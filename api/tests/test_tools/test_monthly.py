"""Tests for get_monthly_summary (tenant 7).

Integration tests assume 11_monthly_views.sql has been deployed and that
tenant 7 has sales data for at least one month.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.tools import TOOL_REGISTRY
from app.tools.monthly import (
    GetMonthlySummaryInput,
    MonthlySummaryOutput,
    get_monthly_summary,
    _prev_month,
)
from app.db.queries import fetch_latest_month, fetch_monthly_totals


# ----------------------------------------------------------------------------
# Helper / pure-function tests
# ----------------------------------------------------------------------------
def test_prev_month_normal() -> None:
    assert _prev_month("2026-05") == "2026-04"
    assert _prev_month("2026-01") == "2025-12"
    assert _prev_month("2025-12") == "2025-11"


# ----------------------------------------------------------------------------
# Input model validation
# ----------------------------------------------------------------------------
def test_input_model_accepts_valid_month() -> None:
    inp = GetMonthlySummaryInput(year_month="2026-04")
    assert inp.year_month == "2026-04"
    assert inp.scope is None


def test_input_model_rejects_invalid_month_format() -> None:
    with pytest.raises(ValidationError):
        GetMonthlySummaryInput(year_month="2026-4")   # missing leading zero

    with pytest.raises(ValidationError):
        GetMonthlySummaryInput(year_month="26-04")    # 2-digit year


def test_input_model_rejects_invalid_scope() -> None:
    with pytest.raises(ValidationError):
        GetMonthlySummaryInput(scope="brand")         # missing :N

    with pytest.raises(ValidationError):
        GetMonthlySummaryInput(scope="company:5")     # unsupported kind


def test_input_model_accepts_valid_scope() -> None:
    assert GetMonthlySummaryInput(scope="brand:5").scope == "brand:5"
    assert GetMonthlySummaryInput(scope="store:12").scope == "store:12"


# ----------------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------------
def test_registry_includes_monthly_summary() -> None:
    entry = TOOL_REGISTRY["get_monthly_summary"]
    assert callable(entry["fn"])
    assert entry["anthropic"]["name"] == "get_monthly_summary"
    assert "required_roles" in entry
    assert "direccion" in entry["required_roles"]
    assert "marca" in entry["required_roles"]


# ----------------------------------------------------------------------------
# Live DB tests (require 11_monthly_views.sql deployed + tenant 7 data)
# ----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_monthly_summary_returns_data_for_tenant_7() -> None:
    result = await get_monthly_summary(tenant_id=7)
    assert result is not None
    summary = MonthlySummaryOutput.model_validate(result)
    assert summary.year_month.count("-") == 1
    assert len(summary.year_month) == 7           # YYYY-MM
    assert summary.revenue > 0
    assert summary.units_sold > 0
    assert 0 <= summary.active_alerts_count


@pytest.mark.asyncio
async def test_get_monthly_summary_unknown_tenant_returns_none() -> None:
    result = await get_monthly_summary(tenant_id=99)
    assert result is None


@pytest.mark.asyncio
async def test_get_monthly_summary_top_brands_bounded() -> None:
    result = await get_monthly_summary(tenant_id=7)
    assert result is not None
    assert len(result["top_brands"]) <= 3
    assert len(result["top_stores"]) <= 3


@pytest.mark.asyncio
async def test_get_monthly_summary_explicit_month() -> None:
    latest = await fetch_latest_month(7)
    assert latest is not None
    result = await get_monthly_summary(tenant_id=7, year_month=latest)
    assert result is not None
    assert result["year_month"] == latest


@pytest.mark.asyncio
async def test_get_monthly_summary_brand_scope() -> None:
    result = await get_monthly_summary(tenant_id=7, scope="brand:1")
    # brand:1 may or may not exist — if it does, result is not None
    # if it doesn't, result is None — both are valid
    if result is not None:
        assert result["top_brands"] == []  # brand-scoped → no top_brands list
        MonthlySummaryOutput.model_validate(result)


@pytest.mark.asyncio
async def test_monthly_aggregates_match_weekly_sum_for_tenant_7() -> None:
    """For each month M, vw_sales_monthly.units_sold_net (summed across all rows)
    must equal the sum of fact_sales_weekly.units_sold_net for the ISO weeks
    assigned to M. Tolerance: 0.01 (decimal rounding).
    """
    from app.db.connection import execute_query

    sql = """
        SELECT
            vm_total.year_month_iso,
            vm_total.monthly_sum,
            fw_total.weekly_sum,
            ABS(vm_total.monthly_sum - fw_total.weekly_sum) AS diff
        FROM (
            SELECT year_month_iso, SUM(units_sold_net) AS monthly_sum
            FROM gold.vw_sales_monthly
            WHERE tenant_id = 7
            GROUP BY year_month_iso
        ) vm_total
        JOIN (
            SELECT dd.year_month_iso, SUM(f.units_sold_net) AS weekly_sum
            FROM gold.fact_sales_weekly f
            JOIN gold.dim_date dd
                ON dd.iso_year_week = f.iso_year_week AND dd.day_of_week = 4
            WHERE f.tenant_id = 7
            GROUP BY dd.year_month_iso
        ) fw_total ON fw_total.year_month_iso = vm_total.year_month_iso
        WHERE ABS(vm_total.monthly_sum - fw_total.weekly_sum) > 0.01;
    """
    mismatches = await execute_query(sql, ())
    assert mismatches == [], (
        f"Monthly aggregate mismatch vs weekly sums: {mismatches}"
    )
