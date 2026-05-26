"""Tools: get_sku_detail and get_sku_coverage_status."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from app.db.queries import (
    fetch_active_alerts,
    fetch_sku_coverage_status,
    fetch_sku_master,
    fetch_sku_sales_8w,
    fetch_sku_stock_current,
)

# ----------------------------------------------------------------------------
# get_sku_detail
# ----------------------------------------------------------------------------
SKU_DETAIL_NAME = "get_sku_detail"
SKU_DETAIL_DESCRIPTION = (
    "Full SKU profile: master fields (code, name, brand, category, list price), "
    "last 8 weeks of sales (units, revenue, margin), current stock per store, "
    "active alerts and coverage status. Use when the user names a specific SKU "
    "or asks 'tell me everything about SKU X'."
)


class GetSkuDetailInput(BaseModel):
    sku_id: int = Field(..., gt=0, description="Internal SKU id from dim_sku.")
    store_id: int | None = Field(
        default=None,
        description="Optional store filter; if omitted, returns data across all stores.",
    )


class SkuWeekSales(BaseModel):
    iso_year_week: str
    units_sold: float
    revenue: float
    gross_margin: float
    tickets_semiadd: int


class SkuStoreStock(BaseModel):
    iso_year_week: str
    store_id: int
    stock_units: float
    stock_value: float
    unit_cost: float
    has_zero_stock_flag: bool
    is_obsolete_flag: bool
    days_since_last_sale: int | None
    days_since_last_movement: int | None
    last_sale_date: date | None
    last_movement_date: date | None


class SkuActiveAlert(BaseModel):
    alert_type: str
    severity: str
    metric_value: float | None
    threshold: float | None
    suggested_action: str | None
    estimated_impact_usd: float | None


class SkuDetail(BaseModel):
    master: dict[str, Any]
    sales_last_8w: list[SkuWeekSales]
    stock_by_store: list[SkuStoreStock]
    active_alerts: list[SkuActiveAlert]


async def get_sku_detail(
    tenant_id: int,
    *,
    sku_id: int,
    store_id: int | None = None,
) -> dict[str, Any] | None:
    master = await fetch_sku_master(tenant_id, sku_id)
    if master is None:
        return None

    sales = await fetch_sku_sales_8w(tenant_id, sku_id, store_id=store_id)
    stock = await fetch_sku_stock_current(tenant_id, sku_id, store_id=store_id)
    alerts_raw = await fetch_active_alerts(tenant_id, limit=50)
    sku_alerts = [a for a in alerts_raw if a.get("sku_id") == sku_id]

    detail = SkuDetail(
        master=master,
        sales_last_8w=[SkuWeekSales.model_validate(r) for r in sales],
        stock_by_store=[SkuStoreStock.model_validate(r) for r in stock],
        active_alerts=[SkuActiveAlert.model_validate(a) for a in sku_alerts],
    )
    return detail.model_dump(mode="json")


# ----------------------------------------------------------------------------
# get_sku_coverage_status
# ----------------------------------------------------------------------------
SKU_COVERAGE_NAME = "get_sku_coverage_status"
SKU_COVERAGE_DESCRIPTION = (
    "Per-SKU coverage status with a traffic-light colour (RED / YELLOW / GREEN / GREY): "
    "stock units, days of coverage, target band from business rules, and suggested action. "
    "Filterable by brand, store and/or status colour. Use to surface 'which SKUs need "
    "attention' or to drill into red items."
)


class GetSkuCoverageStatusInput(BaseModel):
    brand_id: int | None = Field(default=None, description="Optional brand filter.")
    store_id: int | None = Field(default=None, description="Optional store filter.")
    status: str | None = Field(
        default=None,
        description="Optional status filter: RED / YELLOW / GREEN / GREY.",
        pattern=r"^(RED|YELLOW|GREEN|GREY)$",
    )
    sku_id: int | None = Field(default=None, description="Optional single-SKU filter.")
    limit: int = Field(default=50, ge=1, le=500)


class SkuCoverageItem(BaseModel):
    iso_year_week: str
    store_id: int
    sku_id: int
    sku_code: str
    sku_name: str
    brand_id: int
    brand_name: str
    category_id: int | None
    stock_units: float
    stock_value: float
    unit_cost: float
    has_zero_stock_flag: bool
    is_obsolete_flag: bool
    days_since_last_sale: int | None
    units_per_day_4w: float
    days_coverage: float | None
    target_min_days: int
    target_max_days: int
    suggested_action: str
    suggested_discount_pct: float | None
    status_color: str


async def get_sku_coverage_status(
    tenant_id: int,
    *,
    brand_id: int | None = None,
    store_id: int | None = None,
    status: str | None = None,
    sku_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    rows = await fetch_sku_coverage_status(
        tenant_id,
        brand_id=brand_id,
        store_id=store_id,
        status=status,
        sku_id=sku_id,
        limit=limit,
    )
    return [SkuCoverageItem.model_validate(r).model_dump(mode="json") for r in rows]
