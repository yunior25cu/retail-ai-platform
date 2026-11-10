"""Modo "solo ERP" (RETAIL_TOOLS_ENABLED=false): sin tools retail ni prompt retail.

Para ambientes sin almacen gold (Balaxys dev en Azure). Corre en CI: sin base de
datos ni API de Anthropic.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.auth.dependencies import AuthContext
from app.config import settings
from app.llm.orchestrator import run_conversation
from app.mcp_client.balaxys import ErpTool, ErpToolResult

AUTH = AuthContext(user_id="17", tenant_id=7, role="direccion")


def _client(text: str = "ok") -> AsyncMock:
    mock = AsyncMock()
    mock.messages = AsyncMock()
    mock.messages.create = AsyncMock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=5, output_tokens=3),
        )
    )
    return mock


class _Erp:
    instructions = None

    def __init__(self, names: list[str]) -> None:
        self.tools = [ErpTool(n, n, n, {"type": "object", "properties": {}}, True, False) for n in names]

    def anthropic_tools(self) -> list[dict[str, Any]]:
        return [t.to_anthropic() for t in self.tools]

    async def call(self, name: str, arguments: dict[str, Any]) -> ErpToolResult:
        raise AssertionError("no deberia llamarse")


@pytest.fixture(autouse=True)
def _solo_erp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "retail_tools_enabled", False)


async def test_sin_token_no_manda_tools_al_modelo():
    client = _client()
    await run_conversation("hola", AUTH, client=client, system_prompt="base")
    assert "tools" not in client.messages.create.call_args.kwargs


async def test_con_token_ofrece_solo_las_tools_erp():
    client = _client()
    await run_conversation("hola", AUTH, client=client, system_prompt="base", erp=_Erp(["novedades"]))  # type: ignore[arg-type]
    names = [t["name"] for t in client.messages.create.call_args.kwargs["tools"]]
    assert names == ["novedades"]
