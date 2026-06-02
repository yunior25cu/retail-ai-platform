"""Database queries for auth.tenants, auth.users, auth.refresh_tokens.

Follows the same pyodbc / execute_query pattern used across the project.
No ORM. All queries are parameterised with ? placeholders.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from app.auth.models import RefreshToken, Tenant, User
from app.db.connection import execute_query


def _row_to_tenant(row: dict) -> Tenant:
    ptid = row.get("platform_tenant_id")
    return Tenant(
        id=int(row["id"]),
        name=row["name"],
        slug=row["slug"],
        vertical=row["vertical"],
        plan=row.get("tenant_plan") or row.get("plan") or "starter",
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        trial_ends_at=row.get("trial_ends_at"),
        platform_tenant_id=int(ptid) if ptid is not None else None,
    )


def _row_to_user(row: dict) -> User:
    uid = row["id"]
    return User(
        id=UUID(str(uid)) if not isinstance(uid, UUID) else uid,
        tenant_id=int(row["tenant_id"]),
        email=row["email"],
        password_hash=row["password_hash"],
        role=row["role"],
        full_name=row.get("full_name"),
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        last_login_at=row.get("last_login_at"),
    )


async def get_tenant_by_slug(slug: str) -> Tenant | None:
    rows = await execute_query(
        "SELECT * FROM auth.tenants WHERE slug = ? AND is_active = 1;",
        (slug,),
    )
    if rows:
        return _row_to_tenant(rows[0])
    # Fall back to PostgreSQL (standalone tenants like 'admin' live there)
    return await _get_tenant_by_slug_pg(slug)


async def _get_tenant_by_slug_pg(slug: str) -> Tenant | None:
    import asyncio as _asyncio
    import psycopg2 as _pg
    import psycopg2.extras as _pgx
    from app.db.connections import _PG_CONN_PARAMS

    def _query() -> list:
        conn = _pg.connect(**_PG_CONN_PARAMS)
        try:
            cur = conn.cursor(cursor_factory=_pgx.RealDictCursor)
            cur.execute(
                "SELECT * FROM auth.tenants WHERE slug = %s AND is_active = TRUE",
                (slug,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    rows = await _asyncio.to_thread(_query)
    if not rows:
        return None
    r = rows[0]
    return Tenant(
        id=r["id"],
        name=r["name"],
        slug=r["slug"],
        vertical=r["vertical"],
        plan=r.get("tenant_plan") or "starter",
        is_active=bool(r["is_active"]),
        created_at=r["created_at"],
        trial_ends_at=r.get("trial_ends_at"),
        platform_tenant_id=r.get("platform_tenant_id"),
    )


async def get_tenant_by_id(tenant_id: int) -> Tenant | None:
    rows = await execute_query(
        "SELECT * FROM auth.tenants WHERE id = ? AND is_active = 1;",
        (tenant_id,),
    )
    return _row_to_tenant(rows[0]) if rows else None


async def get_tenant_name_by_platform_id(platform_tenant_id: int) -> str | None:
    """Display name for a tenant given the value that lives in JWT.tenant_id
    (which is platform_tenant_id, not auth.tenants.id). Used by /me to
    populate the context bar.

    Looks in SQL Server first (where most tenants live) and falls back to
    PostgreSQL (standalone tenants like 'admin'). Returns None if not found
    — the frontend renders "Tenant N" as fallback.
    """
    rows = await execute_query(
        "SELECT name FROM auth.tenants WHERE platform_tenant_id = ? AND is_active = 1;",
        (platform_tenant_id,),
    )
    if rows:
        return rows[0]["name"]

    import asyncio as _asyncio
    import psycopg2 as _pg
    import psycopg2.extras as _pgx
    from app.db.connections import _PG_CONN_PARAMS

    def _query() -> list:
        conn = _pg.connect(**_PG_CONN_PARAMS)
        try:
            cur = conn.cursor(cursor_factory=_pgx.RealDictCursor)
            cur.execute(
                "SELECT name FROM auth.tenants "
                "WHERE platform_tenant_id = %s AND is_active = TRUE",
                (platform_tenant_id,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    try:
        pg_rows = await _asyncio.to_thread(_query)
    except Exception:
        return None
    return pg_rows[0]["name"] if pg_rows else None


async def get_superadmin_by_email(email: str) -> User | None:
    """Find a superadmin user by email in PostgreSQL (tenant_id IS NULL).

    Superadmins are stored in asistente-ia (PostgreSQL), not SQL Server.
    """
    import asyncio
    import psycopg2
    import psycopg2.extras
    from app.db.connections import _PG_CONN_PARAMS

    def _query() -> list:
        conn = psycopg2.connect(**_PG_CONN_PARAMS)
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "SELECT * FROM auth.users "
                "WHERE email = %s AND role = 'superadmin' "
                "AND is_active = TRUE AND tenant_id IS NULL",
                (email.lower().strip(),),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    rows = await asyncio.to_thread(_query)
    if not rows:
        return None
    r = rows[0]
    return User(
        id=r["id"],
        tenant_id=0,            # superadmin has no tenant
        email=r["email"],
        password_hash=r["password_hash"],
        role=r["role"],
        full_name=r.get("full_name"),
        is_active=bool(r["is_active"]),
        created_at=r["created_at"],
        last_login_at=r.get("last_login"),
    )


async def get_user_by_email(tenant_id: int, email: str) -> User | None:
    rows = await execute_query(
        """SELECT * FROM auth.users
           WHERE tenant_id = ? AND email = ? AND is_active = 1;""",
        (tenant_id, email.lower().strip()),
    )
    if rows:
        return _row_to_user(rows[0])
    # Fall back to PostgreSQL: standalone-product users are stored there
    return await _get_user_by_email_pg(email)


async def _get_user_by_email_pg(email: str) -> User | None:
    """Search for user in PostgreSQL auth.users by email (standalone product)."""
    import asyncio as _asyncio
    import psycopg2 as _pg
    import psycopg2.extras as _pgx
    from app.db.connections import _PG_CONN_PARAMS

    def _query() -> list:
        conn = _pg.connect(**_PG_CONN_PARAMS)
        try:
            cur = conn.cursor(cursor_factory=_pgx.RealDictCursor)
            cur.execute(
                "SELECT * FROM auth.users "
                "WHERE email = %s AND is_active = TRUE "
                "AND role != 'superadmin'",  # superadmin handled separately
                (email.lower().strip(),),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    rows = await _asyncio.to_thread(_query)
    if not rows:
        return None
    r = rows[0]
    return User(
        id=r["id"],
        tenant_id=r.get("tenant_id") or 0,
        email=r["email"],
        password_hash=r["password_hash"],
        role=r["role"],
        full_name=r.get("full_name"),
        is_active=bool(r["is_active"]),
        created_at=r["created_at"],
        last_login_at=r.get("last_login"),
    )


def _looks_like_int(s: str) -> bool:
    """True if s is a small integer (PG BIGSERIAL id), not a UUID."""
    try:
        int(s)
        return True
    except (ValueError, TypeError):
        return False


async def get_user_by_id(user_id: str) -> User | None:
    # Integer IDs belong to PostgreSQL (superadmin); UUIDs belong to SQL Server
    if _looks_like_int(user_id):
        return await _get_user_by_id_pg(user_id)
    rows = await execute_query(
        "SELECT * FROM auth.users WHERE id = ? AND is_active = 1;",
        (user_id,),
    )
    return _row_to_user(rows[0]) if rows else None


async def _get_user_by_id_pg(user_id: str) -> User | None:
    """Fetch user from PostgreSQL by integer id (used for superadmin)."""
    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        return None

    import asyncio as _asyncio
    import psycopg2 as _pg
    import psycopg2.extras as _pgx
    from app.db.connections import _PG_CONN_PARAMS

    def _query() -> list:
        conn = _pg.connect(**_PG_CONN_PARAMS)
        try:
            cur = conn.cursor(cursor_factory=_pgx.RealDictCursor)
            cur.execute(
                "SELECT * FROM auth.users WHERE id = %s AND is_active = TRUE",
                (uid,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    rows = await _asyncio.to_thread(_query)
    if not rows:
        return None
    r = rows[0]
    return User(
        id=r["id"],
        tenant_id=r.get("tenant_id") or 0,
        email=r["email"],
        password_hash=r["password_hash"],
        role=r["role"],
        full_name=r.get("full_name"),
        is_active=bool(r["is_active"]),
        created_at=r["created_at"],
        last_login_at=r.get("last_login"),
    )


async def create_user(
    tenant_id: int,
    email: str,
    password_hash: str,
    role: str,
    full_name: str | None = None,
) -> User:
    rows = await execute_query(
        """INSERT INTO auth.users (tenant_id, email, password_hash, role, full_name)
           OUTPUT INSERTED.*
           VALUES (?, ?, ?, ?, ?);""",
        (tenant_id, email.lower().strip(), password_hash, role, full_name),
    )
    return _row_to_user(rows[0])


async def _pg_execute(sql: str, params: tuple) -> None:
    """Run a write query against PostgreSQL (for superadmin operations)."""
    import asyncio as _asyncio
    import psycopg2 as _pg
    from app.db.connections import _PG_CONN_PARAMS

    def _run() -> None:
        conn = _pg.connect(**_PG_CONN_PARAMS)
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    await _asyncio.to_thread(_run)


async def update_last_login(user_id: str) -> None:
    if _looks_like_int(user_id):
        await update_last_login_pg(user_id)
        return
    await execute_query(
        "UPDATE auth.users SET last_login_at = GETUTCDATE() WHERE id = ?;",
        (user_id,),
    )


async def update_last_login_pg(user_id: str) -> None:
    """Update last_login for PostgreSQL users (superadmin)."""
    await _pg_execute(
        "UPDATE auth.users SET last_login = NOW() WHERE id = %s",
        (int(user_id),),
    )


async def save_refresh_token(
    user_id: str,
    token_hash: str,
    expires_at: datetime,
) -> None:
    await execute_query(
        """INSERT INTO auth.refresh_tokens (user_id, token_hash, expires_at)
           VALUES (?, ?, ?);""",
        (user_id, token_hash, expires_at),
    )


async def save_refresh_token_pg(
    user_id: str,
    token_hash: str,
    expires_at: datetime,
) -> None:
    """Store refresh token for PostgreSQL users (superadmin)."""
    await _pg_execute(
        "INSERT INTO auth.refresh_tokens (user_id, token_hash, expires_at) "
        "VALUES (%s, %s, %s) ON CONFLICT (token_hash) DO NOTHING",
        (int(user_id), token_hash, expires_at),
    )


async def revoke_refresh_token(token_hash: str) -> None:
    # Try SQL Server first; if not found (admin tokens live in PG), try PG
    await execute_query(
        """UPDATE auth.refresh_tokens
           SET revoked_at = GETUTCDATE()
           WHERE token_hash = ? AND revoked_at IS NULL;""",
        (token_hash,),
    )
    # Also revoke in PostgreSQL (superadmin / PG-native users)
    await _pg_execute(
        "UPDATE auth.refresh_tokens SET revoked = TRUE "
        "WHERE token_hash = %s AND revoked = FALSE",
        (token_hash,),
    )


async def _get_valid_refresh_token_pg(token_hash: str) -> RefreshToken | None:
    """Look up a valid refresh token in PostgreSQL (for PG-native users).

    user_id is stored as the string representation of the integer PG id
    so that get_user_by_id(str(token.user_id)) → _looks_like_int → PG lookup.
    """
    import asyncio as _asyncio
    import psycopg2 as _pg
    import psycopg2.extras as _pgx
    from app.db.connections import _PG_CONN_PARAMS
    from datetime import datetime as _dt

    def _query() -> list:
        conn = _pg.connect(**_PG_CONN_PARAMS)
        try:
            cur = conn.cursor(cursor_factory=_pgx.RealDictCursor)
            cur.execute(
                "SELECT * FROM auth.refresh_tokens "
                "WHERE token_hash = %s AND revoked = FALSE AND expires_at > NOW()",
                (token_hash,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    rows = await _asyncio.to_thread(_query)
    if not rows:
        return None
    row = rows[0]
    # user_id is stored as integer string ("1") so that:
    # str(stored.user_id) → "1" → _looks_like_int → _get_user_by_id_pg
    return RefreshToken(
        id=UUID("00000000-0000-0000-0000-000000000000"),
        user_id=str(row["user_id"]),          # "1", "2", ... ← key fix
        token_hash=row["token_hash"],
        expires_at=row["expires_at"],
        revoked_at=None,
        created_at=row.get("created_at", _dt.now()),
    )


async def get_valid_refresh_token(token_hash: str) -> RefreshToken | None:
    rows = await execute_query(
        """SELECT * FROM auth.refresh_tokens
           WHERE token_hash = ?
             AND revoked_at IS NULL
             AND expires_at > GETUTCDATE();""",
        (token_hash,),
    )
    if not rows:
        # Not in SQL Server — try PostgreSQL (superadmin / PG-native users)
        return await _get_valid_refresh_token_pg(token_hash)
    if not rows:
        return None
    row = rows[0]
    uid = row["user_id"]
    rid = row["id"]
    return RefreshToken(
        id=UUID(str(rid)) if not isinstance(rid, UUID) else rid,
        user_id=UUID(str(uid)) if not isinstance(uid, UUID) else uid,
        token_hash=row["token_hash"],
        expires_at=row["expires_at"],
        revoked_at=row.get("revoked_at"),
        created_at=row["created_at"],
    )


async def revoke_all_user_refresh_tokens(user_id: str) -> None:
    # PG-native users (integer IDs) only have tokens in PostgreSQL — skip SQL Server
    # to avoid UNIQUEIDENTIFIER cast error on user_id = "5".
    if not _looks_like_int(user_id):
        await execute_query(
            """UPDATE auth.refresh_tokens
               SET revoked_at = GETUTCDATE()
               WHERE user_id = ? AND revoked_at IS NULL;""",
            (user_id,),
        )
    if _looks_like_int(user_id):
        await _pg_execute(
            "UPDATE auth.refresh_tokens SET revoked = TRUE "
            "WHERE user_id = %s AND revoked = FALSE",
            (int(user_id),),
        )
