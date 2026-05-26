"""Tool: compare_periods.

Compare a single sales metric across two ISO weeks, optionally broken down by
brand or store. Metric and scope are constrained to allowlisted enums so the
dynamic SQL fragment cannot be injected.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.queries import fetch_compare_periods

TOOL_NAME = "compare_periods"
TOOL_DESCRIPTION = (
    "Compare a single sales metric across two ISO weeks, broken down by tenant "
    "(default), brand or store. Returns per-bucket value_a, value_b, absolute "
    "delta and percent delta. Use for 'how did revenue change vs last week' or "
    "'which brand grew the most'."
)


class CompareMetric(StrEnum):
    units_sold_net = "units_sold_net"
    units_sold_gross = "units_sold_gross"
    revenue_net = "revenue_net"
    revenue_gross = "revenue_gross"
    gross_margin = "gross_margin"
    cogs = "cogs"
    tickets = "tickets"
    discount_amount = "discount_amount"


class CompareScope(StrEnum):
    tenant = "tenant"
    brand = "brand"
    store = "store"


class GetComparePeriodsInput(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    metric: CompareMetric = Field(
        ..., description="Metric to compare. Must be in the allowlist."
    )
    period_a: str = Field(
        ..., pattern=r"^\d{4}-W\d{2}$", description="ISO year-week, e.g. '2026-W19'."
    )
    period_b: str = Field(
        ..., pattern=r"^\d{4}-W\d{2}$", description="ISO year-week, e.g. '2026-W22'."
    )
    scope: CompareScope = Field(
        default=CompareScope.tenant,
        description="Breakdown: 'tenant' (single row), 'brand' or 'store'.",
    )


class ComparePeriodsItem(BaseModel):
    scope_id: int | None
    scope_label: str | None
    value_a: float
    value_b: float
    delta_abs: float
    delta_pct: float | None


async def compare_periods(
    tenant_id: int,
    *,
    metric: str,
    period_a: str,
    period_b: str,
    scope: str = "tenant",
) -> list[dict[str, Any]]:
    rows = await fetch_compare_periods(
        tenant_id, metric=metric, period_a=period_a, period_b=period_b, scope=scope
    )

    out: list[dict[str, Any]] = []
    for r in rows:
        a = float(r["value_a"] or 0)
        b = float(r["value_b"] or 0)
        delta_abs = b - a
        delta_pct = (delta_abs / a) if a != 0 else None
        out.append(
            ComparePeriodsItem(
                scope_id=r["scope_id"],
                scope_label=r["scope_label"] or "TOTAL",
                value_a=a,
                value_b=b,
                delta_abs=delta_abs,
                delta_pct=delta_pct,
            ).model_dump(mode="json")
        )
    return out
