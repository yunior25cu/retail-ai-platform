"""Dual-database routing.

SQL Server (pymeconta_local) → clientes Balaxys/retail
PostgreSQL (asistente-ia)     → clientes industriales (tenant 24+)

PG_TENANTS is loaded dynamically from auth.tenants on each request
so new tenants added via POST /admin/tenants take effect immediately
without restarting the API. For MVP this is fine; add TTL cache if
latency becomes an issue with 10+ tenants.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

import psycopg2
import psycopg2.extras
import structlog

log = structlog.get_logger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

# Fallback set read at startup — used if the DB query fails
_PG_TENANTS_FALLBACK: set[int] = {
    int(x.strip())
    for x in os.getenv("PG_TENANTS", "24").split(",")
    if x.strip()
}

# Legacy alias kept for backward-compatibility
PG_TENANTS: set[int] = _PG_TENANTS_FALLBACK

_PG_CONN_PARAMS: dict[str, Any] = {
    "host":     os.getenv("PG_HOST",     "localhost"),
    "port":     int(os.getenv("PG_PORT", "5432")),
    "dbname":   os.getenv("PG_DATABASE", "asistente-ia"),
    "user":     os.getenv("PG_USER",     "postgres"),
    "password": os.getenv("PG_PASSWORD", "postgres"),
}


# ── Routing helpers ───────────────────────────────────────────────────────────

def _fetch_pg_tenants_sync() -> set[int]:
    """Query auth.tenants to get current PG tenant set. Falls back to env var set."""
    try:
        conn = psycopg2.connect(**_PG_CONN_PARAMS)
        cur = conn.cursor()
        cur.execute(
            "SELECT platform_tenant_id FROM auth.tenants "
            "WHERE is_active = TRUE AND platform_tenant_id IS NOT NULL"
        )
        rows = cur.fetchall()
        conn.close()
        ids = {int(r[0]) for r in rows if r[0] is not None}
        return ids if ids else _PG_TENANTS_FALLBACK
    except Exception:  # noqa: BLE001
        return _PG_TENANTS_FALLBACK


def is_postgres(tenant_id: int) -> bool:
    """Returns True if this tenant uses PostgreSQL (asistente-ia).

    Queries auth.tenants on each call so new tenants registered via
    POST /admin/tenants are picked up without API restart.
    """
    return tenant_id in _fetch_pg_tenants_sync()


def get_schema(tenant_id: int) -> str:
    """Return 'gold_t{tenant_id}' for PG tenants, 'gold' for SQL Server."""
    return f"gold_t{tenant_id}" if is_postgres(tenant_id) else "gold"


def current_date_expr(tenant_id: int) -> str:
    """DB-appropriate expression for today's date."""
    return "CURRENT_DATE" if is_postgres(tenant_id) else "CAST(GETDATE() AS DATE)"


def current_iso_week_expr(tenant_id: int) -> str:
    """DB-appropriate expression for the current ISO year-week string (YYYY-Www)."""
    if is_postgres(tenant_id):
        return "TO_CHAR(CURRENT_DATE, 'IYYY-\"W\"IW')"
    return "(SELECT iso_year_week FROM gold.dim_date WHERE date = CAST(GETDATE() AS DATE))"


def weeks_ago_expr(tenant_id: int, param_placeholder: str = "?") -> str:
    """Expression for 'N weeks ago' where N comes from a query parameter."""
    if is_postgres(tenant_id):
        ph = "%s" if param_placeholder == "?" else param_placeholder
        return f"CURRENT_DATE - ({ph} * INTERVAL '1 week')"
    return f"DATEADD(WEEK, -{param_placeholder}, CAST(GETDATE() AS DATE))"


def coalesce(tenant_id: int) -> str:
    return "COALESCE" if is_postgres(tenant_id) else "ISNULL"


def top_n_expr(tenant_id: int, n_placeholder: str = "?") -> str:
    """TOP N for SS, empty for PG (use LIMIT at end instead)."""
    if is_postgres(tenant_id):
        return ""
    ph = n_placeholder if n_placeholder != "?" else "?"
    return f"TOP ({ph})"


def limit_expr(tenant_id: int, n_placeholder: str = "?") -> str:
    """LIMIT N for PG, empty for SS (TOP is used at the start)."""
    if is_postgres(tenant_id):
        ph = "%s" if n_placeholder == "?" else n_placeholder
        return f"LIMIT {ph}"
    return ""


# ── PostgreSQL execution ───────────────────────────────────────────────────────

def _convert_placeholders(sql: str) -> str:
    """Replace SQL Server ? with PostgreSQL %s."""
    parts = sql.split("?")
    return "%s".join(parts)


def _execute_pg_sync(sql: str, params: tuple | None) -> list[dict[str, Any]]:
    conn = psycopg2.connect(**_PG_CONN_PARAMS)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(_convert_placeholders(sql), params or ())
        if cur.description is None:
            return []
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


async def _execute_pg(sql: str, params: tuple | None) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_execute_pg_sync, sql, params)


def _execute_pg_write_sync(sql: str, params: tuple | None) -> None:
    conn = psycopg2.connect(**_PG_CONN_PARAMS)
    try:
        cur = conn.cursor()
        cur.execute(_convert_placeholders(sql), params or ())
        conn.commit()
    finally:
        conn.close()


async def _execute_pg_write(sql: str, params: tuple | None = None) -> None:
    """Execute a write (INSERT/UPDATE/DELETE) on PostgreSQL with commit."""
    await asyncio.to_thread(_execute_pg_write_sync, sql, params)


# ── Public routing function ───────────────────────────────────────────────────

_SS_TO_PG_PATTERNS = [
    # N'literal' -> 'literal'  (TSQL NVARCHAR literal prefix)
    (re.compile(r"\bN'"), "'"),
    # ISNULL(a, b) -> COALESCE(a, b)  (PG-compatible drop-in)
    (re.compile(r"\bISNULL\(", re.IGNORECASE), "COALESCE("),
    # CAST(x AS NVARCHAR(N))  -> CAST(x AS TEXT)
    (re.compile(r"\bAS\s+NVARCHAR\s*\(\s*\d+\s*\)", re.IGNORECASE), "AS TEXT"),
    # CAST(x AS NVARCHAR(MAX))  -> CAST(x AS TEXT)
    (re.compile(r"\bAS\s+NVARCHAR\s*\(\s*MAX\s*\)", re.IGNORECASE), "AS TEXT"),
    # CAST(x AS NVARCHAR)  -> CAST(x AS TEXT)
    (re.compile(r"\bAS\s+NVARCHAR\b", re.IGNORECASE), "AS TEXT"),
    # [level], [date], [delete] -> "level", "date", "delete"
    # Only matches lowercase identifiers (table column names by convention)
    (re.compile(r"\[([a-z_][a-z0-9_]*)\]"), r'"\1"'),
    # GETDATE() -> NOW()  (rare; we usually use CURRENT_DATE)
    (re.compile(r"\bGETDATE\s*\(\s*\)", re.IGNORECASE), "NOW()"),
    # SYSUTCDATETIME() -> NOW() AT TIME ZONE 'UTC'
    (re.compile(r"\bSYSUTCDATETIME\s*\(\s*\)", re.IGNORECASE), "(NOW() AT TIME ZONE 'UTC')"),
]

_TOP_PATTERN = re.compile(
    r"^(\s*SELECT\s+)TOP\s*\(\s*\?\s*\)\s+",
    re.IGNORECASE,
)


def _translate_ss_to_pg(
    sql: str, params: tuple[Any, ...] | None, tenant_id: int
) -> tuple[str, tuple[Any, ...]]:
    """Adapt a SQL-Server-flavoured query to PostgreSQL for PG tenants.

    Conservative transformer — only handles patterns actually used by
    retail queries today. New ones go here on demand. Documented in
    AGENTS.md §2.6 (idiom mapping).

    Transformations:
      - schema  ``gold.``       -> ``gold_tNN.`` (NN = tenant_id)
      - ``ISNULL(``             -> ``COALESCE(``
      - ``AS NVARCHAR(N|MAX)``  -> ``AS TEXT``
      - ``[colname]``           -> ``"colname"`` (lowercase ids only)
      - ``SYSUTCDATETIME()``    -> ``(NOW() AT TIME ZONE 'UTC')``
      - ``GETDATE()``           -> ``NOW()``
      - ``SELECT TOP (?) ...``  -> ``SELECT ... LIMIT ?`` (param moves
                                    from first to last position)

    Returns (sql_pg, params_pg). If the input already used PG syntax it
    is left untouched (idempotent for unmodified patterns).
    """
    # Schema rewrite — must come first (the table identifier is part of
    # subsequent replacements). Use the tenant-specific schema gold_tNN.
    sql = sql.replace("gold.", f"gold_t{tenant_id}.")

    for pattern, replacement in _SS_TO_PG_PATTERNS:
        sql = pattern.sub(replacement, sql)

    # TOP (?) is the trickiest: we strip it from the SELECT and append
    # LIMIT %s, shuffling the placeholder from position 0 to the end of
    # ``params``. Only fires when the query starts with SELECT TOP (?) —
    # subqueries or CTEs with TOP would need their own pass (not used in
    # retail queries today).
    m = _TOP_PATTERN.match(sql)
    if m and params is not None and len(params) >= 1:
        sql = m.group(1) + sql[m.end():]
        sql = sql.rstrip().rstrip(";") + " LIMIT %s"
        params = params[1:] + (params[0],)

    return sql, params or ()


async def execute_query_tenant(
    sql: str,
    params: tuple[Any, ...] | None = None,
    tenant_id: int = 0,
) -> list[dict[str, Any]]:
    """Execute a query on the correct database for tenant_id.

    For PG tenants, SQL-Server syntax is auto-translated by
    ``_translate_ss_to_pg`` so retail queries written in T-SQL keep working.
    The translator is conservative — it only handles patterns actually used
    by ``app/db/queries.py``. New ones go in the patterns list on demand.

    For SS tenants the SQL is passed through unchanged.
    """
    if is_postgres(tenant_id):
        sql, params = _translate_ss_to_pg(sql, params, tenant_id)
        return await _execute_pg(sql, params)
    else:
        from app.db.connection import execute_query
        return await execute_query(sql, params)
