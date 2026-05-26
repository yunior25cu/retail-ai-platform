"""POST /api/v1/chat — orchestrated, audited, sanitised conversation.

Flow:
    1. Resolve identity (JWT or mock dep)
    2. Rate-limit check (tenant + user + tokens-day) -> 429 if breached
    3. Conversation: create new or load existing (tenant-scoped)
    4. Reconstruct message history from DB
    5. Run orchestrator (tool calling loop with sanitiser hook)
    6. Persist user + assistant messages
    7. Persist audit row in api_audit.ai_audit_log
    8. Record token usage in the rate limiter
    9. Detokenise final text for non-direccion roles
   10. Return ChatResponse
"""

from __future__ import annotations

import time
from typing import Annotated, Any
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.audit.persister import persist_audit_row
from app.auth.dependencies import AuthContext, get_auth_context
from app.db.conversation import (
    append_message,
    create_conversation,
    load_conversation,
    load_messages,
    touch_conversation,
)
from app.llm.orchestrator import run_conversation
from app.llm.prompts.generic import GENERIC_SYSTEM_PROMPT
from app.security.rate_limiter import RateLimitExceeded, limiter
from app.security.sanitizer import Sanitizer

router = APIRouter(prefix="/chat", tags=["chat"])
log = structlog.get_logger(__name__)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10_000)
    conversation_id: str | None = Field(
        default=None,
        description="If provided, the conversation must belong to the caller's tenant.",
    )


class ToolUseLog(BaseModel):
    name: str
    duration_ms: int
    is_error: bool


class ChatResponse(BaseModel):
    request_id: str
    conversation_id: str
    response: str
    tools_used: list[ToolUseLog]
    iterations: int
    stop_reason: str
    tokens_input: int
    tokens_output: int
    duration_ms: int


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> ChatResponse:
    t0 = time.perf_counter()

    # 1. Rate limit (requests + tokens budget pre-check)
    try:
        limiter.check_and_record_request(auth.tenant_id, auth.user_id)
        limiter.check_token_budget(auth.tenant_id)
    except RateLimitExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"scope": e.scope, "message": e.detail},
        ) from e

    # 2. Conversation (create or load tenant-scoped)
    conv_id = await _resolve_conversation(payload.conversation_id, auth)

    # 3. Reconstruct history
    history = await load_messages(conv_id)

    # 4. Orchestrator with sanitiser
    sanitizer = Sanitizer()
    audit_status = "SUCCESS"
    audit_error: str | None = None
    try:
        result = await run_conversation(
            user_message=payload.message,
            auth=auth,
            history=history,
            sanitizer=sanitizer,
            conversation_id=conv_id,
        )
    except RuntimeError as e:
        # Config error (ANTHROPIC_API_KEY missing, etc.)
        await _persist_failure_audit(
            conv_id, auth, payload.message, str(e), int((time.perf_counter() - t0) * 1000)
        )
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        await _persist_failure_audit(
            conv_id, auth, payload.message, str(e), int((time.perf_counter() - t0) * 1000)
        )
        raise HTTPException(status_code=500, detail="internal_error") from e

    # 5. Persist messages (user + assistant)
    await append_message(conversation_id=conv_id, role="user", content=payload.message)
    await append_message(
        conversation_id=conv_id, role="assistant", content=result.response_text
    )
    await touch_conversation(conv_id)

    # 6. Audit row
    if result.stop_reason and result.stop_reason != "end_turn":
        audit_status = "PARTIAL"
    await persist_audit_row(
        request_id=result.request_id,
        conversation_id=conv_id,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        user_role=auth.role,
        user_question=payload.message,
        system_prompt=GENERIC_SYSTEM_PROMPT,
        tools_invoked=result.tools_invoked,
        final_response=result.response_text,
        tokens_input=result.tokens_input,
        tokens_output=result.tokens_output,
        duration_ms=result.duration_ms,
        status=audit_status,
        error_msg=audit_error,
    )

    # 7. Token usage to rate limiter (after the fact)
    limiter.record_tokens(auth.tenant_id, result.tokens_input + result.tokens_output)

    # 8. Detokenise the response text for non-direccion roles
    final_text = await sanitizer.detokenize_text(
        result.response_text, conversation_id=conv_id, role=auth.role
    )

    return ChatResponse(
        request_id=result.request_id,
        conversation_id=conv_id,
        response=final_text,
        tools_used=[
            ToolUseLog(name=t.name, duration_ms=t.duration_ms, is_error=t.is_error)
            for t in result.tools_invoked
        ],
        iterations=result.iterations,
        stop_reason=result.stop_reason,
        tokens_input=result.tokens_input,
        tokens_output=result.tokens_output,
        duration_ms=result.duration_ms,
    )


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
async def _resolve_conversation(
    requested_id: str | None, auth: AuthContext
) -> str:
    if requested_id:
        existing = await load_conversation(requested_id, tenant_id=auth.tenant_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="conversation_not_found_for_tenant",
            )
        return str(existing["conversation_id"])
    return await create_conversation(
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        user_role=auth.role,
    )


async def _persist_failure_audit(
    conv_id: str | None,
    auth: AuthContext,
    user_question: str,
    error: str,
    duration_ms: int,
) -> None:
    """Best-effort audit row for failures. Generates its own request_id since
    the orchestrator never produced one."""
    await persist_audit_row(
        request_id=str(uuid4()),
        conversation_id=conv_id,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        user_role=auth.role,
        user_question=user_question,
        system_prompt=GENERIC_SYSTEM_PROMPT,
        tools_invoked=None,
        final_response=None,
        tokens_input=0,
        tokens_output=0,
        duration_ms=duration_ms,
        status="ERROR",
        error_msg=error,
    )
