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
from app.llm.prompts.generic import GENERIC_SYSTEM_PROMPT
from app.llm.tool_dispatcher import dispatch_tool
from app.security.sanitizer import Sanitizer
from app.tools import anthropic_tools

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
) -> ConversationResult:
    """Run one turn of the conversation through Claude with tool calling.

    Args:
        user_message: the user's natural-language input for this turn.
        auth: trusted identity from the FastAPI dependency. The orchestrator
            forwards ``auth.tenant_id`` to every tool call.
        history: optional list of prior Anthropic messages. Stateless for 4.3
            (client passes the history back); persistence arrives in 4.5.
        client: optional injected client (used by tests; production calls
            ``get_client()``).
        system_prompt: override the default system prompt. Phase 5 will pick
            per-role prompts.
        max_iterations: hard cap on tool-use cycles before forcing a stop.
    """
    t0 = time.perf_counter()
    result = ConversationResult(request_id=str(uuid4()))

    client = client or get_client()
    system_prompt = system_prompt or GENERIC_SYSTEM_PROMPT
    # Filter by role so the LLM never sees tools it cannot call.
    tools = anthropic_tools(role=auth.role)

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

        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        # Usage may be missing in mocks; defensive.
        usage = getattr(response, "usage", None)
        if usage is not None:
            result.tokens_input += getattr(usage, "input_tokens", 0) or 0
            result.tokens_output += getattr(usage, "output_tokens", 0) or 0
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
                payload, is_error, ms = await dispatch_tool(
                    block.name, tool_input, auth.tenant_id, auth.role
                )
                # SANITISER: for non-direccion roles, replace internal ids in
                # the payload with opaque tokens before the LLM sees them.
                if sanitizer is not None and conversation_id and not is_error:
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

    result.duration_ms = int((time.perf_counter() - t0) * 1000)
    log.info(
        "orchestrator.finished",
        request_id=result.request_id,
        iterations=result.iterations,
        stop_reason=result.stop_reason,
        tools=len(result.tools_invoked),
        ms=result.duration_ms,
    )
    return result


def _extract_text(content: list[Any]) -> str:
    parts = [getattr(b, "text", "") for b in content if getattr(b, "type", None) == "text"]
    return "\n".join(p for p in parts if p).strip()
