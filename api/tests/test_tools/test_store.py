"""Unit tests for get_store_dashboard against the POC tenant (id=7)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.tools import TOOL_REGISTRY
from app.tools.store import (
    GetStoreDashboardInput,
    StoreDashboardItem,
    get_store_dashboard,
)


@pytest.mark.asyncio
async def test_get_store_dashboard_happy_path_tenant_7() -> None:
    rows = await get_store_dashboard(tenant_id=7)
    assert isinstance(rows, list)
    assert len(rows) == 4  # validated in Phase 3 — emp7 has 4 active warehouses
    for r in rows:
        StoreDashboardItem.model_validate(r)


@pytest.mark.asyncio
async def test_get_store_dashboard_filters_by_store_id() -> None:
    rows = await get_store_dashboard(tenant_id=7, store_id=7)
    assert len(rows) == 1
    assert rows[0]["store_id"] == 7


@pytest.mark.asyncio
async def test_get_store_dashboard_unknown_tenant_returns_empty() -> None:
    rows = await get_store_dashboard(tenant_id=99)
    assert rows == []


@pytest.mark.asyncio
async def test_get_store_dashboard_unknown_store_returns_empty() -> None:
    rows = await get_store_dashboard(tenant_id=7, store_id=9999)
    assert rows == []


def test_input_model_rejects_invalid_week_id_format() -> None:
    with pytest.raises(ValidationError):
        GetStoreDashboardInput(week_id="2026-21")  # missing 'W'
    with pytest.raises(ValidationError):
        GetStoreDashboardInput(week_id="not-a-week")


def test_registry_includes_store_dashboard() -> None:
    entry = TOOL_REGISTRY["get_store_dashboard"]
    assert callable(entry["fn"])
    assert entry["input_model"] is GetStoreDashboardInput
    assert entry["anthropic"]["name"] == "get_store_dashboard"
