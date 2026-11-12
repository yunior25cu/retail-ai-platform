"""Tarjetas y request_id en el historial de conversaciones (migracion 013).

Sin base real: se reemplazan execute_query/_pg_execute/_pg_write por fakes que
registran el SQL y simulan la base con o sin las columnas nuevas.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.db import conversation as conv
from app.mcp_client.balaxys import HISTORY_EXPIRED_FIELD, ErpCard


class FakeDb:
    """Simula conversation_message en SQL Server o PostgreSQL."""

    def __init__(self, *, optional_columns: bool, backend: str = "ss") -> None:
        self.optional_columns = optional_columns
        self.backend = backend
        self.rows: list[dict[str, Any]] = []
        self.statements: list[str] = []

    def _check(self, sql: str) -> None:
        self.statements.append(sql)
        if not self.optional_columns and ("cards_json" in sql or "request_id" in sql):
            if self.backend == "ss":
                raise RuntimeError("[42S22] Invalid column name 'cards_json'.")
            raise RuntimeError('column cm.cards_json does not exist')

    async def run(self, sql: str, params: tuple) -> list[dict[str, Any]]:
        self._check(sql)
        if "MAX(sequence)" in sql:
            return [{"seq": len(self.rows) + 1}]
        if sql.lstrip().startswith("INSERT"):
            row = {"role": params[2], "content_json": params[3], "created_at": "2026-11-12T10:00:00"}
            if "cards_json" in sql:
                row["cards_json"], row["request_id"] = params[4], params[5]
            self.rows.append(row)
            return []
        if "SELECT cm.role" in sql:
            with_optional = "cards_json" in sql
            return [
                {k: v for k, v in r.items() if with_optional or k not in ("cards_json", "request_id")}
                for r in self.rows
            ]
        raise AssertionError(f"SQL inesperado: {sql}")

    async def write(self, sql: str, params: tuple) -> None:
        await self.run(sql, params)


@pytest.fixture(autouse=True)
def _reset_optional_columns_cache():
    conv._optional_columns_missing_until.clear()
    yield
    conv._optional_columns_missing_until.clear()


def _install(monkeypatch: pytest.MonkeyPatch, db: FakeDb) -> None:
    monkeypatch.setattr(conv, "_is_pg", lambda tenant_id: db.backend == "pg")
    monkeypatch.setattr(conv, "execute_query", db.run)
    monkeypatch.setattr(conv, "_pg_execute", db.run)
    monkeypatch.setattr(conv, "_pg_write", db.write)


_CARD = {"tool": "cuentas_por_cobrar", "title": "Cuentas por cobrar", "data": {"total": 1525048.2, "clientes": [{"nombre": "A", "saldo": 10}]}}


@pytest.mark.parametrize("backend", ["ss", "pg"])
@pytest.mark.asyncio
async def test_historial_devuelve_tarjetas_y_request_id(monkeypatch: pytest.MonkeyPatch, backend: str) -> None:
    db = FakeDb(optional_columns=True, backend=backend)
    _install(monkeypatch, db)

    await conv.append_message(conversation_id="c1", role="user", content="cuanto me deben", tenant_id=7)
    await conv.append_message(
        conversation_id="c1", role="assistant", content="Te deben 1.525.048", tenant_id=7,
        cards=[_CARD], request_id="req-1",
    )
    rows = await conv.fetch_conversation_messages_for_history("c1", 7)

    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert rows[0]["cards"] == [] and rows[0]["request_id"] is None
    assert rows[1]["content"] == "Te deben 1.525.048"
    assert rows[1]["cards"] == [_CARD]
    assert rows[1]["request_id"] == "req-1"
    # El texto que se reenvia a Claude no lleva las tarjetas.
    assert json.loads(db.rows[1]["content_json"]) == "Te deben 1.525.048"


@pytest.mark.parametrize("backend", ["ss", "pg"])
@pytest.mark.asyncio
async def test_sin_columnas_nuevas_guarda_y_lee_solo_el_texto(monkeypatch: pytest.MonkeyPatch, backend: str) -> None:
    db = FakeDb(optional_columns=False, backend=backend)
    _install(monkeypatch, db)

    await conv.append_message(
        conversation_id="c1", role="assistant", content="Hola", tenant_id=7, cards=[_CARD], request_id="req-1"
    )
    rows = await conv.fetch_conversation_messages_for_history("c1", 7)

    assert rows == [
        {"role": "assistant", "content": "Hola", "tools_used": None, "duration_ms": None,
         "created_at": "2026-11-12T10:00:00", "cards": [], "request_id": None}
    ]
    # Despues del primer fallo no vuelve a intentar las columnas en cada request.
    db.statements.clear()
    await conv.append_message(conversation_id="c1", role="assistant", content="Otra", tenant_id=7, cards=[_CARD])
    await conv.fetch_conversation_messages_for_history("c1", 7)
    assert not any("cards_json" in s for s in db.statements)


@pytest.mark.asyncio
async def test_vuelve_a_intentar_las_columnas_despues_del_plazo(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeDb(optional_columns=False)
    _install(monkeypatch, db)
    await conv.fetch_conversation_messages_for_history("c1", 7)
    assert not conv._optional_columns_available("ss")

    db.optional_columns = True  # se corrio la migracion
    conv._optional_columns_missing_until["ss"] = 0.0  # vencio el plazo de reintento
    await conv.append_message(conversation_id="c1", role="assistant", content="Hola", tenant_id=7, cards=[_CARD])
    assert (await conv.fetch_conversation_messages_for_history("c1", 7))[0]["cards"] == [_CARD]


@pytest.mark.asyncio
async def test_otro_error_de_base_no_se_traga(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeDb(optional_columns=True)
    _install(monkeypatch, db)

    async def boom(sql: str, params: tuple) -> list[dict[str, Any]]:
        raise RuntimeError("timeout")

    monkeypatch.setattr(conv, "execute_query", boom)
    with pytest.raises(RuntimeError, match="timeout"):
        await conv.fetch_conversation_messages_for_history("c1", 7)


@pytest.mark.asyncio
async def test_mensaje_sin_tarjetas_no_usa_las_columnas_nuevas(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeDb(optional_columns=True)
    _install(monkeypatch, db)
    await conv.append_message(conversation_id="c1", role="user", content="hola", tenant_id=7)
    assert not any("cards_json" in s for s in db.statements)


def test_tarjeta_de_accion_en_el_historial_no_lleva_token_ni_accion() -> None:
    card = ErpCard(
        tool="preparar_emision_cfe",
        title="Emitir CFE",
        data={
            "id_factura": 10,
            "total": 122,
            "token_confirmacion": "bmcpc.secreto",
            "confirmar_con": {"herramienta": "emitir_cfe", "argumentos": {"id_factura": 10, "token_confirmacion": "bmcpc.secreto"}},
        },
    )
    saved = card.to_history_dict()

    assert "bmcpc.secreto" not in json.dumps(saved)
    assert saved["data"] == {"id_factura": 10, "total": 122, HISTORY_EXPIRED_FIELD: True}
    # La tarjeta en vivo no cambia.
    assert card.to_dict()["data"]["confirmar_con"]["herramienta"] == "emitir_cfe"


def test_tarjeta_de_datos_se_guarda_igual() -> None:
    card = ErpCard(tool="cuentas_por_cobrar", title="Cuentas por cobrar", data={"total": 5})
    assert card.to_history_dict() == {"tool": "cuentas_por_cobrar", "title": "Cuentas por cobrar", "data": {"total": 5}}
