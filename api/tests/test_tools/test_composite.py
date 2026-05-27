"""Tests for get_monthly_executive_briefing (tenant 7).

Requires 11_monthly_views.sql deployed + tenant 7 data.
"""

from __future__ import annotations

import pytest

from app.tools import TOOL_REGISTRY
from app.tools.composite import (
    GetMonthlyExecutiveBriefingInput,
    MonthlyExecutiveBriefingOutput,
    get_monthly_executive_briefing,
)


# ----------------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------------
def test_registry_includes_monthly_executive_briefing() -> None:
    entry = TOOL_REGISTRY["get_monthly_executive_briefing"]
    assert callable(entry["fn"])
    assert entry["anthropic"]["name"] == "get_monthly_executive_briefing"
    assert "required_roles" in entry
    assert entry["required_roles"] == ["direccion"]


# ----------------------------------------------------------------------------
# Input model
# ----------------------------------------------------------------------------
def test_input_model_defaults_to_none_month() -> None:
    inp = GetMonthlyExecutiveBriefingInput()
    assert inp.year_month is None


# ----------------------------------------------------------------------------
# Live DB
# ----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_monthly_executive_briefing_tenant_7() -> None:
    result = await get_monthly_executive_briefing(tenant_id=7)
    assert result is not None
    briefing = MonthlyExecutiveBriefingOutput.model_validate(result)
    assert briefing.revenue > 0
    assert len(briefing.top_alerts) <= 3
    assert len(briefing.top_brands) <= 5
    assert briefing.year_month.count("-") == 1


@pytest.mark.asyncio
async def test_get_monthly_executive_briefing_unknown_tenant_returns_none() -> None:
    result = await get_monthly_executive_briefing(tenant_id=99)
    assert result is None


@pytest.mark.asyncio
async def test_get_monthly_executive_briefing_explicit_month() -> None:
    from app.db.queries import fetch_latest_month

    latest = await fetch_latest_month(7)
    assert latest is not None
    result = await get_monthly_executive_briefing(tenant_id=7, year_month=latest)
    assert result is not None
    assert result["year_month"] == latest


@pytest.mark.asyncio
async def test_briefing_top_brands_ordered_by_revenue() -> None:
    result = await get_monthly_executive_briefing(tenant_id=7)
    assert result is not None
    brands = result["top_brands"]
    if len(brands) >= 2:
        revenues = [b["revenue"] for b in brands]
        assert revenues == sorted(revenues, reverse=True), (
            "top_brands must be ordered by revenue DESC"
        )
