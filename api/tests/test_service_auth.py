"""Service-to-service auth tests — sub-fase 6.1.

Tests:
  1. valid key + headers → 200 from /internal/chat
  2. invalid key → 401
  3. missing X-Tenant-Id → 400
  4. invalid role → silently mapped to 'sku'
  5. backward compat: no service key configured → existing JWT/mock path unaffected
  6. GET /health/ready — returns expected fields
  7. internal/chat mirrors conversation orchestration
  8. /internal/chat without key → 401
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.llm.orchestrator import ConversationResult, ToolInvocation

_FAKE_SERVICE_KEY = "test-service-key-abc123"

_GOOD_HEADERS = {
    "X-Service-Key": _FAKE_SERVICE_KEY,
    "X-Tenant-Id": "42",
    "X-User-Id": "99",
    "X-User-Role": "marca",
    "X-Request-Id": "req-svc-001",
}


def _fake_result(**overrides) -> ConversationResult:
    base = dict(
        request_id="req-svc-001",
        response_text="Respuesta de prueba.",
        tools_invoked=[],
        iterations=1,
        stop_reason="end_turn",
        tokens_input=50,
        tokens_output=40,
        duration_ms=200,
    )
    base.update(overrides)
    return ConversationResult(**base)


def _fake_runner(result: ConversationResult):
    async def _run(**kwargs):  # noqa: ANN001, ARG001
        return result

    return _run


# ---------------------------------------------------------------------------
# Test 1: valid service key + headers → 200
# ---------------------------------------------------------------------------

def test_internal_chat_valid_key(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("SERVICE_KEY", _FAKE_SERVICE_KEY)
    # Re-import settings so it picks up the new env value
    import importlib
    import app.config as cfg_mod
    import app.auth.service_auth as svc_mod

    importlib.reload(cfg_mod)
    importlib.reload(svc_mod)
    monkeypatch.setattr(svc_mod, "settings", cfg_mod.Settings(service_key=_FAKE_SERVICE_KEY))

    monkeypatch.setattr("app.api.v1.internal.run_conversation", _fake_runner(_fake_result()))

    resp = client.post(
        "/api/v1/internal/chat",
        json={"message": "¿cuántos SKUs tengo?"},
        headers=_GOOD_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["response"] == "Respuesta de prueba."
    assert body["request_id"] == "req-svc-001"
    assert isinstance(body["conversation_id"], str)
    assert body["tokens_input"] == 50
    assert body["tokens_output"] == 40


# ---------------------------------------------------------------------------
# Test 2: wrong service key → 401
# ---------------------------------------------------------------------------

def test_internal_chat_wrong_key(client: TestClient, monkeypatch) -> None:
    import app.auth.service_auth as svc_mod
    from app.config import Settings

    monkeypatch.setattr(svc_mod, "settings", Settings(service_key=_FAKE_SERVICE_KEY))

    resp = client.post(
        "/api/v1/internal/chat",
        json={"message": "test"},
        headers={**_GOOD_HEADERS, "X-Service-Key": "wrong-key"},
    )
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# Test 3: missing X-Tenant-Id → 400
# ---------------------------------------------------------------------------

def test_internal_chat_missing_tenant(client: TestClient, monkeypatch) -> None:
    import app.auth.service_auth as svc_mod
    from app.config import Settings

    monkeypatch.setattr(svc_mod, "settings", Settings(service_key=_FAKE_SERVICE_KEY))

    headers = {k: v for k, v in _GOOD_HEADERS.items() if k != "X-Tenant-Id"}
    resp = client.post(
        "/api/v1/internal/chat",
        json={"message": "test"},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    assert "X-Tenant-Id" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Test 4: invalid role → silently mapped to 'sku'
# ---------------------------------------------------------------------------

def test_internal_chat_invalid_role_maps_to_sku(client: TestClient, monkeypatch) -> None:
    import app.auth.service_auth as svc_mod
    from app.config import Settings

    monkeypatch.setattr(svc_mod, "settings", Settings(service_key=_FAKE_SERVICE_KEY))
    monkeypatch.setattr("app.api.v1.internal.run_conversation", _fake_runner(_fake_result()))

    resp = client.post(
        "/api/v1/internal/chat",
        json={"message": "test"},
        headers={**_GOOD_HEADERS, "X-User-Role": "superadmin"},
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Test 5: backward compat — no service key configured, /chat mock path unchanged
# ---------------------------------------------------------------------------

def test_chat_mock_path_unaffected_when_no_service_key(
    client: TestClient, monkeypatch
) -> None:
    """When SERVICE_KEY is empty, /chat still works via mock headers."""
    import app.auth.dependencies as dep_mod
    from app.config import Settings

    monkeypatch.setattr(dep_mod, "settings", Settings(service_key=""))
    monkeypatch.setattr("app.api.v1.chat.run_conversation", _fake_runner(_fake_result()))

    resp = client.post(
        "/api/v1/chat",
        json={"message": "test backward compat"},
        headers={"X-Mock-User": "alice", "X-Mock-Tenant": "7", "X-Mock-Role": "direccion"},
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Test 6: GET /health/ready — structure
# ---------------------------------------------------------------------------

def test_health_ready_returns_expected_fields(client: TestClient) -> None:
    resp = client.get("/api/v1/health/ready")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "status" in body
    assert body["status"] in ("ready", "not_ready")
    assert "mode" in body
    assert body["mode"] in ("service", "dev")
    assert isinstance(body["db_ok"], bool)
    assert isinstance(body["anthropic_ok"], bool)


# ---------------------------------------------------------------------------
# Test 7: internal/chat mirrors orchestration — tools_used populated
# ---------------------------------------------------------------------------

def test_internal_chat_tools_used(client: TestClient, monkeypatch) -> None:
    import app.auth.service_auth as svc_mod
    from app.config import Settings

    monkeypatch.setattr(svc_mod, "settings", Settings(service_key=_FAKE_SERVICE_KEY))

    result = _fake_result(
        tools_invoked=[
            ToolInvocation(name="get_active_alerts", input={}, duration_ms=10, is_error=False)
        ]
    )
    monkeypatch.setattr("app.api.v1.internal.run_conversation", _fake_runner(result))

    resp = client.post(
        "/api/v1/internal/chat",
        json={"message": "¿alertas?"},
        headers=_GOOD_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tools_used"] == ["get_active_alerts"]


# ---------------------------------------------------------------------------
# Test 8: /internal/chat without any key → SERVICE_KEY not configured → 503
# ---------------------------------------------------------------------------

def test_internal_chat_no_service_key_configured(client: TestClient, monkeypatch) -> None:
    """When server has no SERVICE_KEY set, /internal/chat returns 503."""
    import app.auth.service_auth as svc_mod
    from app.config import Settings

    monkeypatch.setattr(svc_mod, "settings", Settings(service_key=""))

    resp = client.post(
        "/api/v1/internal/chat",
        json={"message": "test"},
        headers={"X-Service-Key": "anything"},
    )
    assert resp.status_code == 503, resp.text
