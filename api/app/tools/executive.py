"""Tool: get_executive_summary.

Composite tool for the DIRECCION role. Bundles in a single round-trip:
    - Tenant-level weekly totals (units, revenue, COGS, margin, margin %)
    - Plan totals for the same week + vs-plan ratios
    - Real ticket count (COUNT(DISTINCT factura) from source, not the
      semi-additive ``tickets`` column)
    - Top 3 active alerts by estimated dollar impact

By having Claude call this single tool the system saves ~5K input tokens
versus the orchestrator chaining 3+ tools and re-receiving each payload.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.db.queries import (
    fetch_active_alerts,
    fetch_tenant_distinct_tickets,
    fetch_tenant_plan_totals,
    fetch_tenant_weekly_totals,
)

TOOL_NAME = "get_executive_summary"
TOOL_DESCRIPTION = (
    "Director-level snapshot for the latest reported week (or a specified one): "
    "tenant-wide units sold, revenue, COGS, gross margin and margin %, plan vs "
    "actual, real ticket count, plus the top 3 alerts by dollar impact. Use this "
    "when the user asks for an overview, weekly recap, or 'how are we doing'."
)


class GetExecutiveSummaryInput(BaseModel):
    week_id: str | None = Field(
        default=None,
        description=(
            "Optional ISO year-week, format 'YYYY-Www' (e.g. '2026-W22'). "
            "If omitted, defaults to the latest reported week."
        ),
        pattern=r"^\d{4}-W\d{2}$",
    )


class TopAlertItem(BaseModel):
    alert_id: str
    level: str
    alert_type: str
    severity: str
    store_id: int | None
    sku_id: int | None
    brand_id: int | None
    suggested_action: str | None
    estimated_impact_usd: float | None


class ExecutiveSummary(BaseModel):
    week_id: str
    units_sold: float
    revenue: float
    cogs: float
    gross_margin: float
    gross_margin_pct: float | None
    tickets: int
    avg_ticket: float | None
    planned_units: float | None
    planned_revenue: float | None
    units_vs_plan_pct: float | None
    revenue_vs_plan_pct: float | None
    top_alerts: list[TopAlertItem]


async def get_executive_summary(
    tenant_id: int,
    *,
    week_id: str | None = None,
) -> dict[str, Any] | None:
    totals = await fetch_tenant_weekly_totals(tenant_id, week_id=week_id)
    if not totals:
        return None

    resolved_week = totals["iso_year_week"]
    plan = await fetch_tenant_plan_totals(tenant_id, week_id=resolved_week)
    tickets = await fetch_tenant_distinct_tickets(tenant_id, week_id=resolved_week)
    top_alerts_raw = await fetch_active_alerts(tenant_id, limit=3)

    revenue = float(totals["revenue"] or 0)
    margin = float(totals["gross_margin"] or 0)
    planned_units = float(plan["planned_units"] or 0) if plan else 0.0
    planned_revenue = float(plan["planned_revenue"] or 0) if plan else 0.0
    units_sold = float(totals["units_sold"] or 0)

    summary = ExecutiveSummary(
        week_id=resolved_week,
        units_sold=units_sold,
        revenue=revenue,
        cogs=float(totals["cogs"] or 0),
        gross_margin=margin,
        gross_margin_pct=(margin / revenue) if revenue > 0 else None,
        tickets=tickets,
        avg_ticket=(revenue / tickets) if tickets > 0 else None,
        planned_units=planned_units or None,
        planned_revenue=planned_revenue or None,
        units_vs_plan_pct=(units_sold / planned_units) if planned_units > 0 else None,
        revenue_vs_plan_pct=(revenue / planned_revenue) if planned_revenue > 0 else None,
        top_alerts=[TopAlertItem.model_validate(a) for a in top_alerts_raw],
    )
    return summary.model_dump(mode="json")
