"""Persist /chat request audit rows to ``api_audit.ai_audit_log``.

Cost approximation uses the Anthropic Sonnet 4.x price list as of 2026-05:
    input  $3 per 1M tokens
    output $15 per 1M tokens
Adjust ``PRICE_PER_MILLION_*`` constants when pricing changes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from typing import Any

import structlog

from app.db.connection import execute_query

log = structlog.get_logger(__name__)

PRICE_PER_MILLION_INPUT = 3.0
PRICE_PER_MILLION_OUTPUT = 15.0


def estimate_cost_usd(tokens_input: int, tokens_output: int) -> float:
    return (
        (tokens_input or 0) * PRICE_PER_MILLION_INPUT / 1_000_000
        + (tokens_output or 0) * PRICE_PER_MILLION_OUTPUT / 1_000_000
    )


def hash_text(text: str | None) -> str | None:
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def persist_audit_row(
    *,
    request_id: str,
    conversation_id: str | None,
    tenant_id: int,
    user_id: str,
    user_role: str,
    user_question: str | None,
    system_prompt: str | None,
    tools_invoked: list[Any] | None,
    final_response: str | None,
    tokens_input: int,
    tokens_output: int,
    duration_ms: int,
    status: str,
    error_msg: str | None = None,
) -> None:
    """Insert one row in api_audit.ai_audit_log. Never raises (logs on error)."""
    tools_json = None
    if tools_invoked:
        try:
            normalised = [_to_jsonable(t) for t in tools_invoked]
            tools_json = json.dumps(normalised, default=str, ensure_ascii=False)
        except Exception as e:  # noqa: BLE001
            log.warning("audit.tools_serialisation_failed", error=str(e))

    cost = estimate_cost_usd(tokens_input, tokens_output)

    sql = """
        INSERT INTO api_audit.ai_audit_log
            (request_id, conversation_id, tenant_id, user_id, user_role,
             user_question, system_prompt_hash,
             tools_invoked, tool_responses_hash, final_response,
             tokens_input, tokens_output, cost_usd, duration_ms,
             status, error_msg)
        VALUES (
            CAST(? AS UNIQUEIDENTIFIER),
            CASE WHEN ? IS NULL THEN NULL ELSE CAST(? AS UNIQUEIDENTIFIER) END,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        );
    """
    params = (
        request_id,
        conversation_id, conversation_id,
        tenant_id,
        user_id,
        user_role,
        user_question,
        hash_text(system_prompt),
        tools_json,
        hash_text(tools_json),
        final_response,
        tokens_input,
        tokens_output,
        round(cost, 6),
        duration_ms,
        status,
        error_msg,
    )
    try:
        await execute_query(sql, params)
        log.info(
            "audit.persisted",
            request_id=request_id,
            tenant_id=tenant_id,
            status=status,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            cost_usd=round(cost, 6),
        )
    except Exception as e:  # noqa: BLE001
        log.exception("audit.persist_failed", request_id=request_id, error=str(e))


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):  # pydantic
        return value.model_dump()
    return value
