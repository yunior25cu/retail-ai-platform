"""Unit tests for get_active_alerts against the POC tenant (id=7)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.tools import TOOL_REGISTRY
from app.tools.alerts import (
    ActiveAlertItem,
    GetActiveAlertsInput,
    get_active_alerts,
)


@pytest.mark.asyncio
async def test_get_active_alerts_happy_path_tenant_7() -> None:
    rows = await get_active_alerts(tenant_id=7, limit=50)
    assert isinstance(rows, list)
    # Tenant 7 was validated in Phase 3 to have ~46 active alerts.
    assert len(rows) > 0
    # Each row must validate against the typed output schema.
    for r in rows:
        ActiveAlertItem.model_validate(r)
    # Returned in descending impact order.
    impacts = [r["estimated_impact_usd"] or 0 for r in rows]
    assert impacts == sorted(impacts, reverse=True)


@pytest.mark.asyncio
async def test_get_active_alerts_unknown_tenant_returns_empty() -> None:
    rows = await get_active_alerts(tenant_id=99, limit=50)
    assert rows == []


@pytest.mark.asyncio
async def test_get_active_alerts_filter_by_severity() -> None:
    rows = await get_active_alerts(tenant_id=7, severity="HIGH", limit=50)
    assert all(r["severity"] == "HIGH" for r in rows)


@pytest.mark.asyncio
async def test_get_active_alerts_limit_is_respected() -> None:
    rows = await get_active_alerts(tenant_id=7, limit=3)
    assert len(rows) <= 3


def test_input_model_rejects_invalid_limit() -> None:
    with pytest.raises(ValidationError):
        GetActiveAlertsInput(limit=0)
    with pytest.raises(ValidationError):
        GetActiveAlertsInput(limit=10_000)


def test_input_model_rejects_invalid_severity() -> None:
    with pytest.raises(ValidationError):
        GetActiveAlertsInput(severity="CRITICAL")  # not in AlertSeverity


def test_registry_includes_active_alerts() -> None:
    entry = TOOL_REGISTRY["get_active_alerts"]
    assert callable(entry["fn"])
    assert entry["input_model"] is GetActiveAlertsInput
    assert entry["anthropic"]["name"] == "get_active_alerts"
    assert "input_schema" in entry["anthropic"]
    assert entry["anthropic"]["input_schema"]["type"] == "object"
