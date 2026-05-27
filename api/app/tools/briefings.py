"""Sub-fase 5.1 composite tools: executive weekly, store daily, brand weekly.

All three use asyncio.gather(return_exceptions=True) with asyncio.wait_for
5-second timeout per sub-call. Partial failures are recorded in the
_partial_failures field so the rest of the response is still returned.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from app.db.queries import (
    fetch_action_recommendations,
    fetch_active_alerts,
    fetch_brand_performance,
    fetch_latest_week,
    fetch_sku_coverage_status,
    fetch_store_dashboard,
    fetch_tenant_distinct_tickets,
    fetch_tenant_plan_totals,
    fetch_tenant_weekly_totals,
    fetch_velocity_segmentation,
)

_GATHER_TIMEOUT = 5.0


async def _gather_safe(
    *named_coros: tuple[str, Any],
    timeout: float = _GATHER_TIMEOUT,
) -> tuple[list[Any], list[str]]:
    """Parallel coroutine execution with per-task timeout and partial failure isolation.

    Each coroutine is wrapped with asyncio.wait_for(timeout=timeout).
    asyncio.gather(return_exceptions=True) ensures one failure never cancels others.
    Returns (results, partial_failures) where failed slots are None in results.
    """

    async def _timed(_coro: Any) -> Any:
        return await asyncio.wait_for(_coro, timeout=timeout)

    raw = await asyncio.gather(
        *[_timed(coro) for _, coro in named_coros],
        return_exceptions=True,
    )

    results: list[Any] = []
    failures: list[str] = []
    for (name, _), outcome in zip(named_coros, raw):
        if isinstance(outcome, BaseException):
            failures.append(name)
            results.append(None)
        else:
            results.append(outcome)
    return results, failures


# ─────────────────────────────────────────────────────────────────────────────
# Tool 1 — get_executive_weekly_briefing
# ─────────────────────────────────────────────────────────────────────────────

TOOL_NAME_EXEC_WEEKLY = "get_executive_weekly_briefing"
TOOL_DESCRIPTION_EXEC_WEEKLY = (
    "Director-level weekly briefing: tenant-wide KPIs (units, revenue, COGS, margin, "
    "tickets), plan vs actual, top-3 active alerts by dollar impact, top-5 brands by "
    "revenue, and top-3 recommended actions — all in one round-trip. "
    "Replaces chaining get_executive_summary + get_active_alerts + get_brand_performance "
    "+ get_action_recommendations (saves ~4 LLM iterations). "
    "Use for 'briefing semanal', 'cómo va la semana', 'resumen ejecutivo de esta semana'."
)
REQUIRED_ROLES_EXEC_WEEKLY = ["direccion"]


class GetExecutiveWeeklyBriefingInput(BaseModel):
    week_id: str | None = Field(
        default=None,
        description=(
            "ISO year-week in YYYY-Www format (e.g. '2026-W21'). "
            "Omit to use the latest reported week."
        ),
        pattern=r"^\d{4}-W\d{2}$",
    )


class _ExecWeeklyAlertItem(BaseModel):
    alert_id: str
    level: str
    alert_type: str
    severity: str
    store_id: int | None = None
    sku_id: int | None = None
    brand_id: int | None = None
    suggested_action: str | None = None
    estimated_impact_usd: float | None = None


class _ExecWeeklyBrandItem(BaseModel):
    brand_id: int
    brand_name: str | None = None
    revenue: float
    units_sold: float
    gross_margin_pct: float | None = None
    revenue_vs_plan_pct: float | None = None


class _ExecWeeklyActionItem(BaseModel):
    alert_id: str
    level: str
    alert_type: str
    severity: str
    store_id: int | None = None
    sku_id: int | None = None
    brand_id: int | None = None
    suggested_action: str | None = None
    estimated_impact_usd: float | None = None
    priority_rank: int | None = None


class ExecutiveWeeklyBriefingOutput(BaseModel):
    week_id: str
    units_sold: float
    revenue: float
    cogs: float
    gross_margin: float
    gross_margin_pct: float | None = None
    tickets: int
    avg_ticket: float | None = None
    planned_units: float | None = None
    planned_revenue: float | None = None
    units_vs_plan_pct: float | None = None
    revenue_vs_plan_pct: float | None = None
    top_alerts: list[_ExecWeeklyAlertItem]
    top_brands: list[_ExecWeeklyBrandItem]
    top_actions: list[_ExecWeeklyActionItem]


async def get_executive_weekly_briefing(
    tenant_id: int,
    *,
    week_id: str | None = None,
) -> dict[str, Any] | None:
    # Phase 1 (serial): resolve the week via the weekly totals fetch.
    totals = await fetch_tenant_weekly_totals(tenant_id, week_id=week_id)
    if totals is None:
        return None
    resolved_week = totals["iso_year_week"]

    # Phase 2 (parallel): remaining sub-calls with 5s timeout each.
    (
        plan_row,
        tickets_raw,
        alerts_raw,
        brand_rows,
        actions_raw,
    ), failures = await _gather_safe(
        ("plan_totals",            fetch_tenant_plan_totals(tenant_id, week_id=resolved_week)),
        ("distinct_tickets",       fetch_tenant_distinct_tickets(tenant_id, week_id=resolved_week)),
        ("active_alerts",          fetch_active_alerts(tenant_id, limit=3)),
        ("brand_performance",      fetch_brand_performance(tenant_id, week_id=resolved_week)),
        ("action_recommendations", fetch_action_recommendations(tenant_id, limit=3)),
    )

    revenue    = float(totals["revenue"]      or 0)
    units_sold = float(totals["units_sold"]   or 0)
    cogs       = float(totals["cogs"]         or 0)
    margin     = float(totals["gross_margin"] or 0)

    tickets: int = tickets_raw if tickets_raw is not None else 0
    planned_units   = float(plan_row["planned_units"]   or 0) if plan_row else None
    planned_revenue = float(plan_row["planned_revenue"] or 0) if plan_row else None

    top_alerts = [
        _ExecWeeklyAlertItem(
            alert_id=str(a["alert_id"]),
            level=a["level"],
            alert_type=a["alert_type"],
            severity=a["severity"],
            store_id=a.get("store_id"),
            sku_id=a.get("sku_id"),
            brand_id=a.get("brand_id"),
            suggested_action=a.get("suggested_action"),
            estimated_impact_usd=(
                float(a["estimated_impact_usd"])
                if a.get("estimated_impact_usd") is not None else None
            ),
        )
        for a in (alerts_raw or [])
    ]

    top_brands = [
        _ExecWeeklyBrandItem(
            brand_id=r["brand_id"],
            brand_name=r.get("brand_name"),
            revenue=float(r["revenue"] or 0),
            units_sold=float(r["units_sold"] or 0),
            gross_margin_pct=(
                float(r["gross_margin_pct"]) if r.get("gross_margin_pct") is not None else None
            ),
            revenue_vs_plan_pct=(
                float(r["revenue_vs_plan_pct"])
                if r.get("revenue_vs_plan_pct") is not None else None
            ),
        )
        for r in (brand_rows or [])[:5]
    ]

    top_actions = [
        _ExecWeeklyActionItem(
            alert_id=str(a["alert_id"]),
            level=a["level"],
            alert_type=a["alert_type"],
            severity=a["severity"],
            store_id=a.get("store_id"),
            sku_id=a.get("sku_id"),
            brand_id=a.get("brand_id"),
            suggested_action=a.get("suggested_action"),
            estimated_impact_usd=(
                float(a["estimated_impact_usd"])
                if a.get("estimated_impact_usd") is not None else None
            ),
            priority_rank=a.get("priority_rank"),
        )
        for a in (actions_raw or [])
    ]

    briefing = ExecutiveWeeklyBriefingOutput(
        week_id=resolved_week,
        units_sold=units_sold,
        revenue=revenue,
        cogs=cogs,
        gross_margin=margin,
        gross_margin_pct=(margin / revenue) if revenue > 0 else None,
        tickets=tickets,
        avg_ticket=(revenue / tickets) if tickets > 0 else None,
        planned_units=planned_units,
        planned_revenue=planned_revenue,
        units_vs_plan_pct=(
            (units_sold / planned_units) if planned_units and planned_units > 0 else None
        ),
        revenue_vs_plan_pct=(
            (revenue / planned_revenue) if planned_revenue and planned_revenue > 0 else None
        ),
        top_alerts=top_alerts,
        top_brands=top_brands,
        top_actions=top_actions,
    )
    result = briefing.model_dump(mode="json")
    result["_composition"] = (
        "weekly_totals(serial) + plan_totals + distinct_tickets + "
        "active_alerts(3) + brand_performance(all→top5) + action_recommendations(3)"
    )
    result["_partial_failures"] = failures
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Tool 2 — get_store_daily_briefing
# ─────────────────────────────────────────────────────────────────────────────

TOOL_NAME_STORE_DAILY = "get_store_daily_briefing"
TOOL_DESCRIPTION_STORE_DAILY = (
    "Per-store weekly briefing for the store manager's daily review: sales KPIs "
    "(revenue, units, margin, tickets, avg ticket), stock health, active alerts "
    "filtered to this store, and top critical SKUs (RED/YELLOW coverage) — in one "
    "round-trip. "
    "Use for 'cómo está la tienda N', 'situación de tienda', 'stock crítico por tienda'."
)
REQUIRED_ROLES_STORE_DAILY = ["tienda", "marca", "direccion"]


class GetStoreDailyBriefingInput(BaseModel):
    store_id: int = Field(description="Numeric store identifier.")
    week_id: str | None = Field(
        default=None,
        description=(
            "ISO year-week in YYYY-Www format (e.g. '2026-W21'). "
            "Omit to use the latest reported week for this store."
        ),
        pattern=r"^\d{4}-W\d{2}$",
    )


class _StoreAlertItem(BaseModel):
    alert_id: str
    alert_type: str
    severity: str
    sku_id: int | None = None
    suggested_action: str | None = None
    estimated_impact_usd: float | None = None


class _CriticalSkuItem(BaseModel):
    sku_id: int
    sku_name: str | None = None
    status_color: str
    stock_units: float
    days_coverage: float | None = None
    suggested_action: str | None = None


class StoreDailyBriefingOutput(BaseModel):
    week_id: str
    store_id: int
    store_name: str | None = None
    store_code: str | None = None
    units_sold: float
    revenue: float
    gross_margin: float
    gross_margin_pct: float | None = None
    tickets: int
    avg_ticket: float | None = None
    stock_units: float
    stock_value: float
    skus_in_store: int
    skus_zero_stock: int
    store_alerts: list[_StoreAlertItem]
    critical_skus: list[_CriticalSkuItem]


async def get_store_daily_briefing(
    tenant_id: int,
    *,
    store_id: int,
    week_id: str | None = None,
) -> dict[str, Any] | None:
    # Resolve week if not provided.
    resolved_week = week_id or await fetch_latest_week(tenant_id, store_id=store_id)
    if resolved_week is None:
        return None

    (store_rows, alerts_raw, coverage_raw), failures = await _gather_safe(
        ("store_dashboard", fetch_store_dashboard(tenant_id, store_id=store_id, week_id=resolved_week)),
        ("active_alerts",   fetch_active_alerts(tenant_id, limit=50)),
        ("sku_coverage",    fetch_sku_coverage_status(tenant_id, store_id=store_id, limit=15)),
    )

    if not store_rows:
        return None
    s = store_rows[0]

    store_alerts = [
        _StoreAlertItem(
            alert_id=str(a["alert_id"]),
            alert_type=a["alert_type"],
            severity=a["severity"],
            sku_id=a.get("sku_id"),
            suggested_action=a.get("suggested_action"),
            estimated_impact_usd=(
                float(a["estimated_impact_usd"])
                if a.get("estimated_impact_usd") is not None else None
            ),
        )
        for a in (alerts_raw or [])
        if a.get("store_id") == store_id
    ]

    critical_skus = [
        _CriticalSkuItem(
            sku_id=r["sku_id"],
            sku_name=r.get("sku_name"),
            status_color=r["status_color"],
            stock_units=float(r["stock_units"] or 0),
            days_coverage=(
                float(r["days_coverage"]) if r.get("days_coverage") is not None else None
            ),
            suggested_action=r.get("suggested_action"),
        )
        for r in (coverage_raw or [])
        if r["status_color"] in ("RED", "YELLOW")
    ][:10]

    revenue = float(s["revenue"] or 0)
    margin  = float(s["gross_margin"] or 0)
    tickets = int(s["tickets"] or 0)

    briefing = StoreDailyBriefingOutput(
        week_id=resolved_week,
        store_id=store_id,
        store_name=s.get("store_name"),
        store_code=s.get("store_code"),
        units_sold=float(s["units_sold"] or 0),
        revenue=revenue,
        gross_margin=margin,
        gross_margin_pct=(margin / revenue) if revenue > 0 else None,
        tickets=tickets,
        avg_ticket=float(s["avg_ticket"]) if s.get("avg_ticket") is not None else None,
        stock_units=float(s["stock_units"] or 0),
        stock_value=float(s["stock_value"] or 0),
        skus_in_store=int(s["skus_in_store"] or 0),
        skus_zero_stock=int(s["skus_zero_stock"] or 0),
        store_alerts=store_alerts,
        critical_skus=critical_skus,
    )
    result = briefing.model_dump(mode="json")
    result["_composition"] = (
        "store_dashboard(1w) + active_alerts(50→filtered_by_store) + "
        "sku_coverage(15→RED/YELLOW)"
    )
    result["_partial_failures"] = failures
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Tool 3 — get_brand_weekly_review
# ─────────────────────────────────────────────────────────────────────────────

TOOL_NAME_BRAND_WEEKLY = "get_brand_weekly_review"
TOOL_DESCRIPTION_BRAND_WEEKLY = (
    "Per-brand weekly review: brand KPIs (revenue, units, margin, plan vs actual, "
    "stock), active alerts filtered to this brand, and ABCD velocity segmentation "
    "summary — in one round-trip. "
    "Use for 'cómo fue la marca X', 'review de marca', 'alertas de la marca', "
    "'velocidad de rotación por marca'."
)
REQUIRED_ROLES_BRAND_WEEKLY = ["marca", "direccion"]


class GetBrandWeeklyReviewInput(BaseModel):
    brand_id: int = Field(description="Numeric brand identifier.")
    week_id: str | None = Field(
        default=None,
        description=(
            "ISO year-week in YYYY-Www format (e.g. '2026-W21'). "
            "Omit to use the latest reported week."
        ),
        pattern=r"^\d{4}-W\d{2}$",
    )


class _BrandAlertItem(BaseModel):
    alert_id: str
    alert_type: str
    severity: str
    store_id: int | None = None
    sku_id: int | None = None
    suggested_action: str | None = None
    estimated_impact_usd: float | None = None


class _VelocitySegment(BaseModel):
    segment: str
    sku_count: int
    revenue_8w: float
    units_8w: float


class BrandWeeklyReviewOutput(BaseModel):
    week_id: str
    brand_id: int
    brand_name: str | None = None
    units_sold: float
    revenue: float
    gross_margin: float
    gross_margin_pct: float | None = None
    planned_revenue: float | None = None
    revenue_vs_plan_pct: float | None = None
    stock_units: float
    skus_count: int
    skus_zero_stock: int
    brand_alerts: list[_BrandAlertItem]
    velocity_by_segment: list[_VelocitySegment]


async def get_brand_weekly_review(
    tenant_id: int,
    *,
    brand_id: int,
    week_id: str | None = None,
) -> dict[str, Any] | None:
    (brand_rows, alerts_raw, velocity_raw), failures = await _gather_safe(
        ("brand_performance",     fetch_brand_performance(tenant_id, brand_id=brand_id, week_id=week_id)),
        ("active_alerts",        fetch_active_alerts(tenant_id, limit=50)),
        ("velocity_segmentation", fetch_velocity_segmentation(tenant_id, brand_id=brand_id, limit=200)),
    )

    if not brand_rows:
        return None
    b = brand_rows[0]  # latest week first (ORDER BY iso_year_week DESC)
    resolved_week = b["iso_year_week"]

    brand_alerts = [
        _BrandAlertItem(
            alert_id=str(a["alert_id"]),
            alert_type=a["alert_type"],
            severity=a["severity"],
            store_id=a.get("store_id"),
            sku_id=a.get("sku_id"),
            suggested_action=a.get("suggested_action"),
            estimated_impact_usd=(
                float(a["estimated_impact_usd"])
                if a.get("estimated_impact_usd") is not None else None
            ),
        )
        for a in (alerts_raw or [])
        if a.get("brand_id") == brand_id
    ]

    # Aggregate velocity rows into per-segment summary.
    seg_agg: dict[str, dict[str, Any]] = {}
    for r in (velocity_raw or []):
        seg = r["velocity_segment"]
        if seg not in seg_agg:
            seg_agg[seg] = {"sku_count": 0, "revenue_8w": 0.0, "units_8w": 0.0}
        seg_agg[seg]["sku_count"] += 1
        seg_agg[seg]["revenue_8w"] += float(r["revenue_8w"] or 0)
        seg_agg[seg]["units_8w"]   += float(r["units_8w"]  or 0)

    velocity_by_segment = [
        _VelocitySegment(segment=seg, **vals)
        for seg, vals in sorted(seg_agg.items())
    ]

    revenue  = float(b["revenue"]      or 0)
    margin   = float(b["gross_margin"] or 0)
    plan_rev = float(b["planned_revenue"] or 0) if b.get("planned_revenue") else None
    rev_plan = (
        float(b["revenue_vs_plan_pct"]) if b.get("revenue_vs_plan_pct") is not None else None
    )

    review = BrandWeeklyReviewOutput(
        week_id=resolved_week,
        brand_id=brand_id,
        brand_name=b.get("brand_name"),
        units_sold=float(b["units_sold"] or 0),
        revenue=revenue,
        gross_margin=margin,
        gross_margin_pct=(margin / revenue) if revenue > 0 else None,
        planned_revenue=plan_rev,
        revenue_vs_plan_pct=rev_plan,
        stock_units=float(b["stock_units"] or 0),
        skus_count=int(b["skus_count"] or 0),
        skus_zero_stock=int(b["skus_zero_stock"] or 0),
        brand_alerts=brand_alerts,
        velocity_by_segment=velocity_by_segment,
    )
    result = review.model_dump(mode="json")
    result["_composition"] = (
        "brand_performance(1w) + active_alerts(50→filtered_by_brand) + "
        "velocity_segmentation(all→ABCD_summary)"
    )
    result["_partial_failures"] = failures
    return result
