"""Conversation orchestrator: runs the tool-calling loop against Claude.

Loop:
    1. messages = history + [user_message]
    2. while iterations < max_iterations:
         response = client.messages.create(...)
         if stop_reason == "end_turn":
             return final text
         if stop_reason == "tool_use":
             execute every tool_use block
             append assistant (with tool_use) + user (tool_results) to messages
             continue
         else:
             return whatever text the model produced (partial)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import anthropic
import structlog

from app.auth.dependencies import AuthContext
from app.config import settings
from app.llm.claude_client import get_client
from app.llm.prompts.erp import erp_context_block, erp_prompt_block
from app.llm.prompts.generic import GENERIC_SYSTEM_PROMPT
from app.llm.tool_dispatcher import dispatch_tool
from app.mcp_client.balaxys import (
    CONTEXT_TOOL,
    BalaxysMcpSession,
    ErpCard,
    select_cards,
    tools_for_role,
)
from app.security.sanitizer import Sanitizer
from app.tools import TOOL_REGISTRY, anthropic_tools

log = structlog.get_logger(__name__)

MAX_ITERATIONS = 5
MAX_TOKENS = 4096


@dataclass
class ToolInvocation:
    name: str
    input: dict[str, Any]
    duration_ms: int
    is_error: bool


@dataclass
class ConversationResult:
    request_id: str
    response_text: str = ""
    tools_invoked: list[ToolInvocation] = field(default_factory=list)
    iterations: int = 0
    stop_reason: str = ""
    tokens_input: int = 0
    tokens_output: int = 0
    duration_ms: int = 0
    # Tarjetas para el drawer del ERP (resultados de tools MCP de Balaxys).
    cards: list[ErpCard] = field(default_factory=list)
    # Detalle de la cache de prompt (solo informativo). ``tokens_input`` ya los
    # incluye convertidos a tokens equivalentes a tarifa de entrada.
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


async def run_conversation(
    user_message: str,
    auth: AuthContext,
    history: list[dict[str, Any]] | None = None,
    *,
    client: anthropic.AsyncAnthropic | None = None,
    system_prompt: str | None = None,
    max_iterations: int = MAX_ITERATIONS,
    sanitizer: Sanitizer | None = None,
    conversation_id: str | None = None,
    vertical: str = "retail",
    erp: BalaxysMcpSession | None = None,
) -> ConversationResult:
    """Run one turn of the conversation through Claude with tool calling.

    Args:
        user_message: the user's natural-language input for this turn.
        auth: trusted identity from the FastAPI dependency. The orchestrator
            forwards ``auth.tenant_id`` to every tool call.
        history: optional list of prior Anthropic messages.
        client: optional injected client (used by tests).
        system_prompt: system prompt already resolved by the caller.
        max_iterations: hard cap on tool-use cycles before forcing a stop.
        vertical: tenant-level attribute ('retail' | 'produccion' | ...).
            Controls which tools are visible to Claude.
        erp: open Balaxys ERP MCP session for this message (or None). Adds the
            ERP tools (no destructive ones) and the ERP system prompt block;
            their calls go to Balaxys instead of the local registry.
    """
    t0 = time.perf_counter()
    result = ConversationResult(request_id=str(uuid4()))

    client = client or get_client()
    system_prompt = system_prompt or GENERIC_SYSTEM_PROMPT
    # Filter by vertical first, then by role within that vertical.
    tools = anthropic_tools(role=auth.role, vertical=vertical) if settings.retail_tools_enabled else []
    erp_tool_names: set[str] = set()
    if erp is not None:
        local_names = {t["name"] for t in tools} | set(TOOL_REGISTRY)
        offered = {t.name for t in tools_for_role(erp.tools, auth.role)}
        for tool_def in erp.anthropic_tools():
            if tool_def["name"] not in offered:
                continue
            if tool_def["name"] in local_names:
                # Una tool local con el mismo nombre gana: nunca se pisa el registry.
                log.warning("orchestrator.erp_tool_name_clash", tool=tool_def["name"])
                continue
            tools.append(tool_def)
            erp_tool_names.add(tool_def["name"])
        system_prompt = system_prompt + erp_prompt_block(erp.instructions)
    # Contexto de la empresa (nombre, moneda, fecha de hoy) pedido directo al ERP:
    # ahorra la ronda en la que el modelo llamaba obtener_contexto_empresa en
    # cada mensaje. Va en un bloque de system aparte para no romper la cache.
    context_block: str | None = None
    if erp is not None and CONTEXT_TOOL in erp_tool_names:
        context_block = erp_context_block(await erp.company_context())
    collected_cards: list[ErpCard] = []

    # Cache de prompt (solo con tools ERP, ~10k tokens de definiciones): un
    # breakpoint en la ultima tool (cachea todas) y otro en el system prompt;
    # el top-level cache_control cachea ademas la conversacion entre las
    # iteraciones del loop. Las tools y el system son estables entre mensajes
    # del mismo usuario (orden fijo, sin fechas ni ids). Sin ERP el request es
    # identico al de siempre.
    request_tools: list[dict[str, Any]] = tools
    request_system: Any = system_prompt
    cache_kwargs: dict[str, Any] = {}
    if erp_tool_names:
        request_tools = [*tools[:-1], {**tools[-1], "cache_control": {"type": "ephemeral"}}]
        request_system = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
        if context_block:
            request_system.append({"type": "text", "text": context_block})
        cache_kwargs = {"cache_control": {"type": "ephemeral"}}

    messages: list[dict[str, Any]] = list(history or [])
    messages.append({"role": "user", "content": user_message})

    for iteration in range(1, max_iterations + 1):
        result.iterations = iteration
        log.info(
            "orchestrator.iteration",
            request_id=result.request_id,
            iteration=iteration,
            tenant=auth.tenant_id,
            user=auth.user_id,
        )

        # Sin ninguna tool (modo solo ERP sin token MCP) no se manda el campo.
        tools_kwargs: dict[str, Any] = {"tools": request_tools} if request_tools else {}
        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=MAX_TOKENS,
            system=request_system,
            messages=messages,
            **tools_kwargs,
            **cache_kwargs,
        )

        # Usage may be missing in mocks; defensive.
        usage = getattr(response, "usage", None)
        if usage is not None:
            cache_write = _int(getattr(usage, "cache_creation_input_tokens", 0))
            cache_read = _int(getattr(usage, "cache_read_input_tokens", 0))
            result.cache_write_tokens += cache_write
            result.cache_read_tokens += cache_read
            # input_tokens excluye lo cacheado. Para que el costo que calcula
            # audit/persister.py (tokens_input * tarifa de entrada) siga siendo
            # exacto, lo cacheado se suma como tokens equivalentes: escritura
            # 1.25x y lectura 0.1x de la tarifa de entrada.
            result.tokens_input += _int(getattr(usage, "input_tokens", 0)) + round(
                cache_write * 1.25 + cache_read * 0.1
            )
            result.tokens_output += _int(getattr(usage, "output_tokens", 0))
        result.stop_reason = response.stop_reason or ""

        if response.stop_reason == "end_turn":
            result.response_text = _extract_text(response.content)
            break

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                tool_input = dict(getattr(block, "input", None) or {})
                is_erp = erp is not None and block.name in erp_tool_names
                if is_erp:
                    # Balaxys ERP (MCP): permisos, empresa y validaciones los
                    # resuelve el ERP con el token del usuario.
                    erp_result = await erp.call(block.name, tool_input)
                    payload, is_error, ms = erp_result.payload, erp_result.is_error, erp_result.duration_ms
                    if erp_result.card is not None:
                        collected_cards.append(erp_result.card)
                else:
                    payload, is_error, ms = await dispatch_tool(
                        block.name, tool_input, auth.tenant_id, auth.role
                    )
                # SANITISER: for non-direccion roles, replace internal ids in
                # the payload with opaque tokens before the LLM sees them.
                # ERP results are excluded: the model needs the real ids to chain
                # ERP tools (e.g. crear_factura_borrador -> preparar_confirmacion_factura)
                # and the ERP already enforces the user's permissions.
                if sanitizer is not None and conversation_id and not is_error and not is_erp:
                    payload = await sanitizer.tokenize_payload(
                        payload,
                        conversation_id=conversation_id,
                        tenant_id=auth.tenant_id,
                        role=auth.role,
                    )
                result.tools_invoked.append(
                    ToolInvocation(
                        name=block.name,
                        input=tool_input,
                        duration_ms=ms,
                        is_error=is_error,
                    )
                )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(payload, default=str, ensure_ascii=False),
                        "is_error": is_error,
                    }
                )

            messages.append({"role": "user", "content": tool_results})
            continue

        # Any other stop_reason: surface whatever text we have and stop.
        result.response_text = _extract_text(response.content)
        break
    else:
        # for/else: loop exhausted without `break` (max_iterations hit).
        result.response_text = (
            f"Iteration limit reached ({max_iterations}). Returning partial result."
        )

    result.cards = select_cards(collected_cards)
    result.duration_ms = int((time.perf_counter() - t0) * 1000)
    log.info(
        "orchestrator.finished",
        request_id=result.request_id,
        iterations=result.iterations,
        stop_reason=result.stop_reason,
        tools=len(result.tools_invoked),
        erp_tools=len(erp_tool_names),
        cards=len(result.cards),
        cache_read=result.cache_read_tokens,
        cache_write=result.cache_write_tokens,
        ms=result.duration_ms,
    )
    return result


def _int(value: Any) -> int:
    return value if isinstance(value, int) else 0


def _extract_text(content: list[Any]) -> str:
    parts = [getattr(b, "text", "") for b in content if getattr(b, "type", None) == "text"]
    return "\n".join(p for p in parts if p).strip()
