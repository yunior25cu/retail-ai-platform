"""Tool: get_audit_trail (restricted to DIRECCION role).

Returns the full audit row for a previously executed /chat request, so
Dirección can trace which tools were called and what payloads were exchanged.
Tenant isolation is enforced at the SQL level.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.db.queries import fetch_audit_trail

TOOL_NAME = "get_audit_trail"
TOOL_DESCRIPTION = (
    "Retrieve the audit trail for a previous /chat request_id, including the "
    "user question, tools invoked with their inputs, token and cost accounting, "
    "and the final response. Restricted to the DIRECCION role."
)
REQUIRED_ROLES = ["direccion"]


class GetAuditTrailInput(BaseModel):
    request_id: str = Field(
        ..., min_length=8, max_length=64, description="UUID of the prior request."
    )


class AuditTrailItem(BaseModel):
    request_id: str
    conversation_id: str | None
    user_id: str
    user_role: str
    timestamp_utc: str
    user_question: str | None
    tools_invoked: list[dict] | None
    final_response: str | None
    tokens_input: int | None
    tokens_output: int | None
    cost_usd: float | None
    duration_ms: int | None
    status: str
    error_msg: str | None


async def get_audit_trail(
    tenant_id: int,
    *,
    request_id: str,
) -> dict[str, Any] | None:
    row = await fetch_audit_trail(tenant_id, request_id)
    if row is None:
        return None

    # tools_invoked is stored as NVARCHAR(MAX) JSON; parse defensively.
    raw_tools = row.get("tools_invoked")
    tools_parsed: list[dict] | None
    if raw_tools is None:
        tools_parsed = None
    else:
        try:
            parsed = json.loads(raw_tools)
            tools_parsed = parsed if isinstance(parsed, list) else None
        except (TypeError, json.JSONDecodeError):
            tools_parsed = None

    item = AuditTrailItem(
        request_id=row["request_id"],
        conversation_id=row["conversation_id"],
        user_id=row["user_id"],
        user_role=row["user_role"],
        timestamp_utc=row["timestamp_utc"],
        user_question=row["user_question"],
        tools_invoked=tools_parsed,
        final_response=row["final_response"],
        tokens_input=row["tokens_input"],
        tokens_output=row["tokens_output"],
        cost_usd=float(row["cost_usd"]) if row["cost_usd"] is not None else None,
        duration_ms=row["duration_ms"],
        status=row["status"],
        error_msg=row["error_msg"],
    )
    return item.model_dump(mode="json")
