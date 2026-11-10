"""/api/v1/internal/chat con X-Balaxys-Mcp-Token: token -> sesion ERP -> loop -> cards.

Mismo patron que tests/test_service_auth.py: endpoint real, con run_conversation
y la apertura de la sesion MCP reemplazados (sin Anthropic ni ERP).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.llm.orchestrator import MAX_ITERATIONS, ConversationResult
from app.mcp_client.balaxys import ErpCard

_KEY = "test-service-key-mcp"
_HEADERS = {
    "X-Service-Key": _KEY,
    "X-Tenant-Id": "42",
    "X-User-Id": "99",
    "X-User-Role": "direccion",
    "X-Request-Id": "req-mcp-001",
}
_ERP_SENTINEL = object()


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch):
    import app.auth.service_auth as svc_mod
    from app.config import Settings

    monkeypatch.setattr(svc_mod, "settings", Settings(service_key=_KEY))
    seen: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_open(token):  # type: ignore[no-untyped-def]
        seen["token"] = token
        yield _ERP_SENTINEL if token else None

    card = ErpCard(
        tool="preparar_confirmacion_factura",
        title="Confirmar factura A-12",
        data={"confirmar_con": {"herramienta": "confirmar_factura", "argumentos": {"id_factura": 12}}},
    )

    async def fake_run(**kwargs):  # type: ignore[no-untyped-def]
        seen["erp"] = kwargs.get("erp")
        seen["max_iterations"] = kwargs.get("max_iterations")
        return ConversationResult(
            request_id="req-mcp-001",
            response_text="Prepare la confirmacion.",
            stop_reason="end_turn",
            cards=[card] if kwargs.get("erp") is not None else [],
        )

    monkeypatch.setattr("app.api.v1.internal.open_balaxys_mcp", fake_open)
    monkeypatch.setattr("app.api.v1.internal.run_conversation", fake_run)
    return seen


def test_con_token_abre_la_sesion_erp_y_devuelve_cards(client: TestClient, wired: dict[str, Any]) -> None:
    resp = client.post(
        "/api/v1/internal/chat",
        json={"message": "confirma la factura 12"},
        headers={**_HEADERS, "X-Balaxys-Mcp-Token": "bmcp.abc.def"},
    )
    assert resp.status_code == 200, resp.text
    assert wired["token"] == "bmcp.abc.def"
    assert wired["erp"] is _ERP_SENTINEL
    assert wired["max_iterations"] == max(MAX_ITERATIONS, settings.balaxys_mcp_max_tool_calls)
    cards = resp.json()["cards"]
    assert cards == [
        {
            "tool": "preparar_confirmacion_factura",
            "title": "Confirmar factura A-12",
            "data": {"confirmar_con": {"herramienta": "confirmar_factura", "argumentos": {"id_factura": 12}}},
        }
    ]


def test_sin_token_el_chat_sigue_como_antes(client: TestClient, wired: dict[str, Any]) -> None:
    resp = client.post("/api/v1/internal/chat", json={"message": "hola"}, headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    assert wired["token"] is None
    assert wired["erp"] is None
    assert wired["max_iterations"] == MAX_ITERATIONS
    assert resp.json()["cards"] == []


def test_el_token_no_aparece_en_el_repr_del_contexto() -> None:
    from app.auth.service_auth import ServiceAuthContext

    ctx = ServiceAuthContext(
        tenant_id=1, user_id="1", role="direccion", conversation_id=None, request_id="r", mcp_token="bmcp.secret"
    )
    assert "bmcp.secret" not in repr(ctx)
