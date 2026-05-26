"""JWT encode/decode + auth dependency tests."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.auth.jwt_handler import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
)
from app.config import settings


def test_create_and_decode_token_roundtrip() -> None:
    token = create_access_token(user_id="u1", tenant_id=7, role="direccion")
    claims = decode_access_token(token)
    assert claims["sub"] == "u1"
    assert claims["tenant_id"] == 7
    assert claims["role"] == "direccion"
    assert claims["exp"] > claims["iat"]


def test_decode_rejects_wrong_signature() -> None:
    # Sign with a different secret -> InvalidTokenError
    bad = jwt.encode(
        {"sub": "u", "tenant_id": 7, "role": "direccion", "exp": int(time.time()) + 60},
        "different-secret",
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(bad)


def test_decode_rejects_expired_token() -> None:
    token = create_access_token(
        user_id="u", tenant_id=7, role="direccion", expires_minutes=-1
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_rejects_missing_tenant_id_claim() -> None:
    bad = jwt.encode(
        {"sub": "u", "role": "direccion", "exp": int(time.time()) + 60},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(bad)


# ---------------------------------------------------------------------------
# Endpoint-level: /api/v1/chat with Bearer
# ---------------------------------------------------------------------------

from app.llm.orchestrator import ConversationResult


def _fake_runner(result: ConversationResult):
    async def fake_run(**kwargs):  # noqa: ANN001, ARG001
        return result

    return fake_run


def test_chat_endpoint_accepts_valid_bearer_token(
    client: TestClient, monkeypatch
) -> None:
    token = create_access_token(user_id="alice", tenant_id=7, role="direccion")
    monkeypatch.setattr(
        "app.api.v1.chat.run_conversation",
        _fake_runner(
            ConversationResult(
                request_id="r1", response_text="ok", iterations=1, stop_reason="end_turn"
            )
        ),
    )
    resp = client.post(
        "/api/v1/chat",
        json={"message": "hola"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


def test_chat_endpoint_rejects_invalid_bearer(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/chat",
        json={"message": "hola"},
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert resp.status_code == 401
    assert "invalid_token" in resp.json()["detail"]


def test_chat_endpoint_rejects_expired_bearer(client: TestClient) -> None:
    expired = create_access_token(
        user_id="alice", tenant_id=7, role="direccion", expires_minutes=-1
    )
    resp = client.post(
        "/api/v1/chat",
        json={"message": "hola"},
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert resp.status_code == 401
