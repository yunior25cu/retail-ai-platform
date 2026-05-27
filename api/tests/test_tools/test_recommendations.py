"""Unit tests for get_action_recommendations (tenant 7)."""

from __future__ import annotations

import pytest

from app.tools.recommendations import RecommendationItem, get_action_recommendations


@pytest.mark.asyncio
async def test_get_action_recommendations_top_5_for_tenant_7() -> None:
    rows = await get_action_recommendations(tenant_id=7, limit=5)
    assert 1 <= len(rows) <= 5
    for r in rows:
        RecommendationItem.model_validate(r)
    # priority_rank starts at 1 and is monotone increasing
    ranks = [r["priority_rank"] for r in rows]
    assert ranks == sorted(ranks)
    assert ranks[0] == 1


@pytest.mark.asyncio
async def test_get_action_recommendations_severity_filter() -> None:
    rows = await get_action_recommendations(tenant_id=7, severity="HIGH", limit=20)
    assert all(r["severity"] == "HIGH" for r in rows)


@pytest.mark.asyncio
async def test_get_action_recommendations_unknown_tenant_returns_empty() -> None:
    assert await get_action_recommendations(tenant_id=99) == []


@pytest.mark.asyncio
async def test_action_recommendations_includes_names() -> None:
    rows = await get_action_recommendations(tenant_id=23, limit=10)
    assert len(rows) > 0
    for r in rows:
        assert r.get("sku_name") is not None, f"sku_name missing in {r}"
        assert r.get("store_name") is not None, f"store_name missing in {r}"
