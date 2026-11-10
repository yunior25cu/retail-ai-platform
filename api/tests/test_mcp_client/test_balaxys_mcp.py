"""Cliente MCP de Balaxys ERP contra un servidor MCP en proceso (sin red ni ERP real).

El servidor de prueba imita al de Balaxys: Streamable HTTP sin estado, tools
con anotaciones (lectura, ``preparar_*`` con ``confirmar_con`` y una
destructiva), ``structuredContent`` e ``instructions``.

El servidor vive dentro de cada test (``erp_server()``) y no en un fixture con
``yield``: pytest-asyncio corre setup y teardown de un fixture en tareas
distintas, y anyio no permite cerrar el lifespan del servidor en otra tarea.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from app.config import settings
from app.mcp_client import open_balaxys_mcp
from app.mcp_client.balaxys import MAX_CARDS, ErpCard, select_cards

TOKEN = "bmcp.test-token"
URL = "http://localhost:8000/mcp"
INSTRUCTIONS = "Eres el asistente de Balaxys ERP. Llama primero a obtener_contexto_empresa."


def _build_server() -> FastMCP:
    mcp = FastMCP("balaxys-erp-test", instructions=INSTRUCTIONS, stateless_http=True, json_response=True)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, title="Deuda vencida"), structured_output=True)
    def clientes_con_deuda_vencida() -> dict[str, Any]:
        """Clientes con facturas vencidas."""
        return {
            "titulo": "Clientes con deuda vencida",
            "total": 186400,
            "clientes": [{"id_cliente": 7, "nombre": "Cafe Pocitos"}],
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False), structured_output=True)
    def preparar_confirmacion_factura(id_factura: int) -> dict[str, Any]:
        """Prepara la confirmacion de una factura."""
        return {
            "titulo": f"Confirmar factura {id_factura}",
            "token_confirmacion": "bmcpc.secreto",
            "confirmar_con": {
                "herramienta": "confirmar_factura",
                "argumentos": {"id_factura": id_factura, "token_confirmacion": "bmcpc.secreto"},
            },
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def confirmar_factura(id_factura: int, token_confirmacion: str) -> str:
        """Confirma una factura."""
        return "confirmada"

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def falla_negocio() -> str:
        """Siempre falla con un error de negocio."""
        raise ValueError("El documento cambio. Prepara la confirmacion de nuevo.")

    return mcp


class _FlakyTransport(httpx.AsyncBaseTransport):
    """Delega en la app ASGI hasta que ``fail`` se activa; entonces responde 500."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self.inner = inner
        self.fail = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            return httpx.Response(500, text="boom")
        return await self.inner.handle_async_request(request)


@dataclass
class _Server:
    transport: _FlakyTransport
    seen_auth: list[str | None] = field(default_factory=list)

    def factory(self, headers: dict[str, str], timeout: httpx.Timeout) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport, headers=headers, timeout=timeout)


@pytest.fixture(autouse=True)
def _mcp_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "balaxys_mcp_url", URL)
    monkeypatch.setattr(settings, "balaxys_mcp_enabled", True)
    monkeypatch.setattr(settings, "balaxys_mcp_max_tool_calls", 8)
    monkeypatch.setattr(settings, "balaxys_mcp_timeout_seconds", 10.0)


@asynccontextmanager
async def erp_server() -> AsyncIterator[_Server]:
    mcp = _build_server()
    app = mcp.streamable_http_app()
    server: _Server

    async def recorder(scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] == "http":
            raw = dict(scope.get("headers") or []).get(b"authorization")
            server.seen_auth.append(raw.decode() if raw else None)
        await app(scope, receive, send)

    server = _Server(transport=_FlakyTransport(httpx.ASGITransport(app=recorder)))
    async with mcp.session_manager.run():
        yield server


async def test_lista_solo_tools_no_destructivas_y_envia_el_token():
    async with erp_server() as srv, open_balaxys_mcp(TOKEN, http_client_factory=srv.factory) as erp:
        assert erp is not None
        names = [t.name for t in erp.tools]
        assert names == sorted(names), "orden estable para la cache de prompt"
        assert "clientes_con_deuda_vencida" in names
        assert "preparar_confirmacion_factura" in names
        assert "confirmar_factura" not in names, "las destructivas nunca llegan al modelo"
        assert erp.instructions == INSTRUCTIONS
        tool_defs = erp.anthropic_tools()
        assert all(set(d) == {"name", "description", "input_schema"} for d in tool_defs)
        assert all(d["input_schema"]["type"] == "object" for d in tool_defs)
    assert srv.seen_auth and all(a == f"Bearer {TOKEN}" for a in srv.seen_auth)


async def test_lectura_devuelve_payload_y_tarjeta_con_structured_content_intacto():
    async with erp_server() as srv, open_balaxys_mcp(TOKEN, http_client_factory=srv.factory) as erp:
        r = await erp.call("clientes_con_deuda_vencida", {})
    assert not r.is_error
    assert r.payload["total"] == 186400
    assert r.card is not None
    assert r.card.title == "Clientes con deuda vencida"
    assert r.card.data["clientes"][0]["nombre"] == "Cafe Pocitos"


async def test_preparar_oculta_token_y_accion_al_modelo_pero_no_a_la_tarjeta():
    async with erp_server() as srv, open_balaxys_mcp(TOKEN, http_client_factory=srv.factory) as erp:
        r = await erp.call("preparar_confirmacion_factura", {"id_factura": 12})
    assert not r.is_error
    assert "token_confirmacion" not in r.payload
    assert "confirmar_con" not in r.payload
    assert "requiere_confirmacion" in r.payload
    assert r.card is not None and r.card.has_action, "toda preparar_* lleva tarjeta con Confirmar"
    assert r.card.data["confirmar_con"]["argumentos"]["token_confirmacion"] == "bmcpc.secreto"


async def test_error_de_negocio_vuelve_como_tool_error_sin_tarjeta():
    async with erp_server() as srv, open_balaxys_mcp(TOKEN, http_client_factory=srv.factory) as erp:
        r = await erp.call("falla_negocio", {})
    assert r.is_error
    assert "cambio" in r.payload["mensaje"]
    assert r.card is None


async def test_tool_destructiva_o_desconocida_no_se_ejecuta():
    async with erp_server() as srv, open_balaxys_mcp(TOKEN, http_client_factory=srv.factory) as erp:
        r = await erp.call("confirmar_factura", {"id_factura": 1, "token_confirmacion": "x"})
    assert r.is_error and r.payload["error"] == "herramienta_no_disponible"


async def test_tope_de_llamadas_por_mensaje(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "balaxys_mcp_max_tool_calls", 2)
    async with erp_server() as srv, open_balaxys_mcp(TOKEN, http_client_factory=srv.factory) as erp:
        assert not (await erp.call("clientes_con_deuda_vencida", {})).is_error
        assert not (await erp.call("clientes_con_deuda_vencida", {})).is_error
        third = await erp.call("clientes_con_deuda_vencida", {})
    assert third.is_error and third.payload["error"] == "limite_llamadas_erp"


async def test_sin_token_o_sin_url_no_abre_sesion(monkeypatch: pytest.MonkeyPatch):
    async with open_balaxys_mcp(None) as erp:
        assert erp is None
    monkeypatch.setattr(settings, "balaxys_mcp_url", "")
    async with open_balaxys_mcp(TOKEN) as erp:
        assert erp is None


async def test_token_rechazado_entrega_none_y_no_rompe():
    transport = httpx.MockTransport(lambda req: httpx.Response(401, json={"error": "invalid_token"}))

    def factory(headers: dict[str, str], timeout: httpx.Timeout) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport, headers=headers, timeout=timeout)

    async with open_balaxys_mcp(TOKEN, http_client_factory=factory) as erp:
        assert erp is None


async def test_error_del_cuerpo_se_propaga_sin_envolver():
    # pytest.raises envuelve solo al cliente: el servidor de prueba tiene su propio
    # task group, que si envolveria la excepcion (en produccion no existe).
    async with erp_server() as srv:
        with pytest.raises(RuntimeError, match="fallo del orquestador"):
            async with open_balaxys_mcp(TOKEN, http_client_factory=srv.factory) as erp:
                assert erp is not None
                raise RuntimeError("fallo del orquestador")


async def test_caida_del_erp_a_mitad_del_mensaje_no_cancela_al_orquestador():
    """Token vencido o 5xx en medio del loop: la llamada da error y quien llama sigue vivo."""
    async with erp_server() as srv, open_balaxys_mcp(TOKEN, http_client_factory=srv.factory) as erp:
        assert erp is not None
        assert not (await erp.call("clientes_con_deuda_vencida", {})).is_error
        srv.transport.fail = True
        failed = await erp.call("clientes_con_deuda_vencida", {})
        assert failed.is_error and failed.payload["error"] == "erp_no_disponible"
        again = await erp.call("clientes_con_deuda_vencida", {})
        assert again.is_error and again.payload["error"] == "erp_no_disponible", "no reintenta en loop"
        await asyncio.sleep(0)  # seguimos corriendo: no hubo CancelledError en esta tarea


def test_select_cards_prioriza_acciones_y_limita():
    plain = [ErpCard(tool=f"t{i}", title="x", data={"n": i}) for i in range(4)]
    action = ErpCard(tool="preparar", title="y", data={"confirmar_con": {"herramienta": "confirmar_factura"}})
    chosen = select_cards([*plain, action])
    assert len(chosen) == MAX_CARDS
    assert chosen[0] is action
    assert [c.tool for c in chosen[1:]] == ["t0", "t1"]
