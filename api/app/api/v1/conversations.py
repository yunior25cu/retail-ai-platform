"""GET /api/v1/conversations/{id} — conversation context summary.

Returns conversation metadata and the last N turns (as configured by
MEMORY_TURNS_PER_REQUEST) so a client can show the user what context Claude
has in memory before sending the next message.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.dependencies import AuthContext, get_auth_context
from app.config import settings
from app.db.conversation import count_messages, load_conversation, load_recent_messages

router = APIRouter(prefix="/conversations", tags=["conversations"])


class RecentMessage(BaseModel):
    role: str = Field(description="'user' or 'assistant'")
    text: str = Field(description="Plain-text excerpt of the message content.")


class ConversationSummary(BaseModel):
    conversation_id: str
    user_role: str = Field(description="Role of the user who owns this conversation.")
    total_messages: int = Field(description="Total messages stored (all turns).")
    total_turns: int = Field(description="total_messages // 2.")
    memory_turns: int = Field(
        description="How many turns Claude will see on the next request (MEMORY_TURNS_PER_REQUEST)."
    )
    recent_messages: list[RecentMessage] = Field(
        description="Last memory_turns turns in chronological order."
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationSummary,
    summary="Conversation context summary",
    description=(
        "Returns metadata and the last **MEMORY_TURNS_PER_REQUEST** turns of the "
        "conversation. Useful for clients that want to show the user what context "
        "Claude has in memory before sending the next message. "
        "The conversation must belong to the caller's tenant."
    ),
    responses={
        404: {
            "description": "Conversation not found or belongs to a different tenant",
            "content": {"application/json": {"example": {"detail": "conversation_not_found_for_tenant"}}},
        },
    },
)
async def get_conversation_summary(
    conversation_id: str,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> ConversationSummary:
    conv = await load_conversation(conversation_id, tenant_id=auth.tenant_id)
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="conversation_not_found_for_tenant",
        )

    total = await count_messages(conversation_id)
    recent_raw = await load_recent_messages(
        conversation_id, tenant_id=auth.tenant_id
    )

    recent_messages = [
        RecentMessage(role=m["role"], text=_extract_text(m["content"]))
        for m in recent_raw
    ]

    return ConversationSummary(
        conversation_id=conversation_id,
        user_role=conv["user_role"],
        total_messages=total,
        total_turns=total // 2,
        memory_turns=settings.memory_turns_per_request,
        recent_messages=recent_messages,
    )


def _extract_text(content: Any) -> str:
    """Extract a plain-text preview from an Anthropic message content value."""
    if isinstance(content, str):
        return content[:500]
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", ""))[:300])
            elif isinstance(block, str):
                parts.append(block[:300])
        return " ".join(parts)[:500]
    return str(content)[:500]
