"""Tool: get_brand_performance.

Returns per-brand KPIs for the latest week from ``gold.vw_brand_performance``,
including plan-vs-actual ratios.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.db.queries import fetch_brand_performance

TOOL_NAME = "get_brand_performance"
TOOL_DESCRIPTION = (
    "Per-brand KPIs for the latest reported week: units sold, revenue, gross margin, "
    "plan-vs-actual ratios (units and revenue), stock units and value, and counts of "
    "zero-stock / obsolete SKUs. Use this to answer 'how is brand X performing vs plan'."
)


class GetBrandPerformanceInput(BaseModel):
    brand_id: int | None = Field(
        default=None,
        description="Optional. Return only this brand. If omitted, returns all brands.",
    )
    week_id: str | None = Field(
        default=None,
        description=(
            "Optional ISO year-week, format 'YYYY-Www' (e.g. '2026-W22'). "
            "Only the latest reported week is supported in this version."
        ),
        pattern=r"^\d{4}-W\d{2}$",
    )


class BrandPerformanceItem(BaseModel):
    iso_year_week: str
    brand_id: int
    brand_name: str
    units_sold: float
    revenue: float
    cogs: float
    gross_margin: float
    gross_margin_pct: float | None
    planned_units: float
    planned_revenue: float
    units_vs_plan_pct: float | None
    revenue_vs_plan_pct: float | None
    stock_units: float
    stock_value: float
    skus_count: int
    skus_zero_stock: int
    skus_obsolete: int


async def get_brand_performance(
    tenant_id: int,
    *,
    brand_id: int | None = None,
    week_id: str | None = None,
) -> list[dict[str, Any]]:
    rows = await fetch_brand_performance(tenant_id, brand_id=brand_id, week_id=week_id)
    return [BrandPerformanceItem.model_validate(r).model_dump(mode="json") for r in rows]
