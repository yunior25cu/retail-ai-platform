"""Unit tests for get_audit_trail (role-restricted).

Inserts a synthetic row into api_audit.ai_audit_log, queries via the tool,
and cleans up. Uses a unique uuid per test run to avoid collisions.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.db.connection import execute_query
from app.tools.audit import AuditTrailItem, get_audit_trail


@pytest.mark.asyncio
async def test_get_audit_trail_returns_none_for_missing_request() -> None:
    fake = str(uuid4())
    assert await get_audit_trail(tenant_id=7, request_id=fake) is None


@pytest.mark.asyncio
async def test_get_audit_trail_returns_row_when_present() -> None:
    request_id = str(uuid4())
    tools_invoked = [{"name": "get_active_alerts", "duration_ms": 12, "is_error": False}]

    insert_sql = """
        INSERT INTO api_audit.ai_audit_log
            (request_id, tenant_id, user_id, user_role, user_question,
             tools_invoked, final_response, tokens_input, tokens_output,
             duration_ms, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """
    await execute_query(
        insert_sql,
        (
            request_id, 7, "test-user", "direccion", "test question",
            json.dumps(tools_invoked), "test response",
            100, 50, 500, "SUCCESS",
        ),
    )

    try:
        row = await get_audit_trail(tenant_id=7, request_id=request_id)
        assert row is not None
        item = AuditTrailItem.model_validate(row)
        assert item.user_id == "test-user"
        assert item.tools_invoked == tools_invoked
        assert item.tokens_input == 100
        assert item.tokens_output == 50
        assert item.status == "SUCCESS"
    finally:
        # Cleanup
        await execute_query(
            "DELETE FROM api_audit.ai_audit_log WHERE request_id = CAST(? AS UNIQUEIDENTIFIER);",
            (request_id,),
        )


@pytest.mark.asyncio
async def test_get_audit_trail_enforces_tenant_isolation() -> None:
    """Tenant=99 cannot see tenant=7's audit row."""
    request_id = str(uuid4())
    await execute_query(
        """
        INSERT INTO api_audit.ai_audit_log
            (request_id, tenant_id, user_id, user_role, status)
        VALUES (?, ?, ?, ?, ?);
        """,
        (request_id, 7, "u", "direccion", "SUCCESS"),
    )
    try:
        assert await get_audit_trail(tenant_id=99, request_id=request_id) is None
        # tenant 7 sees it
        row = await get_audit_trail(tenant_id=7, request_id=request_id)
        assert row is not None and row["request_id"].lower() == request_id.lower()
    finally:
        await execute_query(
            "DELETE FROM api_audit.ai_audit_log WHERE request_id = CAST(? AS UNIQUEIDENTIFIER);",
            (request_id,),
        )
