"""Unit tests for app.llm.tool_dispatcher."""

from __future__ import annotations

import pytest

from app.llm.tool_dispatcher import dispatch_tool


@pytest.mark.asyncio
async def test_dispatch_known_tool_returns_rows_for_tenant_7() -> None:
    payload, is_error, ms = await dispatch_tool(
        "get_active_alerts", {"limit": 3}, tenant_id=7
    )
    assert not is_error
    assert isinstance(payload, list)
    assert len(payload) <= 3
    assert isinstance(ms, int) and ms >= 0


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_is_error() -> None:
    payload, is_error, _ = await dispatch_tool("nonexistent_tool", {}, tenant_id=7)
    assert is_error
    assert payload == {"error": "unknown_tool", "tool": "nonexistent_tool"}


@pytest.mark.asyncio
async def test_dispatch_invalid_input_is_error() -> None:
    payload, is_error, _ = await dispatch_tool(
        "get_active_alerts", {"limit": -1}, tenant_id=7
    )
    assert is_error
    assert payload["error"] == "invalid_input"
    assert isinstance(payload.get("details"), list)


@pytest.mark.asyncio
async def test_dispatch_drops_tenant_id_from_input() -> None:
    """Security invariant: LLM cannot escape its tenant by sending tenant_id."""
    # auth context says tenant=7; LLM tries to query tenant=99
    payload, is_error, _ = await dispatch_tool(
        "get_active_alerts", {"limit": 3, "tenant_id": 99}, tenant_id=7
    )
    assert not is_error
    assert isinstance(payload, list)
    # Tenant 99 has no data; tenant 7 has many. If injection succeeded,
    # we'd see an empty list.
    assert len(payload) > 0


@pytest.mark.asyncio
async def test_dispatch_tenant_isolation_returns_empty_for_unknown_tenant() -> None:
    payload, is_error, _ = await dispatch_tool(
        "get_active_alerts", {"limit": 50}, tenant_id=99
    )
    assert not is_error
    assert payload == []


@pytest.mark.asyncio
async def test_dispatch_role_gated_tool_rejects_wrong_role() -> None:
    """get_audit_trail requires role='direccion'."""
    payload, is_error, _ = await dispatch_tool(
        "get_audit_trail",
        {"request_id": "00000000-0000-0000-0000-000000000000"},
        tenant_id=7,
        role="marca",
    )
    assert is_error
    assert payload["error"] == "forbidden_for_role"
    assert "direccion" in [r.lower() for r in payload["required"]]


@pytest.mark.asyncio
async def test_dispatch_role_gated_tool_accepts_correct_role() -> None:
    payload, is_error, _ = await dispatch_tool(
        "get_audit_trail",
        {"request_id": "00000000-0000-0000-0000-000000000000"},
        tenant_id=7,
        role="direccion",
    )
    # role passes; the request_id does not exist => None (not an error)
    assert not is_error
    assert payload is None
