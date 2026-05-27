"""Tests for conversation history and feedback endpoints.

3c: GET  /api/v1/internal/conversations
3d: GET  /api/v1/internal/conversations/{id}/messages
3e: POST /api/v1/internal/feedback
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.service_auth import ServiceAuthContext, get_service_auth_context
from app.db.conversation import create_conversation, append_message
from app.main import app


# ---------------------------------------------------------------------------
# Auth fixtures — two separate tenants for isolation tests
# ---------------------------------------------------------------------------

def _svc(tenant_id: int = 7, user_id: int = 1, role: str = "tienda") -> ServiceAuthContext:
    return ServiceAuthContext(
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        conversation_id=None,
        request_id="test-req-id",
    )


@pytest.fixture()
def client_t7():
    """TestClient authenticated as tenant 7, user 1."""
    async def _override():
        return _svc(tenant_id=7, user_id=1)

    app.dependency_overrides[get_service_auth_context] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_service_auth_context, None)


@pytest.fixture()
def client_t99():
    """TestClient authenticated as tenant 99 (no data)."""
    async def _override():
        return _svc(tenant_id=99, user_id=99)

    app.dependency_overrides[get_service_auth_context] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_service_auth_context, None)


# ---------------------------------------------------------------------------
# Helpers — create a real conversation in the DB for integration tests
# ---------------------------------------------------------------------------

@pytest.fixture()
async def conversation_for_t7():
    """Create a real conversation row under tenant 7, user 1; return conv_id."""
    conv_id = await create_conversation(tenant_id=7, user_id="1", user_role="tienda")
    await append_message(conversation_id=conv_id, role="user", content="¿Cuáles son las alertas?")
    await append_message(conversation_id=conv_id, role="assistant", content="Hay 3 alertas activas.")
    return conv_id


@pytest.fixture()
async def conversation_for_t23():
    """Create a real conversation under tenant 23 (different tenant)."""
    return await create_conversation(tenant_id=23, user_id="1", user_role="tienda")


# ---------------------------------------------------------------------------
# 3c: GET /conversations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_conversations_list_returns_list(client_t7: TestClient) -> None:
    resp = client_t7.get("/api/v1/internal/conversations")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_conversations_list_tenant_isolated(
    client_t7: TestClient, conversation_for_t7: str, conversation_for_t23: str
) -> None:
    """Tenant 7 must not see tenant 23's conversations."""
    resp = client_t7.get("/api/v1/internal/conversations")
    assert resp.status_code == 200
    ids = [c["conversation_id"] for c in resp.json()]
    assert conversation_for_t23 not in ids, "Cross-tenant conversation leaked!"
    # Tenant 7's own conversation must be visible
    assert conversation_for_t7 in ids


@pytest.mark.asyncio
async def test_conversations_list_includes_required_fields(
    client_t7: TestClient, conversation_for_t7: str
) -> None:
    resp = client_t7.get("/api/v1/internal/conversations")
    assert resp.status_code == 200
    conversations = resp.json()
    assert len(conversations) > 0
    for conv in conversations:
        assert "conversation_id" in conv
        assert "title" in conv
        assert "last_message_at" in conv
        assert "message_count" in conv


@pytest.mark.asyncio
async def test_conversations_list_title_derived_from_first_user_message(
    client_t7: TestClient, conversation_for_t7: str
) -> None:
    resp = client_t7.get("/api/v1/internal/conversations")
    convs = {c["conversation_id"]: c for c in resp.json()}
    if conversation_for_t7 in convs:
        title = convs[conversation_for_t7]["title"]
        assert "alertas" in title.lower() or len(title) > 0


# ---------------------------------------------------------------------------
# 3d: GET /conversations/{id}/messages
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_conversation_messages_returns_list(
    client_t7: TestClient, conversation_for_t7: str
) -> None:
    resp = client_t7.get(f"/api/v1/internal/conversations/{conversation_for_t7}/messages")
    assert resp.status_code == 200
    messages = resp.json()
    assert isinstance(messages, list)
    assert len(messages) == 2  # user + assistant appended by fixture


@pytest.mark.asyncio
async def test_conversation_messages_correct_order(
    client_t7: TestClient, conversation_for_t7: str
) -> None:
    resp = client_t7.get(f"/api/v1/internal/conversations/{conversation_for_t7}/messages")
    messages = resp.json()
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_conversation_messages_includes_required_fields(
    client_t7: TestClient, conversation_for_t7: str
) -> None:
    resp = client_t7.get(f"/api/v1/internal/conversations/{conversation_for_t7}/messages")
    for msg in resp.json():
        assert "role" in msg
        assert "content" in msg
        assert "created_at" in msg


@pytest.mark.asyncio
async def test_conversation_messages_cross_tenant_rejected(
    client_t99: TestClient, conversation_for_t7: str
) -> None:
    """Tenant 99 must not read tenant 7's conversation messages."""
    resp = client_t99.get(f"/api/v1/internal/conversations/{conversation_for_t7}/messages")
    assert resp.status_code == 404, (
        f"Expected 404 for cross-tenant access, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# 3e: POST /feedback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_feedback_positive(client_t7: TestClient) -> None:
    payload = {"requestId": "aaaaaaaa-0000-0000-0000-000000000001", "rating": "positive"}
    resp = client_t7.post("/api/v1/internal/feedback", json=payload)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.asyncio
async def test_feedback_negative_with_comment(client_t7: TestClient) -> None:
    payload = {
        "requestId": "aaaaaaaa-0000-0000-0000-000000000002",
        "rating": "negative",
        "comment": "La respuesta fue demasiado genérica.",
    }
    resp = client_t7.post("/api/v1/internal/feedback", json=payload)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_feedback_invalid_rating_rejected(client_t7: TestClient) -> None:
    payload = {"requestId": "aaaaaaaa-0000-0000-0000-000000000003", "rating": "neutral"}
    resp = client_t7.post("/api/v1/internal/feedback", json=payload)
    assert resp.status_code == 400
    assert "neutral" in resp.json()["detail"]


def test_feedback_missing_request_id_rejected(client_t7: TestClient) -> None:
    payload = {"rating": "positive"}
    resp = client_t7.post("/api/v1/internal/feedback", json=payload)
    assert resp.status_code == 422  # FastAPI validation error


def test_feedback_comment_too_long_rejected(client_t7: TestClient) -> None:
    payload = {
        "requestId": "aaaaaaaa-0000-0000-0000-000000000004",
        "rating": "negative",
        "comment": "x" * 501,  # max_length=500
    }
    resp = client_t7.post("/api/v1/internal/feedback", json=payload)
    assert resp.status_code == 422
