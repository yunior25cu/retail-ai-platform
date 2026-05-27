"""POST /api/v1/internal/chat — service-to-service endpoint.

Called exclusively by ERP backends (e.g. .NET AiAssistantController) that
have already authenticated the end-user and forward the resolved identity via
X-Service-Key / X-Tenant-Id / X-User-Id / X-User-Role headers.

This endpoint mirrors the /api/v1/chat flow but uses ServiceAuthContext
instead of the Bearer-JWT / mock path.  The conversation_id may arrive
either from the X-Conversation-Id header (priority) or the request body.
"""

from __future__ import annotations

import time
from typing import Annotated
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.audit.persister import persist_audit_row
from app.auth.dependencies import AuthContext
from app.auth.service_auth import ServiceAuthContext, get_service_auth_context
from app.db.conversation import (
    append_message,
    create_conversation,
    load_conversation,
    load_recent_messages,
    touch_conversation,
)
from app.llm.orchestrator import run_conversation
from app.llm.prompts import select_prompt
from app.security.rate_limiter import RateLimitExceeded, limiter
from app.security.sanitizer import Sanitizer

router = APIRouter(prefix="/internal", tags=["internal"])
log = structlog.get_logger(__name__)


class InternalChatRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=10_000,
        description="Natural-language question. 1–10 000 characters.",
    )
    conversation_id: str | None = Field(
        default=None,
        description=(
            "UUID of an existing conversation. "
            "Overridden by X-Conversation-Id header if both are present."
        ),
    )


class InternalChatResponse(BaseModel):
    response: str = Field(description="Claude's answer in markdown.")
    conversation_id: str = Field(description="Pass back on the next turn.")
    request_id: str = Field(description="Echoes X-Request-Id (or generated UUID).")
    tools_used: list[str] = Field(description="Names of Gold tools invoked.")
    tokens_input: int
    tokens_output: int
    duration_ms: int


@router.post(
    "/chat",
    response_model=InternalChatResponse,
    summary="Internal chat (service-to-service)",
    description=(
        "Same orchestration flow as /api/v1/chat but authenticated via "
        "X-Service-Key instead of Bearer JWT. Intended for ERP proxy calls only — "
        "never expose this endpoint to the public internet."
    ),
    responses={
        401: {"description": "Missing or invalid X-Service-Key"},
        400: {"description": "Missing X-Tenant-Id or X-User-Id"},
        429: {"description": "Rate limit exceeded"},
        503: {"description": "SERVICE_KEY not configured or Anthropic key missing"},
    },
)
async def internal_chat(
    payload: InternalChatRequest,
    svc: Annotated[ServiceAuthContext, Depends(get_service_auth_context)],
) -> InternalChatResponse:
    t0 = time.perf_counter()

    # Convert to AuthContext (compatible with orchestrator and all downstream helpers)
    auth = AuthContext(
        user_id=str(svc.user_id),
        tenant_id=svc.tenant_id,
        role=svc.role,
    )

    # Rate limiting — same buckets as /chat
    try:
        limiter.check_and_record_request(auth.tenant_id, auth.user_id)
        limiter.check_token_budget(auth.tenant_id)
    except RateLimitExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"scope": e.scope, "message": e.detail},
        ) from e

    system_prompt = select_prompt(auth.role)

    # Conversation: X-Conversation-Id header takes priority over body field
    conv_requested = svc.conversation_id or payload.conversation_id
    conv_id = await _resolve_conversation(conv_requested, auth)

    history = await load_recent_messages(conv_id, tenant_id=auth.tenant_id)
    sanitizer = Sanitizer()

    try:
        result = await run_conversation(
            user_message=payload.message,
            auth=auth,
            history=history,
            system_prompt=system_prompt,
            sanitizer=sanitizer,
            conversation_id=conv_id,
        )
    except RuntimeError as e:
        duration = int((time.perf_counter() - t0) * 1000)
        await _persist_failure_audit(
            conv_id, auth, payload.message, str(e), duration,
            request_id=svc.request_id, system_prompt=system_prompt,
        )
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        duration = int((time.perf_counter() - t0) * 1000)
        await _persist_failure_audit(
            conv_id, auth, payload.message, str(e), duration,
            request_id=svc.request_id, system_prompt=system_prompt,
        )
        raise HTTPException(status_code=500, detail="internal_error") from e

    await append_message(conversation_id=conv_id, role="user", content=payload.message)
    await append_message(
        conversation_id=conv_id, role="assistant", content=result.response_text
    )
    await touch_conversation(conv_id)

    audit_status = (
        "PARTIAL"
        if result.stop_reason and result.stop_reason != "end_turn"
        else "SUCCESS"
    )
    await persist_audit_row(
        request_id=svc.request_id,
        conversation_id=conv_id,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        user_role=auth.role,
        user_question=payload.message,
        system_prompt=system_prompt,
        tools_invoked=result.tools_invoked,
        final_response=result.response_text,
        tokens_input=result.tokens_input,
        tokens_output=result.tokens_output,
        duration_ms=result.duration_ms,
        status=audit_status,
        error_msg=None,
    )

    limiter.record_tokens(auth.tenant_id, result.tokens_input + result.tokens_output)

    final_text = await sanitizer.detokenize_text(
        result.response_text, conversation_id=conv_id, role=auth.role
    )

    return InternalChatResponse(
        response=final_text,
        conversation_id=conv_id,
        request_id=svc.request_id,
        tools_used=[t.name for t in result.tools_invoked],
        tokens_input=result.tokens_input,
        tokens_output=result.tokens_output,
        duration_ms=result.duration_ms,
    )


# ---------------------------------------------------------------------------
# Helpers (mirrors chat.py — kept private to avoid coupling)
# ---------------------------------------------------------------------------

async def _resolve_conversation(conv_id: str | None, auth: AuthContext) -> str:
    if conv_id:
        existing = await load_conversation(conv_id, tenant_id=auth.tenant_id)
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
    *,
    request_id: str,
    system_prompt: str,
) -> None:
    await persist_audit_row(
        request_id=request_id,
        conversation_id=conv_id,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        user_role=auth.role,
        user_question=user_question,
        system_prompt=system_prompt,
        tools_invoked=None,
        final_response=None,
        tokens_input=0,
        tokens_output=0,
        duration_ms=duration_ms,
        status="ERROR",
        error_msg=error,
    )
