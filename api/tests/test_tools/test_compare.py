"""Unit tests for compare_periods (tenant 7).

Uses 2026-W18 and 2026-W19 which were validated in Phase 3 to have sales for
both PRO BRAND and ESSENTIAL.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.tools.compare import (
    ComparePeriodsItem,
    GetComparePeriodsInput,
    compare_periods,
)

W_A = "2026-W18"
W_B = "2026-W19"


@pytest.mark.asyncio
async def test_compare_periods_tenant_scope_returns_single_row() -> None:
    rows = await compare_periods(
        tenant_id=7, metric="revenue_net", period_a=W_A, period_b=W_B, scope="tenant"
    )
    assert len(rows) == 1
    item = ComparePeriodsItem.model_validate(rows[0])
    assert item.scope_id is None
    assert item.value_a > 0  # W18 had multi-brand sales
    assert item.value_b > 0
    # delta_pct should be defined since value_a != 0
    assert item.delta_pct is not None


@pytest.mark.asyncio
async def test_compare_periods_brand_scope_returns_one_row_per_brand() -> None:
    rows = await compare_periods(
        tenant_id=7, metric="revenue_net", period_a=W_A, period_b=W_B, scope="brand"
    )
    assert len(rows) >= 1
    for r in rows:
        ComparePeriodsItem.model_validate(r)
        assert isinstance(r["scope_id"], int)
        assert isinstance(r["scope_label"], str)


@pytest.mark.asyncio
async def test_compare_periods_store_scope_returns_per_store_breakdown() -> None:
    rows = await compare_periods(
        tenant_id=7, metric="units_sold_net", period_a=W_A, period_b=W_B, scope="store"
    )
    assert len(rows) >= 1
    for r in rows:
        ComparePeriodsItem.model_validate(r)


@pytest.mark.asyncio
async def test_compare_periods_unknown_tenant_zero_rows() -> None:
    rows = await compare_periods(
        tenant_id=99, metric="revenue_net", period_a=W_A, period_b=W_B, scope="tenant"
    )
    # tenant scope yields exactly one row with 0/0
    assert len(rows) == 1
    assert rows[0]["value_a"] == 0
    assert rows[0]["value_b"] == 0
    assert rows[0]["delta_pct"] is None  # divide-by-zero guard


def test_input_model_rejects_invalid_metric() -> None:
    with pytest.raises(ValidationError):
        GetComparePeriodsInput(
            metric="DROP TABLE foo", period_a=W_A, period_b=W_B
        )


def test_input_model_rejects_invalid_week_format() -> None:
    with pytest.raises(ValidationError):
        GetComparePeriodsInput(metric="revenue_net", period_a="2026-19", period_b=W_B)
