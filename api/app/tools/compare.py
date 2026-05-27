"""Tool: compare_periods.

Compare a single sales metric across two periods (ISO weeks or calendar months),
optionally broken down by brand or store. Metric and scope are constrained to
allowlisted enums so the dynamic SQL fragment cannot be injected.

Backward compatible: callers that omit period_type get the original week
behaviour (format 'YYYY-Www').
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.queries import fetch_compare_periods, fetch_compare_periods_monthly

TOOL_NAME = "compare_periods"
TOOL_DESCRIPTION = (
    "Compare a single sales metric across two periods (ISO weeks or calendar months), "
    "broken down by tenant (default), brand or store. Returns per-bucket value_a, "
    "value_b, absolute delta and percent delta. "
    "Use period_type='week' (default) for 'how did revenue change vs last week' or "
    "period_type='month' for 'how did April compare to March'."
)

_WEEK_PAT  = re.compile(r"^\d{4}-W\d{2}$")
_MONTH_PAT = re.compile(r"^\d{4}-\d{2}$")


class CompareMetric(StrEnum):
    units_sold_net  = "units_sold_net"
    units_sold_gross = "units_sold_gross"
    revenue_net     = "revenue_net"
    revenue_gross   = "revenue_gross"
    gross_margin    = "gross_margin"
    cogs            = "cogs"
    tickets         = "tickets"
    discount_amount = "discount_amount"


class CompareScope(StrEnum):
    tenant = "tenant"
    brand  = "brand"
    store  = "store"


class GetComparePeriodsInput(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    period_type: Literal["week", "month"] = Field(
        default="week",
        description=(
            "Periodicity: 'week' expects YYYY-Www format (e.g. '2026-W19'), "
            "'month' expects YYYY-MM format (e.g. '2026-04'). Default: 'week'."
        ),
    )
    metric: CompareMetric = Field(
        ..., description="Metric to compare. Must be in the allowlist."
    )
    period_a: str = Field(
        ...,
        description=(
            "First period. Format: 'YYYY-Www' for weeks (e.g. '2026-W19') "
            "or 'YYYY-MM' for months (e.g. '2026-04')."
        ),
    )
    period_b: str = Field(
        ...,
        description=(
            "Second period. Same format as period_a."
        ),
    )
    scope: CompareScope = Field(
        default=CompareScope.tenant,
        description="Breakdown: 'tenant' (single row), 'brand' or 'store'.",
    )

    @model_validator(mode="after")
    def _validate_period_formats(self) -> "GetComparePeriodsInput":
        if self.period_type == "week":
            pat, expected = _WEEK_PAT, "YYYY-Www (e.g. '2026-W19')"
        else:
            pat, expected = _MONTH_PAT, "YYYY-MM (e.g. '2026-04')"
        for field_name, value in (("period_a", self.period_a), ("period_b", self.period_b)):
            if not pat.match(value):
                raise ValueError(
                    f"{field_name}={value!r} does not match expected format {expected} "
                    f"for period_type='{self.period_type}'"
                )
        return self


class ComparePeriodsItem(BaseModel):
    scope_id:    int | None
    scope_label: str | None
    value_a:     float
    value_b:     float
    delta_abs:   float
    delta_pct:   float | None


async def compare_periods(
    tenant_id: int,
    *,
    metric: str,
    period_a: str,
    period_b: str,
    scope: str = "tenant",
    period_type: str = "week",
) -> list[dict[str, Any]]:
    if period_type == "month":
        rows = await fetch_compare_periods_monthly(
            tenant_id, metric=metric, period_a=period_a, period_b=period_b, scope=scope
        )
    else:
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
