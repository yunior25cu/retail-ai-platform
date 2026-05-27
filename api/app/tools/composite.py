"""Tool: get_monthly_executive_briefing.

Director-level monthly briefing that bundles in a single round-trip:
  - Full monthly KPI snapshot (via get_monthly_summary internals)
  - Top 3 active alerts by dollar impact (from vw_active_alerts)
  - Top 5 brands by monthly revenue (from vw_brand_performance_monthly)

This is a Phase 5 preview tool that validates the composite-tool pattern before
the full agent layer is built. It saves ~3 LLM round-trips vs. chaining the
individual tools.

required_roles: direccion
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.db.queries import (
    fetch_active_alerts,
    fetch_monthly_brand_performance,
    fetch_monthly_totals,
    fetch_latest_month,
)
from app.tools.monthly import (
    MonthlySummaryOutput,
    TopBrandItem,
    TopStoreItem,
    _parse_scope,
    _prev_month,
    _gather,
)
from app.db.queries import fetch_monthly_store_dashboard

TOOL_NAME = "get_monthly_executive_briefing"
TOOL_DESCRIPTION = (
    "Director-level monthly briefing: KPIs for the specified month (or latest), "
    "month-over-month comparison, top-3 active alerts by dollar impact, and top-5 "
    "brands by monthly revenue. Single round-trip equivalent to combining "
    "get_monthly_summary + get_active_alerts + brand rankings. "
    "Use for 'informe ejecutivo de mayo', 'briefing mensual', executive overviews."
)

REQUIRED_ROLES = ["direccion"]


class GetMonthlyExecutiveBriefingInput(BaseModel):
    year_month: str | None = Field(
        default=None,
        description=(
            "Calendar month in YYYY-MM format (e.g. '2026-04'). "
            "If omitted, defaults to the latest month with sales data."
        ),
    )


class TopAlertItem(BaseModel):
    alert_id:             str
    alert_type:           str
    severity:             str
    store_id:             int | None
    sku_id:               int | None
    brand_id:             int | None
    suggested_action:     str | None
    estimated_impact_usd: float | None


class MonthlyBrandSummary(BaseModel):
    brand_id:         int
    brand_name:       str | None
    revenue:          float
    units_sold:       float
    gross_margin_pct: float | None
    revenue_vs_plan:  float | None


class MonthlyExecutiveBriefingOutput(BaseModel):
    year_month:          str
    units_sold:          float
    revenue:             float
    cogs:                float
    gross_margin:        float
    gross_margin_pct:    float | None
    discount_amount:     float
    revenue_prev_month:  float | None
    revenue_vs_prev_pct: float | None
    units_vs_prev_pct:   float | None
    top_alerts:          list[TopAlertItem]
    top_brands:          list[MonthlyBrandSummary]


async def get_monthly_executive_briefing(
    tenant_id: int,
    *,
    year_month: str | None = None,
) -> dict[str, Any] | None:
    resolved = year_month or await fetch_latest_month(tenant_id)
    if resolved is None:
        return None

    prev = _prev_month(resolved)

    current_row, prev_row, alerts_raw, brand_rows = await _gather(
        fetch_monthly_totals(tenant_id, year_month=resolved),
        fetch_monthly_totals(tenant_id, year_month=prev),
        fetch_active_alerts(tenant_id, limit=3),
        fetch_monthly_brand_performance(tenant_id, year_month=resolved),
    )

    if current_row is None:
        return None

    revenue    = float(current_row["revenue"]     or 0)
    units_sold = float(current_row["units_sold"]  or 0)
    cogs       = float(current_row["cogs"]        or 0)
    margin     = float(current_row["gross_margin"] or 0)
    discount   = float(current_row["discount_amount"] or 0)

    prev_revenue = float(prev_row["revenue"]    or 0) if prev_row else None
    prev_units   = float(prev_row["units_sold"] or 0) if prev_row else None

    top_alerts = [
        TopAlertItem(
            alert_id=a["alert_id"],
            alert_type=a["alert_type"],
            severity=a["severity"],
            store_id=a.get("store_id"),
            sku_id=a.get("sku_id"),
            brand_id=a.get("brand_id"),
            suggested_action=a.get("suggested_action"),
            estimated_impact_usd=(
                float(a["estimated_impact_usd"]) if a.get("estimated_impact_usd") is not None else None
            ),
        )
        for a in alerts_raw
    ]

    top_brands = [
        MonthlyBrandSummary(
            brand_id=r["brand_id"],
            brand_name=r["brand_name"],
            revenue=float(r["revenue"] or 0),
            units_sold=float(r["units_sold"] or 0),
            gross_margin_pct=float(r["gross_margin_pct"]) if r["gross_margin_pct"] is not None else None,
            revenue_vs_plan=float(r["revenue_vs_plan_pct"]) if r.get("revenue_vs_plan_pct") is not None else None,
        )
        for r in brand_rows[:5]
    ]

    briefing = MonthlyExecutiveBriefingOutput(
        year_month=resolved,
        units_sold=units_sold,
        revenue=revenue,
        cogs=cogs,
        gross_margin=margin,
        gross_margin_pct=(margin / revenue) if revenue > 0 else None,
        discount_amount=discount,
        revenue_prev_month=prev_revenue,
        revenue_vs_prev_pct=(
            (revenue - prev_revenue) / prev_revenue
            if prev_revenue and prev_revenue != 0 else None
        ),
        units_vs_prev_pct=(
            (units_sold - prev_units) / prev_units
            if prev_units and prev_units != 0 else None
        ),
        top_alerts=top_alerts,
        top_brands=top_brands,
    )
    return briefing.model_dump(mode="json")
