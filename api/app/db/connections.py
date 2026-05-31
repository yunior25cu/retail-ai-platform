"""Dual-database routing.

SQL Server (pymeconta_local) → clientes Balaxys/retail
PostgreSQL (asistente-ia)     → clientes industriales (tenant 24+)

The retail tools and all existing Balaxys code are untouched —
they continue to call execute_query() which always hits SQL Server.

Production tools call execute_query_tenant(sql, params, tenant_id)
which routes to the right DB and handles placeholder differences.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import psycopg2
import psycopg2.extras
import structlog

log = structlog.get_logger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

def _load_pg_tenants() -> set[int]:
    raw = os.getenv("PG_TENANTS", "24")
    return {int(x.strip()) for x in raw.split(",") if x.strip()}

PG_TENANTS: set[int] = _load_pg_tenants()

_PG_CONN_PARAMS: dict[str, Any] = {
    "host":     os.getenv("PG_HOST",     "localhost"),
    "port":     int(os.getenv("PG_PORT", "5432")),
    "dbname":   os.getenv("PG_DATABASE", "asistente-ia"),
    "user":     os.getenv("PG_USER",     "postgres"),
    "password": os.getenv("PG_PASSWORD", "postgres"),
}


# ── Routing helpers ───────────────────────────────────────────────────────────

def is_postgres(tenant_id: int) -> bool:
    return tenant_id in PG_TENANTS


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


# ── Public routing function ───────────────────────────────────────────────────

async def execute_query_tenant(
    sql: str,
    params: tuple[Any, ...] | None = None,
    tenant_id: int = 0,
) -> list[dict[str, Any]]:
    """Execute a query on the correct database for tenant_id.

    Production tools use this instead of execute_query().
    Retail tools keep using execute_query() — no change.
    """
    if is_postgres(tenant_id):
        return await _execute_pg(sql, params)
    else:
        from app.db.connection import execute_query
        return await execute_query(sql, params)
