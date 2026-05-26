"""POST /api/v1/chat — integration tests with the orchestrator mocked."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.llm.orchestrator import ConversationResult, ToolInvocation


def _make_fake_runner(result: ConversationResult):
    async def fake_run(**kwargs):  # noqa: ANN001, ARG001
        return result

    return fake_run


def test_chat_endpoint_returns_envelope(
    client: TestClient, monkeypatch
) -> None:
    fake = ConversationResult(
        request_id="req-1",
        response_text="Tenés 3 alertas activas.",
        tools_invoked=[
            ToolInvocation(
                name="get_active_alerts",
                input={"limit": 3},
                duration_ms=12,
                is_error=False,
            )
        ],
        iterations=2,
        stop_reason="end_turn",
        tokens_input=100,
        tokens_output=80,
        duration_ms=350,
    )
    monkeypatch.setattr("app.api.v1.chat.run_conversation", _make_fake_runner(fake))

    resp = client.post("/api/v1/chat", json={"message": "¿qué alertas tengo?"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["request_id"] == "req-1"
    assert body["response"] == "Tenés 3 alertas activas."
    assert body["tools_used"] == [
        {"name": "get_active_alerts", "duration_ms": 12, "is_error": False}
    ]
    assert body["iterations"] == 2
    assert body["stop_reason"] == "end_turn"
    assert body["tokens_input"] == 100
    assert body["tokens_output"] == 80
    assert body["duration_ms"] == 350
    # conversation_id is generated when not provided
    assert isinstance(body["conversation_id"], str) and len(body["conversation_id"]) >= 8


def test_chat_endpoint_echoes_conversation_id_when_provided(
    client: TestClient, monkeypatch
) -> None:
    fake = ConversationResult(
        request_id="req-2",
        response_text="ok",
        tools_invoked=[],
        iterations=1,
        stop_reason="end_turn",
    )
    monkeypatch.setattr("app.api.v1.chat.run_conversation", _make_fake_runner(fake))

    resp = client.post(
        "/api/v1/chat",
        json={"message": "hola", "conversation_id": "conv-abc-123"},
    )
    assert resp.status_code == 200
    assert resp.json()["conversation_id"] == "conv-abc-123"


def test_chat_endpoint_503_when_anthropic_key_missing(
    client: TestClient, monkeypatch
) -> None:
    async def boom(**kwargs):  # noqa: ANN001, ARG001
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    monkeypatch.setattr("app.api.v1.chat.run_conversation", boom)

    resp = client.post("/api/v1/chat", json={"message": "test"})
    assert resp.status_code == 503
    assert "ANTHROPIC_API_KEY" in resp.json()["detail"]


def test_chat_endpoint_rejects_empty_message(client: TestClient) -> None:
    resp = client.post("/api/v1/chat", json={"message": ""})
    assert resp.status_code == 422


def test_chat_endpoint_uses_auth_default_tenant(
    client: TestClient, monkeypatch
) -> None:
    """Without auth headers, the mock dependency defaults to tenant=7."""
    captured = {}

    async def capturing_runner(**kwargs):
        captured["tenant_id"] = kwargs["auth"].tenant_id
        captured["user_id"] = kwargs["auth"].user_id
        return ConversationResult(
            request_id="req-3",
            response_text="ok",
            iterations=1,
            stop_reason="end_turn",
        )

    monkeypatch.setattr("app.api.v1.chat.run_conversation", capturing_runner)
    resp = client.post("/api/v1/chat", json={"message": "test"})
    assert resp.status_code == 200
    assert captured == {"tenant_id": 7, "user_id": "dev-user"}


def test_chat_endpoint_respects_mock_auth_headers(
    client: TestClient, monkeypatch
) -> None:
    captured = {}

    async def capturing_runner(**kwargs):
        captured["tenant_id"] = kwargs["auth"].tenant_id
        return ConversationResult(
            request_id="req-4",
            response_text="ok",
            iterations=1,
            stop_reason="end_turn",
        )

    monkeypatch.setattr("app.api.v1.chat.run_conversation", capturing_runner)
    resp = client.post(
        "/api/v1/chat",
        json={"message": "test"},
        headers={"X-Mock-Tenant": "42", "X-Mock-User": "boss"},
    )
    assert resp.status_code == 200
    assert captured["tenant_id"] == 42
