"""Schema parity tests between SQL Server (api_audit.*) and
PostgreSQL (audit.* / config.*).

Why this exists
---------------
The repo routes tenants to two DB engines at runtime (see
``app/db/connections.py``). Every dual-routed table must keep the same
column set on both sides — otherwise an agent that touches one schema
and forgets the other introduces silent drift that only surfaces when a
tenant on the forgotten side hits the broken path.

This module compares column NAMES (not types, not order, not
nullability — that would be too brittle across engines that name types
differently). If a test fails the AGENTS.md checklist for "agregar
columna a tabla dual-routed" was not followed: add the missing column
to the side that's behind.

Skipping behaviour
------------------
If one of the two engines is not reachable from the dev environment, the
parity test for that pair is SKIPPED with a clear message, never failed.
That way the suite stays green in environments that only have one DB
configured (e.g. a CI lane that only spins up SQL Server) while still
catching drift when both are available.
"""

from __future__ import annotations

import os
import pytest

# Pairs of (SS_schema, SS_table, PG_schema, PG_table) that must agree on
# column names. Append to this list when you add a new dual-routed table
# whose schemas are meant to be equivalent.
#
# NOT included on purpose:
# - ``api_audit.ai_audit_log`` ↔ ``audit.conversation_log``:
#   conceptually equivalent (both record chat history for billing /
#   audit) but structurally different — SS stores one row per chat turn
#   with hashes and response text; PG stores one row per message
#   (user vs assistant). Drift here is by design and handled in
#   ``get_monthly_spend_usd`` with engine-specific column names
#   (``cost_usd`` vs ``estimated_cost_usd``). DO NOT add to this list.
DUAL_ROUTED_TABLES = [
    ("api_audit", "ai_tenant_config", "config", "tenant_config"),
]


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _fetch_ss_columns(schema: str, table: str) -> set[str] | None:
    """Return the column-name set for an SS table, or None if SS is not
    reachable from this environment."""
    try:
        from app.db.connection import _execute_sync
    except Exception:
        return None
    try:
        rows = _execute_sync(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?;
            """,
            (schema, table),
        )
    except Exception:
        return None
    return {r["COLUMN_NAME"] for r in rows}


def _fetch_pg_columns(schema: str, table: str) -> set[str] | None:
    """Return the column-name set for a PG table, or None if PG is not
    reachable / not configured in this environment."""
    try:
        import psycopg2
        from app.db.connections import _PG_CONN_PARAMS
    except Exception:
        return None
    try:
        conn = psycopg2.connect(**_PG_CONN_PARAMS, connect_timeout=2)
    except Exception:
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s;
            """,
            (schema, table),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


# ----------------------------------------------------------------------------
# Columns that legitimately differ between engines (audit/bookkeeping
# fields that mean the same thing under different names). Add an entry
# with a justification when you find a new acceptable divergence.
# ----------------------------------------------------------------------------
ACCEPTED_DIVERGENCE: dict[tuple[str, str, str, str], dict[str, set[str]]] = {
    # ai_tenant_config keeps `updated_by` only on the SS side — the PG
    # equivalent doesn't track who updated (no auth.users FK yet).
    ("api_audit", "ai_tenant_config", "config", "tenant_config"): {
        "ss_only": {"id", "updated_by"},
        "pg_only": {"id"},
    },
}


# ----------------------------------------------------------------------------
# The actual parity test
# ----------------------------------------------------------------------------

@pytest.mark.parametrize(
    "ss_schema, ss_table, pg_schema, pg_table",
    DUAL_ROUTED_TABLES,
    ids=lambda v: v if isinstance(v, str) else str(v),
)
def test_dual_routed_tables_have_same_columns(
    ss_schema: str, ss_table: str, pg_schema: str, pg_table: str
) -> None:
    ss_cols = _fetch_ss_columns(ss_schema, ss_table)
    pg_cols = _fetch_pg_columns(pg_schema, pg_table)

    if ss_cols is None and pg_cols is None:
        pytest.skip("neither SQL Server nor PostgreSQL reachable")
    if ss_cols is None:
        pytest.skip(f"SQL Server not reachable; cannot validate {ss_schema}.{ss_table}")
    if pg_cols is None:
        pytest.skip(f"PostgreSQL not reachable; cannot validate {pg_schema}.{pg_table}")

    if not ss_cols:
        pytest.skip(f"{ss_schema}.{ss_table} not deployed on SQL Server")
    if not pg_cols:
        pytest.skip(f"{pg_schema}.{pg_table} not deployed on PostgreSQL")

    key = (ss_schema, ss_table, pg_schema, pg_table)
    accepted = ACCEPTED_DIVERGENCE.get(key, {"ss_only": set(), "pg_only": set()})

    only_in_ss = (ss_cols - pg_cols) - accepted["ss_only"]
    only_in_pg = (pg_cols - ss_cols) - accepted["pg_only"]

    msg_lines = []
    if only_in_ss:
        msg_lines.append(
            f"Columns present in {ss_schema}.{ss_table} (SS) but missing in "
            f"{pg_schema}.{pg_table} (PG): {sorted(only_in_ss)}.\n"
            f"  → add them to the PG migration in db/migrations/, or document "
            f"them as accepted divergence in ACCEPTED_DIVERGENCE[\"ss_only\"] "
            f"with a justification."
        )
    if only_in_pg:
        msg_lines.append(
            f"Columns present in {pg_schema}.{pg_table} (PG) but missing in "
            f"{ss_schema}.{ss_table} (SS): {sorted(only_in_pg)}.\n"
            f"  → add them to the SS schema in sql/gold/ or sql/audit/, or "
            f"document them as accepted divergence in "
            f"ACCEPTED_DIVERGENCE[\"pg_only\"] with a justification."
        )

    assert not msg_lines, (
        f"\nSchema drift between SQL Server and PostgreSQL for "
        f"{ss_schema}.{ss_table} ↔ {pg_schema}.{pg_table}:\n\n"
        + "\n\n".join(msg_lines)
        + "\n\nSee AGENTS.md §2.2 for the rule that was violated."
    )


# ----------------------------------------------------------------------------
# Sanity test for the tenant_config Python contract — runs WITHOUT a DB.
# Guards the most common drift inside Python: agregar un campo al
# dataclass y olvidar agregarlo a _VALID_KEYS o a _apply_row.
# ----------------------------------------------------------------------------

def test_tenant_config_dataclass_matches_valid_keys() -> None:
    """Every dataclass field (except internal/derived) MUST appear in
    _VALID_KEYS, and vice-versa. If they diverge, the PUT endpoint
    silently rejects a setting the dataclass knows about, or persists a
    setting the dataclass ignores on the next read."""
    from app.db.tenant_config import TenantConfig, _VALID_KEYS

    dataclass_fields = {f for f in TenantConfig.__dataclass_fields__}

    missing_from_valid = dataclass_fields - _VALID_KEYS
    missing_from_dataclass = _VALID_KEYS - dataclass_fields

    msg = []
    if missing_from_valid:
        msg.append(
            f"Fields in TenantConfig dataclass but NOT in _VALID_KEYS: "
            f"{sorted(missing_from_valid)}.\n"
            f"  → add them to _VALID_KEYS or remove from the dataclass."
        )
    if missing_from_dataclass:
        msg.append(
            f"Keys in _VALID_KEYS but NOT in TenantConfig dataclass: "
            f"{sorted(missing_from_dataclass)}.\n"
            f"  → add the corresponding field to TenantConfig with a default."
        )

    assert not msg, (
        "\ntenant_config.py is internally inconsistent (AGENTS.md §2.3):\n\n"
        + "\n\n".join(msg)
    )


def test_tenant_config_apply_row_covers_all_fields() -> None:
    """_apply_row MUST have a branch for every dataclass field; otherwise
    setting that key in the DB is silently ignored on read."""
    import inspect
    from app.db.tenant_config import TenantConfig, _apply_row

    src = inspect.getsource(_apply_row)
    missing = [
        f for f in TenantConfig.__dataclass_fields__
        if f'"{f}"' not in src and f"'{f}'" not in src
    ]
    assert not missing, (
        f"_apply_row does not handle these dataclass fields: {missing}.\n"
        "Each field MUST have an `elif key == \"X\"` branch (AGENTS.md §2.3)."
    )
