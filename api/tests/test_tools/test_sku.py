"""Unit tests for get_sku_detail and get_sku_coverage_status (tenant 7)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.tools.sku import (
    GetSkuCoverageStatusInput,
    GetSkuDetailInput,
    SkuCoverageItem,
    SkuDetail,
    get_sku_coverage_status,
    get_sku_detail,
)


# ---------- get_sku_detail ----------

@pytest.mark.asyncio
async def test_get_sku_detail_for_existing_sku_returns_full_profile() -> None:
    # SKU 7 is the largest overstock contributor per Phase 3 validation
    detail = await get_sku_detail(tenant_id=7, sku_id=7)
    assert detail is not None
    SkuDetail.model_validate(detail)
    assert detail["master"]["sku_id"] == 7
    assert len(detail["sales_last_8w"]) <= 8
    assert isinstance(detail["stock_by_store"], list)
    assert isinstance(detail["active_alerts"], list)


@pytest.mark.asyncio
async def test_get_sku_detail_with_store_filter_narrows_stock() -> None:
    detail_all = await get_sku_detail(tenant_id=7, sku_id=7)
    detail_one = await get_sku_detail(tenant_id=7, sku_id=7, store_id=7)
    assert detail_all is not None and detail_one is not None
    assert all(s["store_id"] == 7 for s in detail_one["stock_by_store"])
    assert len(detail_one["stock_by_store"]) <= len(detail_all["stock_by_store"])


@pytest.mark.asyncio
async def test_get_sku_detail_unknown_sku_returns_none() -> None:
    assert await get_sku_detail(tenant_id=7, sku_id=999_999) is None


def test_input_model_rejects_invalid_sku_id() -> None:
    with pytest.raises(ValidationError):
        GetSkuDetailInput(sku_id=0)
    with pytest.raises(ValidationError):
        GetSkuDetailInput(sku_id=-1)


# ---------- get_sku_coverage_status ----------

@pytest.mark.asyncio
async def test_get_sku_coverage_status_returns_red_first() -> None:
    rows = await get_sku_coverage_status(tenant_id=7, limit=50)
    assert isinstance(rows, list) and len(rows) > 0
    for r in rows:
        SkuCoverageItem.model_validate(r)
    # RED rows should appear before YELLOW/GREEN
    colors = [r["status_color"] for r in rows]
    if "RED" in colors and "GREEN" in colors:
        assert colors.index("RED") < colors.index("GREEN")


@pytest.mark.asyncio
async def test_get_sku_coverage_status_filter_by_status() -> None:
    rows = await get_sku_coverage_status(tenant_id=7, status="RED", limit=20)
    assert all(r["status_color"] == "RED" for r in rows)


@pytest.mark.asyncio
async def test_get_sku_coverage_status_unknown_tenant_returns_empty() -> None:
    assert await get_sku_coverage_status(tenant_id=99, limit=5) == []


def test_coverage_input_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        GetSkuCoverageStatusInput(status="BLUE")
