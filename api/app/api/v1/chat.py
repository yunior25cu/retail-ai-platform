"""POST /api/v1/chat — orchestrated conversation with Claude."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.dependencies import AuthContext, get_auth_context
from app.llm.orchestrator import run_conversation

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10_000)
    conversation_id: str | None = Field(
        default=None,
        description="Optional. For 4.3 the server is stateless; persistence arrives in 4.5.",
    )
    history: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional prior messages in Anthropic format. Stateless for 4.3.",
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
    try:
        result = await run_conversation(
            user_message=payload.message,
            auth=auth,
            history=payload.history,
        )
    except RuntimeError as e:
        # Configuration error (e.g. ANTHROPIC_API_KEY not set).
        raise HTTPException(status_code=503, detail=str(e)) from e

    return ChatResponse(
        request_id=result.request_id,
        conversation_id=payload.conversation_id or str(uuid4()),
        response=result.response_text,
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
