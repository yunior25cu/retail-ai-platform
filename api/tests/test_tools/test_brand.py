"""Unit tests for get_brand_performance against the POC tenant (id=7)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.tools import TOOL_REGISTRY
from app.tools.brand import (
    BrandPerformanceItem,
    GetBrandPerformanceInput,
    get_brand_performance,
)


@pytest.mark.asyncio
async def test_get_brand_performance_happy_path_tenant_7() -> None:
    rows = await get_brand_performance(tenant_id=7)
    assert isinstance(rows, list)
    assert len(rows) == 3  # validated in Phase 3 — emp7 has 3 seeded brands
    for r in rows:
        BrandPerformanceItem.model_validate(r)
    # At least one brand should have non-zero revenue.
    assert any(r["revenue"] > 0 for r in rows)


@pytest.mark.asyncio
async def test_get_brand_performance_filters_by_brand_id() -> None:
    rows = await get_brand_performance(tenant_id=7, brand_id=1)  # PRO BRAND
    assert len(rows) == 1
    assert rows[0]["brand_id"] == 1
    assert rows[0]["brand_name"] == "PRO BRAND"


@pytest.mark.asyncio
async def test_get_brand_performance_unknown_tenant_returns_empty() -> None:
    rows = await get_brand_performance(tenant_id=99)
    assert rows == []


@pytest.mark.asyncio
async def test_get_brand_performance_unknown_brand_returns_empty() -> None:
    rows = await get_brand_performance(tenant_id=7, brand_id=9999)
    assert rows == []


def test_input_model_rejects_invalid_week_id_format() -> None:
    with pytest.raises(ValidationError):
        GetBrandPerformanceInput(week_id="abc")


def test_registry_includes_brand_performance() -> None:
    entry = TOOL_REGISTRY["get_brand_performance"]
    assert callable(entry["fn"])
    assert entry["input_model"] is GetBrandPerformanceInput
    assert entry["anthropic"]["name"] == "get_brand_performance"
