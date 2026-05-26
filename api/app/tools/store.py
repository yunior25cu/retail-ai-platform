"""Tool: get_store_dashboard.

Returns per-store KPIs for the latest week from ``gold.vw_store_dashboard``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.db.queries import fetch_store_dashboard

TOOL_NAME = "get_store_dashboard"
TOOL_DESCRIPTION = (
    "Per-store KPIs for the latest reported week: units sold, revenue, gross margin, "
    "ticket count, stock units and value, plus counts of zero-stock / obsolete SKUs. "
    "Use this to answer 'how is store X doing this week' or to list all stores ranked "
    "by revenue."
)


class GetStoreDashboardInput(BaseModel):
    store_id: int | None = Field(
        default=None,
        description="Optional. Return only this store. If omitted, returns all active stores.",
    )
    week_id: str | None = Field(
        default=None,
        description=(
            "Optional ISO year-week, format 'YYYY-Www' (e.g. '2026-W22'). "
            "Only the latest reported week is supported in this version; passing "
            "an older week will return an empty list."
        ),
        pattern=r"^\d{4}-W\d{2}$",
    )


class StoreDashboardItem(BaseModel):
    iso_year_week: str
    store_id: int
    store_code: str
    store_name: str
    block_AB: str
    is_store_flag: bool
    units_sold: float
    revenue: float
    cogs: float
    gross_margin: float
    gross_margin_pct: float | None
    tickets: int
    avg_ticket: float | None
    stock_units: float
    stock_value: float
    skus_in_store: int
    skus_zero_stock: int
    skus_obsolete: int


async def get_store_dashboard(
    tenant_id: int,
    *,
    store_id: int | None = None,
    week_id: str | None = None,
) -> list[dict[str, Any]]:
    rows = await fetch_store_dashboard(tenant_id, store_id=store_id, week_id=week_id)
    return [StoreDashboardItem.model_validate(r).model_dump(mode="json") for r in rows]
