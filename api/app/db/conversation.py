"""Persistence helpers for multi-turn chat: conversations, messages,
sanitiser token maps.

Routing:
  PG tenants (e.g. tenant 24) → audit.conversation / audit.conversation_message
  SS tenants                  → api_audit.conversation / api_audit.conversation_message

Every query is tenant-scoped. Loading a conversation that belongs to a
different tenant returns None.
"""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

import structlog

from app.db.connection import execute_query

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Columnas opcionales de conversation_message (migracion 013): cards_json y
# request_id. Si la base todavia no las tiene, se escribe y se lee como antes
# y se reintenta cada _OPTIONAL_COLUMNS_RETRY_S (despues de migrar no hace
# falta reiniciar la API).
# ---------------------------------------------------------------------------

_OPTIONAL_COLUMNS_RETRY_S = 600.0
_optional_columns_missing_until: dict[str, float] = {}


def _optional_columns_available(backend: str) -> bool:
    return time.monotonic() >= _optional_columns_missing_until.get(backend, 0.0)


def _is_missing_optional_column(error: Exception) -> bool:
    text = str(error).lower()
    return ("cards_json" in text or "request_id" in text) and (
        "invalid column" in text or "does not exist" in text or "undefined" in text
    )


def _mark_optional_columns_missing(backend: str, error: Exception) -> None:
    _optional_columns_missing_until[backend] = time.monotonic() + _OPTIONAL_COLUMNS_RETRY_S
    log.warning("conversation.optional_columns_missing", backend=backend, detail=str(error)[:200])


def _parse_cards(cards_json: Any) -> list[dict[str, Any]]:
    if not cards_json:
        return []
    try:
        parsed = json.loads(cards_json)
    except (TypeError, json.JSONDecodeError):
        return []
    return [c for c in parsed if isinstance(c, dict)] if isinstance(parsed, list) else []


# ---------------------------------------------------------------------------
# Internal PG helpers
# ---------------------------------------------------------------------------

async def _pg_execute(sql: str, params: tuple) -> list[dict[str, Any]]:
    """Run a read or write query against PostgreSQL conversation tables."""
    from app.db.connections import _execute_pg
    return await _execute_pg(sql, params)


async def _pg_write(sql: str, params: tuple) -> None:
    """Run a write (INSERT/UPDATE) against PostgreSQL with commit."""
    from app.db.connections import _execute_pg_write
    await _execute_pg_write(sql, params)


def _is_pg(tenant_id: int) -> bool:
    from app.db.connections import is_postgres
    return is_postgres(tenant_id)


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------

async def create_conversation(
    *, tenant_id: int, user_id: str, user_role: str, title: str | None = None
) -> str:
    """Create a new conversation row; return its uuid string."""
    cid = str(uuid4())

    if _is_pg(tenant_id):
        await _pg_write(
            """INSERT INTO audit.conversation
                   (conversation_id, tenant_id, user_id, user_role, title)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (conversation_id) DO NOTHING""",
            (cid, tenant_id, user_id, user_role, title),
        )
    else:
        await execute_query(
            """INSERT INTO api_audit.conversation
                   (conversation_id, tenant_id, user_id, user_role, title, last_message_at)
               VALUES (CAST(? AS UNIQUEIDENTIFIER), ?, ?, ?, ?, SYSUTCDATETIME());""",
            (cid, tenant_id, user_id, user_role, title),
        )
    return cid


async def load_conversation(
    conversation_id: str, *, tenant_id: int
) -> dict[str, Any] | None:
    """Return the conversation row if it belongs to ``tenant_id``; None otherwise."""
    if _is_pg(tenant_id):
        rows = await _pg_execute(
            """SELECT conversation_id, tenant_id, user_id, user_role, title
               FROM audit.conversation
               WHERE tenant_id = %s AND conversation_id = %s""",
            (tenant_id, conversation_id),
        )
    else:
        rows = await execute_query(
            """SELECT CAST(conversation_id AS NVARCHAR(50)) AS conversation_id,
                      tenant_id, user_id, user_role, title
               FROM api_audit.conversation
               WHERE tenant_id = ? AND conversation_id = CAST(? AS UNIQUEIDENTIFIER);""",
            (tenant_id, conversation_id),
        )
    return rows[0] if rows else None


async def touch_conversation(conversation_id: str, tenant_id: int = 0) -> None:
    if _is_pg(tenant_id):
        await _pg_write(
            """UPDATE audit.conversation
               SET last_message_at = NOW()
               WHERE conversation_id = %s""",
            (conversation_id,),
        )
    else:
        await execute_query(
            """UPDATE api_audit.conversation
               SET last_message_at = SYSUTCDATETIME()
               WHERE conversation_id = CAST(? AS UNIQUEIDENTIFIER);""",
            (conversation_id,),
        )


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

async def append_message(
    *,
    conversation_id: str,
    role: str,
    content: Any,
    tenant_id: int = 0,
    cards: list[dict[str, Any]] | None = None,
    request_id: str | None = None,
) -> int:
    """Append a message; return its sequence number (1-based).

    ``cards`` (tarjetas ya preparadas para el historial) y ``request_id`` solo
    se guardan en las respuestas del asistente. No van en ``content_json``:
    ese campo se le reenvia a Claude como historia.
    """
    content_json = json.dumps(content, default=str, ensure_ascii=False)
    cards_json = json.dumps(cards, default=str, ensure_ascii=False) if cards else None
    with_optional = cards_json is not None or request_id is not None

    if _is_pg(tenant_id):
        rows = await _pg_execute(
            """SELECT COALESCE(MAX(sequence), 0) + 1 AS seq
               FROM audit.conversation_message
               WHERE conversation_id = %s""",
            (conversation_id,),
        )
        seq = int(rows[0]["seq"]) if rows else 1
        if with_optional and _optional_columns_available("pg"):
            try:
                await _pg_write(
                    """INSERT INTO audit.conversation_message
                           (conversation_id, sequence, role, content_json, cards_json, request_id)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (conversation_id, sequence) DO NOTHING""",
                    (conversation_id, seq, role, content_json, cards_json, request_id),
                )
                return seq
            except Exception as e:  # noqa: BLE001
                if not _is_missing_optional_column(e):
                    raise
                _mark_optional_columns_missing("pg", e)
        await _pg_write(
            """INSERT INTO audit.conversation_message
                   (conversation_id, sequence, role, content_json)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (conversation_id, sequence) DO NOTHING""",
            (conversation_id, seq, role, content_json),
        )
        return seq
    else:
        next_seq_rows = await execute_query(
            """SELECT ISNULL(MAX(sequence), 0) + 1 AS seq
               FROM api_audit.conversation_message
               WHERE conversation_id = CAST(? AS UNIQUEIDENTIFIER);""",
            (conversation_id,),
        )
        seq = int(next_seq_rows[0]["seq"]) if next_seq_rows else 1
        if with_optional and _optional_columns_available("ss"):
            try:
                await execute_query(
                    """INSERT INTO api_audit.conversation_message
                           (conversation_id, sequence, role, content_json, cards_json, request_id)
                       VALUES (CAST(? AS UNIQUEIDENTIFIER), ?, ?, ?, ?, ?);""",
                    (conversation_id, seq, role, content_json, cards_json, request_id),
                )
                return seq
            except Exception as e:  # noqa: BLE001
                if not _is_missing_optional_column(e):
                    raise
                _mark_optional_columns_missing("ss", e)
        await execute_query(
            """INSERT INTO api_audit.conversation_message
                   (conversation_id, sequence, role, content_json)
               VALUES (CAST(? AS UNIQUEIDENTIFIER), ?, ?, ?);""",
            (conversation_id, seq, role, content_json),
        )
        return seq


async def load_messages(conversation_id: str, tenant_id: int = 0) -> list[dict[str, Any]]:
    """Return all messages in Anthropic format, oldest first."""
    if _is_pg(tenant_id):
        rows = await _pg_execute(
            """SELECT role, content_json FROM audit.conversation_message
               WHERE conversation_id = %s ORDER BY sequence ASC""",
            (conversation_id,),
        )
    else:
        rows = await execute_query(
            """SELECT role, content_json FROM api_audit.conversation_message
               WHERE conversation_id = CAST(? AS UNIQUEIDENTIFIER)
               ORDER BY sequence ASC;""",
            (conversation_id,),
        )
    return _parse_message_rows(rows)


async def count_messages(conversation_id: str, tenant_id: int = 0) -> int:
    if _is_pg(tenant_id):
        rows = await _pg_execute(
            "SELECT COUNT(*) AS cnt FROM audit.conversation_message WHERE conversation_id = %s",
            (conversation_id,),
        )
    else:
        rows = await execute_query(
            """SELECT COUNT(*) AS cnt FROM api_audit.conversation_message
               WHERE conversation_id = CAST(? AS UNIQUEIDENTIFIER);""",
            (conversation_id,),
        )
    return int(rows[0]["cnt"]) if rows else 0


async def load_recent_messages(
    conversation_id: str,
    *,
    tenant_id: int,
    turns: int | None = None,
) -> list[dict[str, Any]]:
    """Return the last *turns* user+assistant pairs, oldest first."""
    from app.config import settings

    effective_turns = turns if turns is not None else settings.memory_turns_per_request
    limit = effective_turns * 2

    if _is_pg(tenant_id):
        rows = await _pg_execute(
            """SELECT role, content_json
               FROM audit.conversation_message
               WHERE conversation_id = %s
                 AND EXISTS (
                     SELECT 1 FROM audit.conversation c
                     WHERE c.conversation_id = %s AND c.tenant_id = %s
                 )
               ORDER BY sequence DESC
               LIMIT %s""",
            (conversation_id, conversation_id, tenant_id, limit),
        )
    else:
        rows = await execute_query(
            """SELECT TOP (?) role, content_json
               FROM api_audit.conversation_message cm
               WHERE cm.conversation_id = CAST(? AS UNIQUEIDENTIFIER)
                 AND EXISTS (
                     SELECT 1 FROM api_audit.conversation c
                     WHERE c.conversation_id = cm.conversation_id
                       AND c.tenant_id = ?
                 )
               ORDER BY cm.sequence DESC;""",
            (limit, conversation_id, tenant_id),
        )
    return _parse_message_rows(reversed(rows))


def _parse_message_rows(rows: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            content = json.loads(r["content_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        out.append({"role": r["role"], "content": content})
    return out


# ---------------------------------------------------------------------------
# Conversation history — used by GET /internal/conversations endpoints
# ---------------------------------------------------------------------------

def _extract_title(content_json: str | None, max_len: int = 40) -> str:
    if not content_json:
        return "Nueva conversacion"
    try:
        parsed = json.loads(content_json)
        if isinstance(parsed, str):
            text: str = parsed
        elif isinstance(parsed, list):
            text = " ".join(
                block.get("text", "") for block in parsed
                if isinstance(block, dict) and block.get("type") == "text"
            )
        else:
            text = str(parsed)
        return text[:max_len] if text.strip() else "Nueva conversacion"
    except (TypeError, json.JSONDecodeError):
        return "Nueva conversacion"


def _extract_content_text(content_json: str) -> str:
    try:
        parsed = json.loads(content_json)
        if isinstance(parsed, str):
            return parsed
        if isinstance(parsed, list):
            texts = [
                block.get("text", "") for block in parsed
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            return "\n".join(t for t in texts if t)
        return str(parsed)
    except (TypeError, json.JSONDecodeError):
        return content_json or ""


async def fetch_conversations(
    tenant_id: int, user_id: int, limit: int = 20
) -> list[dict[str, Any]]:
    """Return the most recent *limit* conversations for *user_id* under *tenant_id*."""
    user_id_str = str(user_id)

    if _is_pg(tenant_id):
        rows = await _pg_execute(
            """SELECT c.conversation_id,
                      c.last_message_at,
                      (SELECT COUNT(*) FROM audit.conversation_message cm2
                       WHERE cm2.conversation_id = c.conversation_id) AS message_count,
                      (SELECT cm.content_json
                       FROM audit.conversation_message cm
                       WHERE cm.conversation_id = c.conversation_id AND cm.role = 'user'
                       ORDER BY cm.sequence ASC LIMIT 1) AS first_message_json
               FROM audit.conversation c
               WHERE c.tenant_id = %s AND c.user_id = %s
               ORDER BY COALESCE(c.last_message_at, c.started_at) DESC
               LIMIT %s""",
            (tenant_id, user_id_str, limit),
        )
    else:
        rows = await execute_query(
            """SELECT TOP (?)
                   CAST(c.conversation_id AS NVARCHAR(50)) AS conversation_id,
                   CONVERT(NVARCHAR(30), ISNULL(c.last_message_at, c.started_at), 127)
                       AS last_message_at,
                   (SELECT COUNT(*) FROM api_audit.conversation_message cm2
                    WHERE cm2.conversation_id = c.conversation_id) AS message_count,
                   (SELECT TOP 1 cm.content_json
                    FROM api_audit.conversation_message cm
                    WHERE cm.conversation_id = c.conversation_id AND cm.role = 'user'
                    ORDER BY cm.sequence ASC) AS first_message_json
               FROM api_audit.conversation c
               WHERE c.tenant_id = ? AND c.user_id = ?
               ORDER BY ISNULL(c.last_message_at, c.started_at) DESC;""",
            (limit, tenant_id, user_id_str),
        )

    result: list[dict[str, Any]] = []
    for row in rows:
        lma = row.get("last_message_at")
        result.append({
            "conversation_id": row["conversation_id"],
            "title": _extract_title(row.get("first_message_json")),
            "last_message_at": lma.isoformat() if hasattr(lma, "isoformat") else str(lma) if lma else None,
            "message_count": int(row["message_count"] or 0),
        })
    return result


async def fetch_conversation_messages_for_history(
    conversation_id: str, tenant_id: int
) -> list[dict[str, Any]]:
    """Return all messages for *conversation_id*, validating tenant ownership.

    Incluye las tarjetas (``cards``) y el ``request_id`` de cada respuesta del
    asistente cuando la base tiene esas columnas (migracion 013).
    """
    backend = "pg" if _is_pg(tenant_id) else "ss"
    rows: list[dict[str, Any]] | None = None
    if _optional_columns_available(backend):
        try:
            rows = await _history_rows(backend, conversation_id, tenant_id, with_optional=True)
        except Exception as e:  # noqa: BLE001
            if not _is_missing_optional_column(e):
                raise
            _mark_optional_columns_missing(backend, e)
    if rows is None:
        rows = await _history_rows(backend, conversation_id, tenant_id, with_optional=False)

    return [
        {
            "role": row["role"],
            "content": _extract_content_text(row["content_json"]),
            "tools_used": None,
            "duration_ms": None,
            "created_at": (
                row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"])
            ),
            "cards": _parse_cards(row.get("cards_json")),
            "request_id": row.get("request_id") or None,
        }
        for row in rows
    ]


async def _history_rows(
    backend: str, conversation_id: str, tenant_id: int, *, with_optional: bool
) -> list[dict[str, Any]]:
    if backend == "pg":
        extra = ", cm.cards_json, cm.request_id" if with_optional else ""
        return await _pg_execute(
            f"""SELECT cm.role, cm.content_json, cm.created_at{extra}
               FROM audit.conversation_message cm
               INNER JOIN audit.conversation c
                   ON c.conversation_id = cm.conversation_id
                  AND c.tenant_id = %s
               WHERE cm.conversation_id = %s
               ORDER BY cm.sequence ASC""",
            (tenant_id, conversation_id),
        )
    extra = ", cm.cards_json, cm.request_id" if with_optional else ""
    return await execute_query(
        f"""SELECT cm.role, cm.content_json,
                  CONVERT(NVARCHAR(30), cm.created_at, 127) AS created_at{extra}
           FROM api_audit.conversation_message cm
           INNER JOIN api_audit.conversation c
               ON c.conversation_id = cm.conversation_id AND c.tenant_id = ?
           WHERE cm.conversation_id = CAST(? AS UNIQUEIDENTIFIER)
           ORDER BY cm.sequence ASC;""",
        (tenant_id, conversation_id),
    )


# ---------------------------------------------------------------------------
# Token map (sanitiser) — SQL Server only (retail tenants use sanitiser)
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
    return await execute_query(
        """SELECT token, entity_type, entity_id, display_name
           FROM api_audit.conversation_token_map
           WHERE conversation_id = CAST(? AS UNIQUEIDENTIFIER);""",
        (conversation_id,),
    )


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
