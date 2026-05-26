"""Audit persister + endpoint integration."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.audit.persister import estimate_cost_usd, hash_text, persist_audit_row
from app.db.connection import execute_query
from app.llm.orchestrator import ConversationResult, ToolInvocation


def test_estimate_cost_usd_uses_sonnet_pricing() -> None:
    # 1M input + 1M output -> $18 exactly with current constants
    assert abs(estimate_cost_usd(1_000_000, 1_000_000) - 18.0) < 1e-9
    assert estimate_cost_usd(0, 0) == 0


def test_hash_text_is_stable_and_sha256() -> None:
    h = hash_text("hello")
    assert h is not None and len(h) == 64
    assert hash_text("hello") == h
    assert hash_text(None) is None


@pytest.mark.asyncio
async def test_persist_audit_row_writes_to_db() -> None:
    request_id = str(uuid4())
    try:
        await persist_audit_row(
            request_id=request_id,
            conversation_id=None,
            tenant_id=7,
            user_id="test-user",
            user_role="direccion",
            user_question="hi",
            system_prompt="sys",
            tools_invoked=[
                ToolInvocation(
                    name="get_active_alerts", input={"limit": 3}, duration_ms=10, is_error=False
                )
            ],
            final_response="ok",
            tokens_input=100,
            tokens_output=50,
            duration_ms=500,
            status="SUCCESS",
        )
        rows = await execute_query(
            """SELECT user_id, user_role, tokens_input, tokens_output, status,
                      cost_usd, tools_invoked
               FROM api_audit.ai_audit_log
               WHERE request_id = CAST(? AS UNIQUEIDENTIFIER);""",
            (request_id,),
        )
        assert len(rows) == 1
        r = rows[0]
        assert r["user_id"] == "test-user"
        assert r["tokens_input"] == 100
        assert r["tokens_output"] == 50
        # cost = 100*3/1e6 + 50*15/1e6 = 0.000300 + 0.000750 = 0.001050
        assert abs(float(r["cost_usd"]) - 0.00105) < 1e-9
        assert '"get_active_alerts"' in str(r["tools_invoked"])
    finally:
        await execute_query(
            "DELETE FROM api_audit.ai_audit_log WHERE request_id = CAST(? AS UNIQUEIDENTIFIER);",
            (request_id,),
        )


# ---------------------------------------------------------------------------
# Endpoint integration: chat call -> a row appears in ai_audit_log
# ---------------------------------------------------------------------------

def _fake_runner(result: ConversationResult):
    async def fake_run(**kwargs):  # noqa: ANN001, ARG001
        return result

    return fake_run


def test_chat_writes_audit_row_on_success(client: TestClient, monkeypatch) -> None:
    fake = ConversationResult(
        request_id=str(uuid4()),
        response_text="hello",
        iterations=1,
        stop_reason="end_turn",
        tokens_input=42,
        tokens_output=21,
    )
    monkeypatch.setattr("app.api.v1.chat.run_conversation", _fake_runner(fake))

    resp = client.post("/api/v1/chat", json={"message": "audit me"})
    assert resp.status_code == 200

    import asyncio
    rows = asyncio.run(
        execute_query(
            """SELECT tokens_input, tokens_output, status, user_question
               FROM api_audit.ai_audit_log
               WHERE request_id = CAST(? AS UNIQUEIDENTIFIER);""",
            (fake.request_id,),
        )
    )
    assert len(rows) == 1
    assert rows[0]["tokens_input"] == 42
    assert rows[0]["tokens_output"] == 21
    assert rows[0]["status"] == "SUCCESS"
    assert rows[0]["user_question"] == "audit me"

    # Cleanup
    asyncio.run(
        execute_query(
            "DELETE FROM api_audit.ai_audit_log WHERE request_id = CAST(? AS UNIQUEIDENTIFIER);",
            (fake.request_id,),
        )
    )
