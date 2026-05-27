"""Tool: get_monthly_summary.

Monthly KPI snapshot for a given calendar month. Includes tenant-level
(or brand/store-scoped) totals, month-over-month comparison, top-3 brands,
top-3 stores, and current active alert count.

required_roles: direccion, marca
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.db.queries import (
    fetch_active_alerts,
    fetch_latest_month,
    fetch_monthly_brand_performance,
    fetch_monthly_store_dashboard,
    fetch_monthly_totals,
)

TOOL_NAME = "get_monthly_summary"
TOOL_DESCRIPTION = (
    "Monthly KPI snapshot for a given calendar month (or the latest month with "
    "data when omitted). Returns units sold, revenue, COGS, gross margin, "
    "month-over-month comparison, top-3 brands by revenue, top-3 stores by "
    "revenue, and current active alert count. "
    "Use for 'cómo fue abril', 'resumen del mes', 'tendencia mensual'. "
    "scope accepts 'brand:N' or 'store:N' to narrow to a specific entity."
)

REQUIRED_ROLES = ["direccion", "marca"]

_MONTH_PAT = re.compile(r"^\d{4}-\d{2}$")


class GetMonthlySummaryInput(BaseModel):
    year_month: str | None = Field(
        default=None,
        description=(
            "Calendar month in YYYY-MM format (e.g. '2026-04'). "
            "If omitted, defaults to the latest month with sales data."
        ),
    )
    scope: str | None = Field(
        default=None,
        description=(
            "Optional entity filter: 'brand:N' (e.g. 'brand:5') or "
            "'store:N' (e.g. 'store:3'). Default: full tenant."
        ),
    )

    @model_validator(mode="after")
    def _validate_fields(self) -> "GetMonthlySummaryInput":
        if self.year_month is not None and not _MONTH_PAT.match(self.year_month):
            raise ValueError(
                f"year_month={self.year_month!r} must match YYYY-MM (e.g. '2026-04')"
            )
        if self.scope is not None and not re.match(r"^(brand|store):\d+$", self.scope):
            raise ValueError(
                f"scope={self.scope!r} must be 'brand:N' or 'store:N' where N is an integer"
            )
        return self


class TopBrandItem(BaseModel):
    brand_id:         int
    brand_name:       str | None
    revenue:          float
    units_sold:       float
    gross_margin_pct: float | None


class TopStoreItem(BaseModel):
    store_id:   int
    store_name: str | None
    revenue:    float
    units_sold: float
    tickets:    int


class MonthlySummaryOutput(BaseModel):
    year_month:              str
    units_sold:              float
    revenue:                 float
    cogs:                    float
    gross_margin:            float
    gross_margin_pct:        float | None
    discount_amount:         float
    revenue_prev_month:      float | None
    revenue_vs_prev_pct:     float | None
    units_vs_prev_pct:       float | None
    top_brands:              list[TopBrandItem]
    top_stores:              list[TopStoreItem]
    active_alerts_count:     int


def _prev_month(ym: str) -> str:
    """'2026-01' → '2025-12',  '2026-05' → '2026-04'."""
    year, month = int(ym[:4]), int(ym[5:])
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def _parse_scope(scope: str | None) -> tuple[int | None, int | None]:
    if scope is None:
        return None, None
    kind, val = scope.split(":", 1)
    if kind == "brand":
        return int(val), None
    return None, int(val)  # store


async def get_monthly_summary(
    tenant_id: int,
    *,
    year_month: str | None = None,
    scope: str | None = None,
) -> dict[str, Any] | None:
    # Resolve month
    resolved = year_month or await fetch_latest_month(tenant_id)
    if resolved is None:
        return None

    scope_brand_id, scope_store_id = _parse_scope(scope)
    prev = _prev_month(resolved)

    # Current + previous month totals (run in parallel-style: two DB calls)
    current_row, prev_row = await _gather(
        fetch_monthly_totals(
            tenant_id,
            year_month=resolved,
            scope_brand_id=scope_brand_id,
            scope_store_id=scope_store_id,
        ),
        fetch_monthly_totals(
            tenant_id,
            year_month=prev,
            scope_brand_id=scope_brand_id,
            scope_store_id=scope_store_id,
        ),
    )

    if current_row is None:
        return None

    revenue      = float(current_row["revenue"]      or 0)
    units_sold   = float(current_row["units_sold"]    or 0)
    cogs         = float(current_row["cogs"]          or 0)
    margin       = float(current_row["gross_margin"]  or 0)
    discount     = float(current_row["discount_amount"] or 0)

    prev_revenue  = float(prev_row["revenue"]    or 0) if prev_row else None
    prev_units    = float(prev_row["units_sold"] or 0) if prev_row else None

    # Top 3 brands (skip when scope is brand-level)
    top_brands: list[TopBrandItem] = []
    if scope_brand_id is None:
        brand_rows = await fetch_monthly_brand_performance(tenant_id, year_month=resolved)
        for r in brand_rows[:3]:
            top_brands.append(
                TopBrandItem(
                    brand_id=r["brand_id"],
                    brand_name=r["brand_name"],
                    revenue=float(r["revenue"] or 0),
                    units_sold=float(r["units_sold"] or 0),
                    gross_margin_pct=float(r["gross_margin_pct"]) if r["gross_margin_pct"] is not None else None,
                )
            )

    # Top 3 stores (skip when scope is store-level)
    top_stores: list[TopStoreItem] = []
    if scope_store_id is None:
        store_rows = await fetch_monthly_store_dashboard(tenant_id, year_month=resolved)
        for r in store_rows[:3]:
            top_stores.append(
                TopStoreItem(
                    store_id=r["store_id"],
                    store_name=r["store_name"],
                    revenue=float(r["revenue"] or 0),
                    units_sold=float(r["units_sold"] or 0),
                    tickets=int(r["tickets"] or 0),
                )
            )

    # Alert count (current state — always week-based)
    alerts = await fetch_active_alerts(tenant_id, limit=500)

    summary = MonthlySummaryOutput(
        year_month=resolved,
        units_sold=units_sold,
        revenue=revenue,
        cogs=cogs,
        gross_margin=margin,
        gross_margin_pct=(margin / revenue) if revenue > 0 else None,
        discount_amount=discount,
        revenue_prev_month=prev_revenue,
        revenue_vs_prev_pct=(
            (revenue - prev_revenue) / prev_revenue if prev_revenue and prev_revenue != 0 else None
        ),
        units_vs_prev_pct=(
            (units_sold - prev_units) / prev_units if prev_units and prev_units != 0 else None
        ),
        top_brands=top_brands,
        top_stores=top_stores,
        active_alerts_count=len(alerts),
    )
    return summary.model_dump(mode="json")


async def _gather(*coros: Any) -> list[Any]:
    """Awaits coroutines sequentially (no asyncio.gather to keep pyodbc happy)."""
    results = []
    for coro in coros:
        results.append(await coro)
    return results
