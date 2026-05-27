"""Tests for load_recent_messages and count_messages (Sub-fase 5.3).

Uses the real DB (tenant 7). Each test creates a fresh conversation and
cleans up after itself so the data warehouse stays predictable.
"""

from __future__ import annotations

import pytest

from app.db.conversation import (
    append_message,
    count_messages,
    create_conversation,
    load_recent_messages,
)
from app.config import settings


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

def test_memory_turns_setting_is_positive() -> None:
    assert settings.memory_turns_per_request > 0


def test_memory_turns_default_is_three() -> None:
    assert settings.memory_turns_per_request == 3


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _make_conversation(turns: int = 4) -> str:
    """Create a conversation with *turns* user+assistant pairs for tenant 7."""
    conv_id = await create_conversation(tenant_id=7, user_id="test_user", user_role="direccion")
    for i in range(turns):
        await append_message(conversation_id=conv_id, role="user", content=f"pregunta {i + 1}")
        await append_message(conversation_id=conv_id, role="assistant", content=f"respuesta {i + 1}")
    return conv_id


# ─────────────────────────────────────────────────────────────────────────────
# count_messages
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_count_messages_empty_conversation() -> None:
    conv_id = await create_conversation(tenant_id=7, user_id="u", user_role="direccion")
    assert await count_messages(conv_id) == 0


@pytest.mark.asyncio
async def test_count_messages_four_turns() -> None:
    conv_id = await _make_conversation(turns=4)
    assert await count_messages(conv_id) == 8  # 4 turns × 2 messages


# ─────────────────────────────────────────────────────────────────────────────
# load_recent_messages — basic behaviour
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_load_recent_messages_returns_last_n_turns() -> None:
    conv_id = await _make_conversation(turns=4)  # 8 messages total

    msgs = await load_recent_messages(conv_id, tenant_id=7, turns=2)
    assert len(msgs) == 4  # 2 turns × 2 messages


@pytest.mark.asyncio
async def test_load_recent_messages_chronological_order() -> None:
    conv_id = await _make_conversation(turns=4)

    msgs = await load_recent_messages(conv_id, tenant_id=7, turns=3)
    # Last 3 turns = turns 2, 3, 4 (0-indexed) → content: pregunta 2..4, respuesta 2..4
    texts = [m["content"] for m in msgs]
    # Should be oldest first: pregunta 2, respuesta 2, pregunta 3, respuesta 3, pregunta 4, respuesta 4
    assert texts[0] == "pregunta 2"
    assert texts[1] == "respuesta 2"
    assert texts[-2] == "pregunta 4"
    assert texts[-1] == "respuesta 4"


@pytest.mark.asyncio
async def test_load_recent_messages_uses_settings_default_when_turns_none() -> None:
    """With turns=None, the function uses settings.memory_turns_per_request."""
    n = settings.memory_turns_per_request  # default 3
    conv_id = await _make_conversation(turns=n + 2)  # more turns than the limit

    msgs = await load_recent_messages(conv_id, tenant_id=7, turns=None)
    assert len(msgs) == n * 2


@pytest.mark.asyncio
async def test_load_recent_messages_fewer_than_limit_returns_all() -> None:
    """If the conversation has fewer turns than the limit, all messages are returned."""
    conv_id = await _make_conversation(turns=1)  # 2 messages

    msgs = await load_recent_messages(conv_id, tenant_id=7, turns=5)
    assert len(msgs) == 2  # only 1 turn exists


@pytest.mark.asyncio
async def test_load_recent_messages_roles_alternate() -> None:
    """Messages must alternate user / assistant in chronological order."""
    conv_id = await _make_conversation(turns=3)

    msgs = await load_recent_messages(conv_id, tenant_id=7, turns=3)
    roles = [m["role"] for m in msgs]
    expected = ["user", "assistant"] * 3
    assert roles == expected


# ─────────────────────────────────────────────────────────────────────────────
# load_recent_messages — tenant isolation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_load_recent_messages_wrong_tenant_returns_empty() -> None:
    """A conversation belonging to tenant 7 should return no messages for tenant 99."""
    conv_id = await _make_conversation(turns=2)

    msgs = await load_recent_messages(conv_id, tenant_id=99, turns=10)
    assert msgs == [], "Tenant isolation breach: messages returned for wrong tenant"


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/conversations/{id} summary endpoint
# ─────────────────────────────────────────────────────────────────────────────

def test_conversations_endpoint_valid(client) -> None:
    """Create a conversation via the chat endpoint and verify the summary endpoint."""
    # Use mock auth to post a chat message, creating a new conversation.
    r = client.post(
        "/api/v1/chat",
        json={"message": "hola"},
        headers={"X-Mock-Tenant": "7", "X-Mock-Role": "direccion"},
    )
    assert r.status_code == 200
    conv_id = r.json()["conversation_id"]

    r2 = client.get(
        f"/api/v1/conversations/{conv_id}",
        headers={"X-Mock-Tenant": "7", "X-Mock-Role": "direccion"},
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["conversation_id"] == conv_id
    assert body["total_messages"] >= 2
    assert body["memory_turns"] == settings.memory_turns_per_request
    assert isinstance(body["recent_messages"], list)


def test_conversations_endpoint_unknown_id_returns_404(client) -> None:
    r = client.get(
        "/api/v1/conversations/00000000-0000-0000-0000-000000000000",
        headers={"X-Mock-Tenant": "7", "X-Mock-Role": "direccion"},
    )
    assert r.status_code == 404


def test_conversations_endpoint_foreign_tenant_returns_404(client) -> None:
    """A conversation from tenant 7 is not visible to tenant 8."""
    r = client.post(
        "/api/v1/chat",
        json={"message": "hola"},
        headers={"X-Mock-Tenant": "7", "X-Mock-Role": "direccion"},
    )
    assert r.status_code == 200
    conv_id = r.json()["conversation_id"]

    r2 = client.get(
        f"/api/v1/conversations/{conv_id}",
        headers={"X-Mock-Tenant": "8", "X-Mock-Role": "direccion"},
    )
    assert r2.status_code == 404
