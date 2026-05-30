"""Tests for GET /api/v1/internal/metrics (sub-phase 6.6)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.v1.internal import _METRICS_CACHE, _top_tool_from_invocations
from app.auth.service_auth import ServiceAuthContext, get_service_auth_context
from app.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_svc(tenant_id: int = 7, role: str = "direccion") -> ServiceAuthContext:
    return ServiceAuthContext(
        tenant_id=tenant_id,
        user_id=1,
        role=role,
        conversation_id=None,
        request_id="test-request-id",
    )


@pytest.fixture()
def metrics_client():
    svc = _make_svc()

    async def _override() -> ServiceAuthContext:
        return svc

    app.dependency_overrides[get_service_auth_context] = _override
    _METRICS_CACHE.clear()
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_service_auth_context, None)
    _METRICS_CACHE.clear()


# ---------------------------------------------------------------------------
# top_tool helper — pure unit test, no DB / HTTP
# ---------------------------------------------------------------------------

def test_top_tool_from_string_list() -> None:
    rows = [
        '["get_active_alerts", "get_store_dashboard"]',
        '["get_active_alerts"]',
        '["get_brand_performance"]',
    ]
    name, count = _top_tool_from_invocations(rows)
    assert name == "get_active_alerts"
    assert count == 2


def test_top_tool_from_dict_list() -> None:
    rows = [
        '[{"name": "get_sku_detail"}, {"name": "get_sku_detail"}]',
        '[{"tool": "get_velocity_segmentation"}]',
    ]
    name, count = _top_tool_from_invocations(rows)
    assert name == "get_sku_detail"
    assert count == 2


def test_top_tool_empty_input_returns_empty_string() -> None:
    assert _top_tool_from_invocations([]) == ("", 0)


def test_top_tool_ignores_malformed_json() -> None:
    rows = ['not-json', '{"x": 1}', '["good_tool"]']
    name, count = _top_tool_from_invocations(rows)
    assert name == "good_tool"
    assert count == 1


# ---------------------------------------------------------------------------
# Endpoint — orchestration with all DB calls mocked
# ---------------------------------------------------------------------------

def _patch_db(*, aggregates: dict, tools: list[str], by_role: list[dict],
              by_day: list[dict], longest: int):
    """Returns a stack of patch context managers for every DB helper."""
    return [
        patch(
            "app.api.v1.internal.fetch_metrics_aggregates",
            new=AsyncMock(return_value=aggregates),
        ),
        patch(
            "app.api.v1.internal.fetch_metrics_tools_invoked",
            new=AsyncMock(return_value=tools),
        ),
        patch(
            "app.api.v1.internal.fetch_metrics_by_role",
            new=AsyncMock(return_value=by_role),
        ),
        patch(
            "app.api.v1.internal.fetch_metrics_by_day",
            new=AsyncMock(return_value=by_day),
        ),
        patch(
            "app.api.v1.internal.fetch_metrics_longest_conversation_turns",
            new=AsyncMock(return_value=longest),
        ),
    ]


def test_metrics_endpoint_assembles_response(metrics_client: TestClient) -> None:
    patches = _patch_db(
        aggregates={
            "total_queries": 47,
            "total_cost_usd": 1.4067,
            "active_users": 3,
            "avg_duration_ms": 8420.4,
        },
        tools=['["get_active_alerts"]'] * 5,
        by_role=[
            {"user_role": "direccion", "cnt": 12},
            {"user_role": "tienda", "cnt": 19},
        ],
        by_day=[{"date": "2026-05-01", "cnt": 3}],
        longest=12,
    )
    for p in patches:
        p.start()
    try:
        resp = metrics_client.get("/api/v1/internal/metrics")
    finally:
        for p in patches:
            p.stop()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_queries"] == 47
    assert body["total_cost_usd"] == 1.4067
    assert body["active_users"] == 3
    assert body["avg_duration_ms"] == 8420  # rounded to int
    assert body["top_tool"] == "get_active_alerts"
    assert body["top_tool_count"] == 5
    assert body["longest_conversation_turns"] == 12
    assert body["queries_by_role"] == {"direccion": 12, "tienda": 19}
    assert body["queries_by_day"] == [{"date": "2026-05-01", "count": 3}]
    assert len(body["period"]) == 7  # YYYY-MM


def test_metrics_cache_hit_skips_db(metrics_client: TestClient) -> None:
    aggregates = {"total_queries": 1, "total_cost_usd": 0.0,
                  "active_users": 1, "avg_duration_ms": 0.0}
    agg_mock = AsyncMock(return_value=aggregates)
    other = AsyncMock(return_value=[])
    longest = AsyncMock(return_value=0)

    with patch("app.api.v1.internal.fetch_metrics_aggregates", new=agg_mock), \
         patch("app.api.v1.internal.fetch_metrics_tools_invoked", new=other), \
         patch("app.api.v1.internal.fetch_metrics_by_role", new=other), \
         patch("app.api.v1.internal.fetch_metrics_by_day", new=other), \
         patch(
             "app.api.v1.internal.fetch_metrics_longest_conversation_turns",
             new=longest,
         ):
        metrics_client.get("/api/v1/internal/metrics")
        metrics_client.get("/api/v1/internal/metrics")

    assert agg_mock.call_count == 1


def test_metrics_zero_data_returns_safe_defaults(metrics_client: TestClient) -> None:
    """No audit rows yet → all zeros, no exceptions."""
    patches = _patch_db(
        aggregates={
            "total_queries": 0,
            "total_cost_usd": 0.0,
            "active_users": 0,
            "avg_duration_ms": 0.0,
        },
        tools=[],
        by_role=[],
        by_day=[],
        longest=0,
    )
    for p in patches:
        p.start()
    try:
        resp = metrics_client.get("/api/v1/internal/metrics")
    finally:
        for p in patches:
            p.stop()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_queries"] == 0
    assert body["top_tool"] == ""
    assert body["top_tool_count"] == 0
    assert body["queries_by_role"] == {}
    assert body["queries_by_day"] == []
