"""Unit tests for get_executive_summary (tenant 7)."""

from __future__ import annotations

import pytest

from app.tools import TOOL_REGISTRY
from app.tools.executive import ExecutiveSummary, get_executive_summary


@pytest.mark.asyncio
async def test_get_executive_summary_returns_full_envelope_for_tenant_7() -> None:
    result = await get_executive_summary(tenant_id=7)
    assert result is not None
    # Output must validate against the typed model
    summary = ExecutiveSummary.model_validate(result)
    assert summary.week_id.startswith("2026-W")
    assert summary.revenue > 0
    # Top alerts capped at 3
    assert len(summary.top_alerts) <= 3
    # If revenue > 0 and ticket count > 0, avg_ticket must be > 0
    if summary.tickets > 0:
        assert summary.avg_ticket is not None and summary.avg_ticket > 0


@pytest.mark.asyncio
async def test_get_executive_summary_unknown_tenant_returns_none() -> None:
    assert await get_executive_summary(tenant_id=99) is None


def test_registry_includes_executive_summary() -> None:
    entry = TOOL_REGISTRY["get_executive_summary"]
    assert callable(entry["fn"])
    assert entry["anthropic"]["name"] == "get_executive_summary"
    assert "required_roles" not in entry  # not role-gated
