"""Tests for /api/v1/internal/config + per-tenant gates on /chat and
/suggestions (sub-phase 6.7)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.v1.internal import _SUGGESTIONS_CACHE
from app.auth.service_auth import ServiceAuthContext, get_service_auth_context
from app.db.tenant_config import TenantConfig, invalidate_cache
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
def config_client():
    svc = _make_svc()

    async def _override() -> ServiceAuthContext:
        return svc

    app.dependency_overrides[get_service_auth_context] = _override
    invalidate_cache()
    _SUGGESTIONS_CACHE.clear()
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_service_auth_context, None)
    invalidate_cache()
    _SUGGESTIONS_CACHE.clear()


def _override_role(role: str) -> None:
    svc = _make_svc(role=role)

    async def _override() -> ServiceAuthContext:
        return svc

    app.dependency_overrides[get_service_auth_context] = _override


# ---------------------------------------------------------------------------
# GET /config — defaults
# ---------------------------------------------------------------------------

def test_get_config_returns_defaults(config_client: TestClient) -> None:
    """Tenant with no rows in ai_tenant_config gets dataclass defaults."""
    with patch("app.api.v1.internal.get_tenant_config",
               new=AsyncMock(return_value=TenantConfig())), \
         patch("app.api.v1.internal.get_monthly_spend_usd",
               new=AsyncMock(return_value=0.0)):
        resp = config_client.get("/api/v1/internal/config")

    assert resp.status_code == 200
    body = resp.json()
    assert body["memory_turns"] == 3
    assert body["monthly_budget_usd"] == 0.0
    assert body["budget_alert_pct"] == 80
    assert body["rate_limit_director"] == 50
    assert body["rate_limit_producto"] == 15
    assert body["suggestions_enabled"] is True
    assert body["current_spend_usd"] == 0.0


# ---------------------------------------------------------------------------
# PUT /config — validation matrix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["3", "5", "10"])
def test_update_memory_turns_valid(config_client: TestClient, value: str) -> None:
    with patch("app.api.v1.internal.update_tenant_config",
               new=AsyncMock()) as mock_update:
        resp = config_client.put(
            "/api/v1/internal/config",
            json={"key": "memory_turns", "value": value},
        )
    assert resp.status_code == 200, resp.text
    mock_update.assert_awaited_once()


@pytest.mark.parametrize("value", ["1", "2", "4", "7", "20", "abc"])
def test_update_memory_turns_invalid(config_client: TestClient, value: str) -> None:
    with patch("app.api.v1.internal.update_tenant_config", new=AsyncMock()):
        resp = config_client.put(
            "/api/v1/internal/config",
            json={"key": "memory_turns", "value": value},
        )
    assert resp.status_code == 422


def test_update_budget_zero_is_valid(config_client: TestClient) -> None:
    """Budget = 0 means unlimited, not 'invalid zero'."""
    with patch("app.api.v1.internal.update_tenant_config",
               new=AsyncMock()) as mock_update:
        resp = config_client.put(
            "/api/v1/internal/config",
            json={"key": "monthly_budget_usd", "value": "0"},
        )
    assert resp.status_code == 200
    mock_update.assert_awaited_once()


def test_update_budget_negative_rejected(config_client: TestClient) -> None:
    with patch("app.api.v1.internal.update_tenant_config", new=AsyncMock()):
        resp = config_client.put(
            "/api/v1/internal/config",
            json={"key": "monthly_budget_usd", "value": "-5"},
        )
    assert resp.status_code == 422


def test_update_rate_limit_out_of_range(config_client: TestClient) -> None:
    """Rate limits must be in [1, 200]."""
    with patch("app.api.v1.internal.update_tenant_config", new=AsyncMock()):
        for value in ("0", "201", "1000"):
            resp = config_client.put(
                "/api/v1/internal/config",
                json={"key": "rate_limit_director", "value": value},
            )
            assert resp.status_code == 422, f"value={value}"


def test_update_config_unknown_key_rejected(config_client: TestClient) -> None:
    with patch("app.api.v1.internal.update_tenant_config", new=AsyncMock()):
        resp = config_client.put(
            "/api/v1/internal/config",
            json={"key": "memory_turnz", "value": "5"},
        )
    assert resp.status_code == 422


def test_update_suggestions_enabled_string_bool(config_client: TestClient) -> None:
    """Only 'true' / 'false' strings (case-insensitive) accepted."""
    with patch("app.api.v1.internal.update_tenant_config",
               new=AsyncMock()) as mock_update:
        ok = config_client.put(
            "/api/v1/internal/config",
            json={"key": "suggestions_enabled", "value": "False"},
        )
        bad = config_client.put(
            "/api/v1/internal/config",
            json={"key": "suggestions_enabled", "value": "yes"},
        )
    assert ok.status_code == 200
    assert bad.status_code == 422
    assert mock_update.await_count == 1


# ---------------------------------------------------------------------------
# /suggestions toggle
# ---------------------------------------------------------------------------

def test_suggestions_disabled_returns_role_fallback(config_client: TestClient) -> None:
    """When suggestions_enabled=False, the endpoint must not hit Claude
    and must return the role-specific fallback list."""
    cfg = TenantConfig(suggestions_enabled=False)
    claude_mock = AsyncMock()

    with patch("app.api.v1.internal.get_tenant_config",
               new=AsyncMock(return_value=cfg)), \
         patch("app.api.v1.internal.get_client") as mock_get_client:
        mock_get_client.return_value.messages.create = claude_mock
        resp = config_client.get("/api/v1/internal/suggestions")

    assert resp.status_code == 200
    suggestions = resp.json()["suggestions"]
    assert len(suggestions) == 3
    # Fixture role is "direccion" — must get the direccion fallback list.
    assert "vs plan" in suggestions[0] or "mes" in suggestions[0]
    claude_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Budget gate on /chat
# ---------------------------------------------------------------------------

def test_chat_budget_exceeded_returns_429(config_client: TestClient) -> None:
    """When tenant has spent more than its budget, /chat returns 429 with
    a structured BUDGET_EXCEEDED detail BEFORE invoking the orchestrator."""
    cfg = TenantConfig(monthly_budget_usd=1.0)
    orchestrator_mock = AsyncMock()

    with patch("app.api.v1.internal.get_tenant_config",
               new=AsyncMock(return_value=cfg)), \
         patch("app.api.v1.internal.get_monthly_spend_usd",
               new=AsyncMock(return_value=1.5)), \
         patch("app.api.v1.internal.run_conversation",
               new=orchestrator_mock):
        resp = config_client.post(
            "/api/v1/internal/chat",
            json={"message": "hola"},
        )

    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["scope"] == "budget"
    assert detail["error"] == "BUDGET_EXCEEDED"
    assert detail["spent_usd"] == 1.5
    assert detail["budget_usd"] == 1.0
    orchestrator_mock.assert_not_called()


def test_chat_zero_budget_means_unlimited(config_client: TestClient) -> None:
    """monthly_budget_usd=0 must NOT call get_monthly_spend_usd and must
    NOT block the request even if the tenant has spent something."""
    cfg = TenantConfig(monthly_budget_usd=0.0)
    spend_mock = AsyncMock(return_value=999.0)

    with patch("app.api.v1.internal.get_tenant_config",
               new=AsyncMock(return_value=cfg)), \
         patch("app.api.v1.internal.get_monthly_spend_usd", new=spend_mock), \
         patch("app.api.v1.internal.limiter") as limiter_mock, \
         patch("app.api.v1.internal._resolve_conversation",
               new=AsyncMock(return_value="conv-1")), \
         patch("app.api.v1.internal.load_recent_messages",
               new=AsyncMock(return_value=[])), \
         patch("app.api.v1.internal.run_conversation",
               new=AsyncMock(side_effect=RuntimeError("stop-here"))):
        # We don't need /chat to fully succeed; we only need to assert that
        # spend lookup was skipped and the limiter was reached.
        resp = config_client.post(
            "/api/v1/internal/chat",
            json={"message": "hola"},
        )

    spend_mock.assert_not_called()
    # 503 because run_conversation raised RuntimeError after we got past
    # the budget gate — proves the gate did not short-circuit.
    assert resp.status_code == 503
    limiter_mock.check_and_record_request.assert_called_once()


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_config_cache_invalidated_on_update() -> None:
    """update_tenant_config must drop the cached entry so the next
    get_tenant_config returns fresh data."""
    from app.db import tenant_config as tc

    tc._cache[42] = (1.0, TenantConfig(memory_turns=10))
    assert 42 in tc._cache

    with patch("app.db.tenant_config.execute_query",
               new=AsyncMock(return_value=[])):
        await tc.update_tenant_config(
            tenant_id=42, key="memory_turns", value="5", updated_by=1,
        )

    assert 42 not in tc._cache
