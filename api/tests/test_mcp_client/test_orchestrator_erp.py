"""Orquestador con tools ERP de Balaxys (MCP) y un cliente de Claude simulado.

No usa base de datos ni API de Anthropic: solo se llaman tools ERP (sesion
falsa en memoria), que no pasan por el dispatcher local.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from app.auth.dependencies import AuthContext
from app.config import settings
from app.llm.orchestrator import run_conversation
from app.llm.prompts.erp import erp_context_block, erp_prompt_block
from app.mcp_client.balaxys import ErpCard, ErpTool, ErpToolResult
from app.tools import anthropic_tools

AUTH = AuthContext(user_id="17", tenant_id=7, role="direccion")
BASE_PROMPT = "Base system prompt."


def _text(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_use(use_id: str, name: str, args: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=use_id, name=name, input=args)


def _msg(content: list[Any], stop: str, **usage: int) -> SimpleNamespace:
    u = {"input_tokens": 10, "output_tokens": 5, **usage}
    return SimpleNamespace(content=content, stop_reason=stop, usage=SimpleNamespace(**u))


def _client(responses: list[Any]) -> AsyncMock:
    mock = AsyncMock()
    mock.messages = AsyncMock()
    mock.messages.create = AsyncMock(side_effect=responses)
    return mock


@dataclass
class FakeErp:
    """Duck-type de BalaxysMcpSession."""

    results: dict[str, ErpToolResult]
    tool_names: list[str]
    instructions: str | None = "Llama primero a obtener_contexto_empresa."
    context: dict[str, Any] | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    context_requests: int = 0

    async def company_context(self) -> dict[str, Any] | None:
        self.context_requests += 1
        return self.context

    @property
    def tools(self) -> list[ErpTool]:
        return [
            ErpTool(n, n, f"ERP {n}", {"type": "object", "properties": {}}, read_only=True, has_card=False)
            for n in self.tool_names
        ]

    def anthropic_tools(self) -> list[dict[str, Any]]:
        return [t.to_anthropic() for t in self.tools]

    async def call(self, name: str, arguments: dict[str, Any]) -> ErpToolResult:
        self.calls.append((name, arguments))
        return self.results[name]


def _sent_tool_result(client: AsyncMock, call_index: int) -> dict[str, Any]:
    messages = client.messages.create.call_args_list[call_index].kwargs["messages"]
    return messages[-1]["content"][0]


async def test_sin_erp_el_request_es_el_mismo_de_siempre():
    client = _client([_msg([_text("hola")], "end_turn")])
    result = await run_conversation("hola", AUTH, client=client, system_prompt=BASE_PROMPT)
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["system"] == BASE_PROMPT
    assert [t["name"] for t in kwargs["tools"]] == [t["name"] for t in anthropic_tools(role="direccion")]
    assert result.cards == []


async def test_con_erp_agrega_tools_y_bloque_de_prompt_y_rutea_la_llamada_al_erp():
    card = ErpCard(tool="clientes_con_deuda_vencida", title="Deuda vencida", data={"total": 186400})
    erp = FakeErp(
        results={"clientes_con_deuda_vencida": ErpToolResult({"total": 186400}, False, 12, card)},
        tool_names=["clientes_con_deuda_vencida", "obtener_contexto_empresa"],
    )
    client = _client(
        [
            _msg([_tool_use("t1", "clientes_con_deuda_vencida", {"dias": 30})], "tool_use"),
            _msg([_text("Tenes **$ 186.400** vencidos.")], "end_turn"),
        ]
    )
    result = await run_conversation("quien me debe", AUTH, client=client, system_prompt=BASE_PROMPT, erp=erp)  # type: ignore[arg-type]

    first = client.messages.create.call_args_list[0].kwargs
    names = [t["name"] for t in first["tools"]]
    assert "clientes_con_deuda_vencida" in names and "obtener_contexto_empresa" in names
    assert first["system"][0]["text"] == BASE_PROMPT + erp_prompt_block(erp.instructions)
    assert erp.calls == [("clientes_con_deuda_vencida", {"dias": 30})]

    tool_result = _sent_tool_result(client, 1)
    assert tool_result["is_error"] is False
    assert json.loads(tool_result["content"]) == {"total": 186400}

    assert [t.name for t in result.tools_invoked] == ["clientes_con_deuda_vencida"]
    assert result.cards == [card]
    assert result.response_text.startswith("Tenes")


CONTEXT = {
    "empresa": "Kapepro Uruguay SAS",
    "pais": "Uruguay",
    "moneda_base": "UYU",
    "simbolo_moneda": "$U",
    "zona_horaria": "America/Montevideo",
    "emite_efactura": True,
    "fecha_hoy": "2026-11-12",
}


async def test_contexto_de_la_empresa_va_en_un_bloque_aparte_fuera_de_la_cache():
    erp = FakeErp(results={}, tool_names=["obtener_contexto_empresa", "novedades"], context=CONTEXT)
    client = _client([_msg([_text("ok")], "end_turn")])
    await run_conversation("como viene el mes", AUTH, client=client, system_prompt=BASE_PROMPT, erp=erp)  # type: ignore[arg-type]

    system = client.messages.create.call_args.kwargs["system"]
    assert erp.context_requests == 1
    assert len(system) == 2
    assert system[0]["text"] == BASE_PROMPT + erp_prompt_block(erp.instructions), "el bloque cacheado no cambia"
    assert "cache_control" in system[0] and "cache_control" not in system[1]
    assert system[1]["text"] == erp_context_block(CONTEXT)
    assert "- Today: 2026-11-12" in system[1]["text"]
    assert "- Base currency: UYU" in system[1]["text"]
    assert "- Issues e-invoices (CFE): yes" in system[1]["text"]
    assert erp.calls == [], "el contexto no pasa por el modelo ni por erp.call"


async def test_sin_contexto_o_sin_la_tool_el_system_queda_como_antes():
    sin_tool = FakeErp(results={}, tool_names=["novedades"], context=CONTEXT)
    client = _client([_msg([_text("ok")], "end_turn")])
    await run_conversation("hola", AUTH, client=client, system_prompt=BASE_PROMPT, erp=sin_tool)  # type: ignore[arg-type]
    assert sin_tool.context_requests == 0
    assert len(client.messages.create.call_args.kwargs["system"]) == 1

    fallo = FakeErp(results={}, tool_names=["obtener_contexto_empresa"], context=None)
    client = _client([_msg([_text("ok")], "end_turn")])
    await run_conversation("hola", AUTH, client=client, system_prompt=BASE_PROMPT, erp=fallo)  # type: ignore[arg-type]
    assert fallo.context_requests == 1
    assert len(client.messages.create.call_args.kwargs["system"]) == 1


async def test_error_del_erp_llega_al_modelo_y_el_loop_sigue():
    erp = FakeErp(
        results={"preparar_confirmacion_factura": ErpToolResult({"error": "erp_error", "mensaje": "El documento cambio."}, True, 3)},
        tool_names=["preparar_confirmacion_factura"],
    )
    client = _client(
        [
            _msg([_tool_use("t1", "preparar_confirmacion_factura", {"id_factura": 9})], "tool_use"),
            _msg([_text("La factura cambio; la preparo de nuevo si queres.")], "end_turn"),
        ]
    )
    result = await run_conversation("confirma la 9", AUTH, client=client, system_prompt=BASE_PROMPT, erp=erp)  # type: ignore[arg-type]
    tool_result = _sent_tool_result(client, 1)
    assert tool_result["is_error"] is True
    assert "cambio" in json.loads(tool_result["content"])["mensaje"]
    assert result.tools_invoked[0].is_error
    assert result.cards == []


async def test_tool_erp_con_el_nombre_de_una_local_no_pisa_la_local():
    local = anthropic_tools(role="direccion")[0]["name"]
    erp = FakeErp(results={}, tool_names=[local, "novedades"])
    client = _client([_msg([_text("ok")], "end_turn")])
    await run_conversation("hola", AUTH, client=client, system_prompt=BASE_PROMPT, erp=erp)  # type: ignore[arg-type]
    names = [t["name"] for t in client.messages.create.call_args.kwargs["tools"]]
    assert names.count(local) == 1
    assert "novedades" in names


async def test_tarjetas_limitadas_y_con_accion_primero():
    plain = {
        f"t{i}": ErpToolResult({"n": i}, False, 1, ErpCard(tool=f"t{i}", title="x", data={"n": i}))
        for i in range(3)
    }
    action_card = ErpCard(tool="preparar_x", title="Confirmar", data={"confirmar_con": {"herramienta": "confirmar_x"}})
    erp = FakeErp(
        results={**plain, "preparar_x": ErpToolResult({"requiere_confirmacion": "..."}, False, 1, action_card)},
        tool_names=["t0", "t1", "t2", "preparar_x"],
    )
    client = _client(
        [
            _msg([_tool_use("a", "t0", {}), _tool_use("b", "t1", {}), _tool_use("c", "t2", {}), _tool_use("d", "preparar_x", {})], "tool_use"),
            _msg([_text("listo")], "end_turn"),
        ]
    )
    result = await run_conversation("todo", AUTH, client=client, system_prompt=BASE_PROMPT, erp=erp)  # type: ignore[arg-type]
    assert [c.tool for c in result.cards] == ["preparar_x", "t0", "t1"]


async def test_cache_de_prompt_solo_con_tools_erp_y_sin_mutar_el_registry():
    erp = FakeErp(results={}, tool_names=["novedades"])
    client = _client([_msg([_text("ok")], "end_turn")])
    await run_conversation("hola", AUTH, client=client, system_prompt=BASE_PROMPT, erp=erp)  # type: ignore[arg-type]
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert all("cache_control" not in t for t in kwargs["tools"][:-1])
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["cache_control"] == {"type": "ephemeral"}
    # El registry local no queda marcado para los requests siguientes sin ERP.
    assert all("cache_control" not in t for t in anthropic_tools(role="direccion"))

    plain = _client([_msg([_text("ok")], "end_turn")])
    await run_conversation("hola", AUTH, client=plain, system_prompt=BASE_PROMPT)
    plain_kwargs = plain.messages.create.call_args.kwargs
    assert "cache_control" not in plain_kwargs
    assert plain_kwargs["system"] == BASE_PROMPT


async def test_tokens_de_cache_se_cuentan_como_equivalentes_de_entrada():
    erp = FakeErp(results={}, tool_names=["novedades"])
    client = _client(
        [_msg([_text("ok")], "end_turn", input_tokens=100, cache_creation_input_tokens=8000, cache_read_input_tokens=0)]
    )
    first = await run_conversation("hola", AUTH, client=client, system_prompt=BASE_PROMPT, erp=erp)  # type: ignore[arg-type]
    assert first.tokens_input == 100 + 10000  # escritura 1.25x
    assert first.cache_write_tokens == 8000

    client2 = _client(
        [_msg([_text("ok")], "end_turn", input_tokens=100, cache_creation_input_tokens=0, cache_read_input_tokens=8000)]
    )
    second = await run_conversation("hola", AUTH, client=client2, system_prompt=BASE_PROMPT, erp=erp)  # type: ignore[arg-type]
    assert second.tokens_input == 100 + 800  # lectura 0.1x
    assert second.cache_read_tokens == 8000


async def test_subconjunto_por_rol_reduce_las_tools_erp(monkeypatch):
    names = ["obtener_contexto_empresa", "consultar_stock", "saldos_bancarios", "analisis_ventas"]
    erp = FakeErp(results={}, tool_names=names)

    async def offered(role: str) -> list[str]:
        client = _client([_msg([_text("ok")], "end_turn")])
        auth = AuthContext(user_id="1", tenant_id=7, role=role)
        await run_conversation("hola", auth, client=client, system_prompt=BASE_PROMPT, erp=erp)  # type: ignore[arg-type]
        return [t["name"] for t in client.messages.create.call_args.kwargs["tools"] if t["name"] in names]

    assert sorted(await offered("direccion")) == sorted(names)
    assert sorted(await offered("sku")) == ["consultar_stock", "obtener_contexto_empresa"]
    assert "saldos_bancarios" not in await offered("tienda")

    monkeypatch.setattr(settings, "balaxys_mcp_role_subset", False)
    assert sorted(await offered("sku")) == sorted(names)
