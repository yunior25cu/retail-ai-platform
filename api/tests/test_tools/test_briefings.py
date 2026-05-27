"""Tests for Sub-fase 5.1 composite briefing tools.

Requires tenant 7 data (same as the rest of the test suite).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.tools import TOOL_REGISTRY
from app.tools.briefings import (
    BrandWeeklyReviewOutput,
    ExecutiveWeeklyBriefingOutput,
    GetBrandWeeklyReviewInput,
    GetExecutiveWeeklyBriefingInput,
    GetStoreDailyBriefingInput,
    StoreDailyBriefingOutput,
    _gather_safe,
    get_brand_weekly_review,
    get_executive_weekly_briefing,
    get_store_daily_briefing,
)


# ─────────────────────────────────────────────────────────────────────────────
# Registry — 15 tools, correct roles, is_composite flag
# ─────────────────────────────────────────────────────────────────────────────

def test_registry_has_15_tools() -> None:
    assert len(TOOL_REGISTRY) == 15


def test_exec_weekly_registry() -> None:
    entry = TOOL_REGISTRY["get_executive_weekly_briefing"]
    assert callable(entry["fn"])
    assert entry["anthropic"]["name"] == "get_executive_weekly_briefing"
    assert entry["required_roles"] == ["direccion"]
    assert entry["is_composite"] is True


def test_store_daily_registry() -> None:
    entry = TOOL_REGISTRY["get_store_daily_briefing"]
    assert callable(entry["fn"])
    assert entry["anthropic"]["name"] == "get_store_daily_briefing"
    assert set(entry["required_roles"]) == {"tienda", "marca", "direccion"}
    assert entry["is_composite"] is True


def test_brand_weekly_registry() -> None:
    entry = TOOL_REGISTRY["get_brand_weekly_review"]
    assert callable(entry["fn"])
    assert entry["anthropic"]["name"] == "get_brand_weekly_review"
    assert set(entry["required_roles"]) == {"marca", "direccion"}
    assert entry["is_composite"] is True


def test_existing_composites_marked() -> None:
    assert TOOL_REGISTRY["get_executive_summary"]["is_composite"] is True
    assert TOOL_REGISTRY["get_monthly_executive_briefing"]["is_composite"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Input model validation
# ─────────────────────────────────────────────────────────────────────────────

def test_exec_weekly_input_defaults_none() -> None:
    inp = GetExecutiveWeeklyBriefingInput()
    assert inp.week_id is None


def test_exec_weekly_input_rejects_bad_format() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GetExecutiveWeeklyBriefingInput(week_id="2026-05")


def test_store_daily_input_requires_store_id() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GetStoreDailyBriefingInput()  # store_id is required


def test_store_daily_input_ok() -> None:
    inp = GetStoreDailyBriefingInput(store_id=1)
    assert inp.store_id == 1
    assert inp.week_id is None


def test_brand_weekly_input_requires_brand_id() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GetBrandWeeklyReviewInput()  # brand_id is required


def test_brand_weekly_input_ok() -> None:
    inp = GetBrandWeeklyReviewInput(brand_id=3)
    assert inp.brand_id == 3
    assert inp.week_id is None


# ─────────────────────────────────────────────────────────────────────────────
# _gather_safe — partial failure isolation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gather_safe_partial_failure() -> None:
    """A failing coroutine lands in partial_failures; others still return."""

    async def _ok() -> str:
        return "ok"

    async def _fail() -> str:
        raise RuntimeError("boom")

    results, failures = await _gather_safe(
        ("good_call", _ok()),
        ("bad_call",  _fail()),
    )
    assert results[0] == "ok"
    assert results[1] is None
    assert failures == ["bad_call"]


@pytest.mark.asyncio
async def test_gather_safe_timeout_recorded() -> None:
    """A coroutine that exceeds the timeout is counted as a partial failure."""

    async def _slow() -> str:
        await asyncio.sleep(10)
        return "never"

    results, failures = await _gather_safe(
        ("slow_call", _slow()),
        timeout=0.05,
    )
    assert results[0] is None
    assert "slow_call" in failures


# ─────────────────────────────────────────────────────────────────────────────
# Live DB — get_executive_weekly_briefing
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exec_weekly_briefing_tenant_7() -> None:
    result = await get_executive_weekly_briefing(tenant_id=7)
    assert result is not None
    out = ExecutiveWeeklyBriefingOutput.model_validate(result)
    assert out.revenue > 0
    assert out.week_id.startswith("20")
    assert len(out.top_brands) <= 5
    assert len(out.top_alerts) <= 3
    assert len(out.top_actions) <= 3
    assert "_composition" in result
    assert "_partial_failures" in result
    assert isinstance(result["_partial_failures"], list)


@pytest.mark.asyncio
async def test_exec_weekly_briefing_unknown_tenant_returns_none() -> None:
    result = await get_executive_weekly_briefing(tenant_id=99999)
    assert result is None


@pytest.mark.asyncio
async def test_exec_weekly_briefing_top_brands_ordered_by_revenue() -> None:
    result = await get_executive_weekly_briefing(tenant_id=7)
    assert result is not None
    brands = result["top_brands"]
    if len(brands) >= 2:
        revenues = [b["revenue"] for b in brands]
        assert revenues == sorted(revenues, reverse=True)


@pytest.mark.asyncio
async def test_exec_weekly_briefing_partial_failure_propagates() -> None:
    """Patch one Phase-2 sub-call to raise; result still returns with failure recorded."""
    with patch(
        "app.tools.briefings.fetch_action_recommendations",
        new_callable=AsyncMock,
        side_effect=RuntimeError("db timeout"),
    ):
        result = await get_executive_weekly_briefing(tenant_id=7)

    assert result is not None
    assert "action_recommendations" in result["_partial_failures"]
    assert result["top_actions"] == []


# ─────────────────────────────────────────────────────────────────────────────
# Live DB — get_store_daily_briefing
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_store_daily_briefing_tenant_7_store_1() -> None:
    from app.db.queries import fetch_store_dashboard

    # Find a valid store_id for tenant 7.
    rows = await fetch_store_dashboard(tenant_id=7)
    if not rows:
        pytest.skip("no store data for tenant 7")
    store_id = rows[0]["store_id"]

    result = await get_store_daily_briefing(tenant_id=7, store_id=store_id)
    assert result is not None
    out = StoreDailyBriefingOutput.model_validate(result)
    assert out.store_id == store_id
    assert out.revenue >= 0
    assert "_composition" in result
    assert "_partial_failures" in result
    assert isinstance(result["critical_skus"], list)
    assert all(s["status_color"] in ("RED", "YELLOW") for s in result["critical_skus"])


@pytest.mark.asyncio
async def test_store_daily_briefing_unknown_store_returns_none() -> None:
    result = await get_store_daily_briefing(tenant_id=7, store_id=999999)
    assert result is None


@pytest.mark.asyncio
async def test_store_daily_critical_skus_bounded() -> None:
    from app.db.queries import fetch_store_dashboard

    rows = await fetch_store_dashboard(tenant_id=7)
    if not rows:
        pytest.skip("no store data for tenant 7")
    store_id = rows[0]["store_id"]

    result = await get_store_daily_briefing(tenant_id=7, store_id=store_id)
    if result is None:
        pytest.skip("no data for this store")
    assert len(result["critical_skus"]) <= 10


# ─────────────────────────────────────────────────────────────────────────────
# Live DB — get_brand_weekly_review
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_brand_weekly_review_tenant_7() -> None:
    from app.db.queries import fetch_brand_performance

    rows = await fetch_brand_performance(tenant_id=7)
    if not rows:
        pytest.skip("no brand data for tenant 7")
    brand_id = rows[0]["brand_id"]

    result = await get_brand_weekly_review(tenant_id=7, brand_id=brand_id)
    assert result is not None
    out = BrandWeeklyReviewOutput.model_validate(result)
    assert out.brand_id == brand_id
    assert out.revenue >= 0
    assert "_composition" in result
    assert "_partial_failures" in result
    assert isinstance(result["velocity_by_segment"], list)


@pytest.mark.asyncio
async def test_brand_weekly_review_unknown_brand_returns_none() -> None:
    result = await get_brand_weekly_review(tenant_id=7, brand_id=999999)
    assert result is None


@pytest.mark.asyncio
async def test_brand_weekly_velocity_segments_are_abcd() -> None:
    from app.db.queries import fetch_brand_performance

    rows = await fetch_brand_performance(tenant_id=7)
    if not rows:
        pytest.skip("no brand data for tenant 7")
    brand_id = rows[0]["brand_id"]

    result = await get_brand_weekly_review(tenant_id=7, brand_id=brand_id)
    if result is None:
        pytest.skip("no data for this brand")
    segments = {s["segment"] for s in result["velocity_by_segment"]}
    assert segments <= {"A", "B", "C", "D"}


@pytest.mark.asyncio
async def test_brand_weekly_partial_failure_propagates() -> None:
    """Patch velocity fetch to fail; brand KPIs still return, failure recorded."""
    from app.db.queries import fetch_brand_performance

    rows = await fetch_brand_performance(tenant_id=7)
    if not rows:
        pytest.skip("no brand data for tenant 7")
    brand_id = rows[0]["brand_id"]

    with patch(
        "app.tools.briefings.fetch_velocity_segmentation",
        new_callable=AsyncMock,
        side_effect=RuntimeError("db timeout"),
    ):
        result = await get_brand_weekly_review(tenant_id=7, brand_id=brand_id)

    assert result is not None
    assert "velocity_segmentation" in result["_partial_failures"]
    assert result["velocity_by_segment"] == []
