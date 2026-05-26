"""Persistence helpers for multi-turn chat: conversations, messages,
sanitiser token maps.

Every query is tenant-scoped. Loading a conversation that belongs to a
different tenant returns None.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from app.db.connection import execute_query


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------
async def create_conversation(
    *, tenant_id: int, user_id: str, user_role: str, title: str | None = None
) -> str:
    """Create a new conversation row; return its uuid string."""
    cid = str(uuid4())
    sql = """
        INSERT INTO api_audit.conversation
            (conversation_id, tenant_id, user_id, user_role, title, last_message_at)
        VALUES (CAST(? AS UNIQUEIDENTIFIER), ?, ?, ?, ?, SYSUTCDATETIME());
    """
    await execute_query(sql, (cid, tenant_id, user_id, user_role, title))
    return cid


async def load_conversation(
    conversation_id: str, *, tenant_id: int
) -> dict[str, Any] | None:
    """Return the conversation row if it belongs to ``tenant_id``; None otherwise.

    Tenant isolation is enforced here: a /chat call with a foreign
    conversation_id returns None and the endpoint surfaces 404 to the caller.
    """
    sql = """
        SELECT CAST(conversation_id AS NVARCHAR(50)) AS conversation_id,
               tenant_id, user_id, user_role, title
        FROM api_audit.conversation
        WHERE tenant_id = ? AND conversation_id = CAST(? AS UNIQUEIDENTIFIER);
    """
    rows = await execute_query(sql, (tenant_id, conversation_id))
    return rows[0] if rows else None


async def touch_conversation(conversation_id: str) -> None:
    await execute_query(
        """UPDATE api_audit.conversation
           SET last_message_at = SYSUTCDATETIME()
           WHERE conversation_id = CAST(? AS UNIQUEIDENTIFIER);""",
        (conversation_id,),
    )


# ---------------------------------------------------------------------------
# Messages (anthropic-format blocks serialised to JSON)
# ---------------------------------------------------------------------------
async def append_message(
    *, conversation_id: str, role: str, content: Any
) -> int:
    """Append a message; return its sequence number (1-based)."""
    next_seq_rows = await execute_query(
        """SELECT ISNULL(MAX(sequence), 0) + 1 AS seq
           FROM api_audit.conversation_message
           WHERE conversation_id = CAST(? AS UNIQUEIDENTIFIER);""",
        (conversation_id,),
    )
    seq = int(next_seq_rows[0]["seq"])
    await execute_query(
        """INSERT INTO api_audit.conversation_message
               (conversation_id, sequence, role, content_json)
           VALUES (CAST(? AS UNIQUEIDENTIFIER), ?, ?, ?);""",
        (conversation_id, seq, role, json.dumps(content, default=str, ensure_ascii=False)),
    )
    return seq


async def load_messages(conversation_id: str) -> list[dict[str, Any]]:
    """Return messages in Anthropic format (role + content)."""
    rows = await execute_query(
        """SELECT role, content_json
           FROM api_audit.conversation_message
           WHERE conversation_id = CAST(? AS UNIQUEIDENTIFIER)
           ORDER BY sequence ASC;""",
        (conversation_id,),
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            content = json.loads(r["content_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        out.append({"role": r["role"], "content": content})
    return out


# ---------------------------------------------------------------------------
# Token map (sanitiser)
# ---------------------------------------------------------------------------
async def insert_token_mapping(
    *,
    conversation_id: str,
    token: str,
    entity_type: str,
    entity_id: int,
    display_name: str | None = None,
) -> None:
    await execute_query(
        """INSERT INTO api_audit.conversation_token_map
               (conversation_id, token, entity_type, entity_id, display_name)
           VALUES (CAST(? AS UNIQUEIDENTIFIER), ?, ?, ?, ?);""",
        (conversation_id, token, entity_type, entity_id, display_name),
    )


async def find_token_for_entity(
    *, conversation_id: str, entity_type: str, entity_id: int
) -> str | None:
    rows = await execute_query(
        """SELECT token FROM api_audit.conversation_token_map
           WHERE conversation_id = CAST(? AS UNIQUEIDENTIFIER)
             AND entity_type = ? AND entity_id = ?;""",
        (conversation_id, entity_type, entity_id),
    )
    return rows[0]["token"] if rows else None


async def load_token_map(conversation_id: str) -> list[dict[str, Any]]:
    """Return all token mappings for a conversation (used by the de-tokeniser)."""
    return await execute_query(
        """SELECT token, entity_type, entity_id, display_name
           FROM api_audit.conversation_token_map
           WHERE conversation_id = CAST(? AS UNIQUEIDENTIFIER);""",
        (conversation_id,),
    )


# ---------------------------------------------------------------------------
# Display-name lookups for new tokens (sanitiser builds these once per entity)
# ---------------------------------------------------------------------------
async def fetch_display_names(
    tenant_id: int, *, sku_ids: list[int], store_ids: list[int], brand_ids: list[int]
) -> dict[tuple[str, int], str]:
    out: dict[tuple[str, int], str] = {}
    if sku_ids:
        rows = await execute_query(
            f"""SELECT sku_id, sku_code, sku_name FROM gold.dim_sku
                WHERE tenant_id = ? AND sku_id IN ({','.join('?' * len(sku_ids))});""",
            tuple([tenant_id, *sku_ids]),
        )
        for r in rows:
            out[("sku", int(r["sku_id"]))] = f"{r['sku_code']} - {r['sku_name']}"
    if store_ids:
        rows = await execute_query(
            f"""SELECT store_id, store_name FROM gold.dim_store
                WHERE tenant_id = ? AND store_id IN ({','.join('?' * len(store_ids))});""",
            tuple([tenant_id, *store_ids]),
        )
        for r in rows:
            out[("store", int(r["store_id"]))] = str(r["store_name"]).strip()
    if brand_ids:
        rows = await execute_query(
            f"""SELECT DISTINCT brand_id, brand_name FROM gold.dim_sku
                WHERE tenant_id = ? AND brand_id IN ({','.join('?' * len(brand_ids))});""",
            tuple([tenant_id, *brand_ids]),
        )
        for r in rows:
            out[("brand", int(r["brand_id"]))] = str(r["brand_name"]).strip()
    return out
