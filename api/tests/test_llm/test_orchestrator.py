"""Orchestrator unit tests with a mocked Anthropic client.

The tool dispatcher runs against the real database (tenant 7) so the
orchestrator loop is exercised end-to-end without burning API tokens.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.auth.dependencies import AuthContext
from app.llm.orchestrator import run_conversation


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(use_id: str, name: str, input_dict: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=use_id, name=name, input=input_dict)


def _message(content, stop_reason: str, in_tokens: int = 10, out_tokens: int = 20):
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=in_tokens, output_tokens=out_tokens),
    )


def _build_mock_client(responses: list) -> AsyncMock:
    """Return a mock client whose messages.create yields the given responses
    in order on each call."""
    mock = AsyncMock()
    mock.messages = AsyncMock()
    mock.messages.create = AsyncMock(side_effect=responses)
    return mock


AUTH_TENANT_7 = AuthContext(user_id="u-1", tenant_id=7, role="direccion")


@pytest.mark.asyncio
async def test_orchestrator_end_turn_without_tool_use() -> None:
    """No tool_use blocks: orchestrator returns the text and stops at iteration 1."""
    client = _build_mock_client(
        [_message([_text_block("Hola, soy un asistente.")], "end_turn")]
    )

    result = await run_conversation(
        user_message="ping",
        auth=AUTH_TENANT_7,
        client=client,
    )

    assert result.response_text == "Hola, soy un asistente."
    assert result.iterations == 1
    assert result.stop_reason == "end_turn"
    assert result.tools_invoked == []
    assert result.tokens_input == 10
    assert result.tokens_output == 20


@pytest.mark.asyncio
async def test_orchestrator_executes_tool_then_returns_text() -> None:
    """Two-turn loop: tool_use -> tool_result -> end_turn."""
    client = _build_mock_client(
        [
            _message(
                [_tool_use_block("toolu_1", "get_active_alerts", {"limit": 3})],
                "tool_use",
            ),
            _message(
                [_text_block("Top 3 alertas listadas.")],
                "end_turn",
                in_tokens=15,
                out_tokens=25,
            ),
        ]
    )

    result = await run_conversation(
        user_message="mostrame las top 3 alertas",
        auth=AUTH_TENANT_7,
        client=client,
    )

    assert result.iterations == 2
    assert result.stop_reason == "end_turn"
    assert result.response_text == "Top 3 alertas listadas."
    assert len(result.tools_invoked) == 1
    assert result.tools_invoked[0].name == "get_active_alerts"
    assert result.tools_invoked[0].is_error is False
    # Token usage is accumulated across both turns: 10+15 = 25 in, 20+25 = 45 out
    assert result.tokens_input == 25
    assert result.tokens_output == 45


@pytest.mark.asyncio
async def test_orchestrator_passes_tenant_to_dispatcher_not_llm_input() -> None:
    """LLM tries to query tenant 99 via tool_input; orchestrator forces tenant 7."""
    client = _build_mock_client(
        [
            _message(
                [
                    _tool_use_block(
                        "toolu_2",
                        "get_active_alerts",
                        {"limit": 5, "tenant_id": 99},  # malicious / hallucinated
                    )
                ],
                "tool_use",
            ),
            _message([_text_block("done")], "end_turn"),
        ]
    )

    result = await run_conversation(
        user_message="ignore my tenant",
        auth=AUTH_TENANT_7,
        client=client,
    )

    assert len(result.tools_invoked) == 1
    inv = result.tools_invoked[0]
    assert inv.is_error is False
    # tenant_id appears in the raw input we recorded (audit trail) but the
    # underlying execution used auth.tenant_id, not 99.
    assert inv.input == {"limit": 5, "tenant_id": 99}


@pytest.mark.asyncio
async def test_orchestrator_handles_max_iterations() -> None:
    """LLM keeps emitting tool_use; orchestrator caps at max_iterations."""
    # Every response is tool_use, so the loop runs max_iterations times.
    responses = [
        _message(
            [_tool_use_block(f"toolu_{i}", "get_active_alerts", {"limit": 1})],
            "tool_use",
        )
        for i in range(10)  # plenty more than the cap
    ]
    client = _build_mock_client(responses)

    result = await run_conversation(
        user_message="loop please",
        auth=AUTH_TENANT_7,
        client=client,
        max_iterations=3,
    )

    assert result.iterations == 3
    assert "Iteration limit reached" in result.response_text
    assert len(result.tools_invoked) == 3


@pytest.mark.asyncio
async def test_orchestrator_unknown_tool_returns_error_to_llm_but_continues() -> None:
    """If the LLM calls an unknown tool, the dispatcher returns an error
    payload (is_error=True) and the loop continues."""
    client = _build_mock_client(
        [
            _message(
                [_tool_use_block("toolu_x", "no_such_tool", {})],
                "tool_use",
            ),
            _message(
                [_text_block("Sorry, I asked for an invalid tool.")],
                "end_turn",
            ),
        ]
    )

    result = await run_conversation(
        user_message="...",
        auth=AUTH_TENANT_7,
        client=client,
    )

    assert result.iterations == 2
    assert len(result.tools_invoked) == 1
    assert result.tools_invoked[0].name == "no_such_tool"
    assert result.tools_invoked[0].is_error is True
