"""Tests for GET /api/v1/internal/suggestions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.v1.internal import _FALLBACK_SUGGESTIONS, _SUGGESTIONS_CACHE
from app.auth.service_auth import ServiceAuthContext, get_service_auth_context
from app.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_svc(tenant_id: int = 7, role: str = "tienda") -> ServiceAuthContext:
    return ServiceAuthContext(
        tenant_id=tenant_id,
        user_id=1,
        role=role,
        conversation_id=None,
        request_id="test-request-id",
    )


@pytest.fixture()
def suggestions_client():
    """TestClient with service auth overridden and cache cleared before each test."""
    svc = _make_svc()

    async def _override() -> ServiceAuthContext:
        return svc

    app.dependency_overrides[get_service_auth_context] = _override
    _SUGGESTIONS_CACHE.clear()
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_service_auth_context, None)
    _SUGGESTIONS_CACHE.clear()


# ---------------------------------------------------------------------------
# Helpers — mock Anthropic response
# ---------------------------------------------------------------------------

def _mock_claude_response(text: str) -> MagicMock:
    """Build a minimal AsyncMock that mimics client.messages.create() return value."""
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_suggestions_returns_3_items(suggestions_client: TestClient) -> None:
    claude_text = "¿Qué alertas hay activas?\n¿Cómo van las ventas?\n¿Qué productos reponer?"
    mock_create = AsyncMock(return_value=_mock_claude_response(claude_text))

    with patch("app.api.v1.internal.get_client") as mock_get_client:
        mock_get_client.return_value.messages.create = mock_create
        resp = suggestions_client.get("/api/v1/internal/suggestions")

    assert resp.status_code == 200
    body = resp.json()
    assert "suggestions" in body
    assert len(body["suggestions"]) == 3
    assert body["suggestions"][0] == "¿Qué alertas hay activas?"


def test_suggestions_cache_hit(suggestions_client: TestClient) -> None:
    """Second call within TTL must not invoke Claude again."""
    claude_text = "Pregunta A\nPregunta B\nPregunta C"
    mock_create = AsyncMock(return_value=_mock_claude_response(claude_text))

    with patch("app.api.v1.internal.get_client") as mock_get_client:
        mock_get_client.return_value.messages.create = mock_create
        suggestions_client.get("/api/v1/internal/suggestions")
        suggestions_client.get("/api/v1/internal/suggestions")

    assert mock_create.call_count == 1, "Claude should only be called once (cache hit on second request)"


def test_suggestions_fallback_on_error(suggestions_client: TestClient) -> None:
    """When get_client() raises, the endpoint returns the static fallback."""
    with patch("app.api.v1.internal.get_client", side_effect=RuntimeError("API key not configured")):
        resp = suggestions_client.get("/api/v1/internal/suggestions")

    assert resp.status_code == 200
    body = resp.json()
    assert body["suggestions"] == list(_FALLBACK_SUGGESTIONS)


def test_suggestions_fallback_when_claude_returns_empty(suggestions_client: TestClient) -> None:
    """Claude returns empty content → pad with fallbacks."""
    mock_create = AsyncMock(return_value=_mock_claude_response(""))

    with patch("app.api.v1.internal.get_client") as mock_get_client:
        mock_get_client.return_value.messages.create = mock_create
        resp = suggestions_client.get("/api/v1/internal/suggestions")

    assert resp.status_code == 200
    assert len(resp.json()["suggestions"]) == 3


def test_suggestions_pads_to_3_when_claude_returns_fewer(suggestions_client: TestClient) -> None:
    """Claude returns only 1 line → remaining 2 slots filled with fallbacks."""
    mock_create = AsyncMock(return_value=_mock_claude_response("Solo una pregunta"))

    with patch("app.api.v1.internal.get_client") as mock_get_client:
        mock_get_client.return_value.messages.create = mock_create
        resp = suggestions_client.get("/api/v1/internal/suggestions")

    suggestions = resp.json()["suggestions"]
    assert len(suggestions) == 3
    assert suggestions[0] == "Solo una pregunta"
    # Padded with fallbacks
    assert suggestions[1] == _FALLBACK_SUGGESTIONS[1]
    assert suggestions[2] == _FALLBACK_SUGGESTIONS[2]
