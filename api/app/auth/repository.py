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
    return _row_to_tenant(rows[0]) if rows else None


async def get_tenant_by_id(tenant_id: int) -> Tenant | None:
    rows = await execute_query(
        "SELECT * FROM auth.tenants WHERE id = ? AND is_active = 1;",
        (tenant_id,),
    )
    return _row_to_tenant(rows[0]) if rows else None


async def get_user_by_email(tenant_id: int, email: str) -> User | None:
    rows = await execute_query(
        """SELECT * FROM auth.users
           WHERE tenant_id = ? AND email = ? AND is_active = 1;""",
        (tenant_id, email.lower().strip()),
    )
    return _row_to_user(rows[0]) if rows else None


async def get_user_by_id(user_id: str) -> User | None:
    rows = await execute_query(
        "SELECT * FROM auth.users WHERE id = ? AND is_active = 1;",
        (user_id,),
    )
    return _row_to_user(rows[0]) if rows else None


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


async def update_last_login(user_id: str) -> None:
    await execute_query(
        "UPDATE auth.users SET last_login_at = GETUTCDATE() WHERE id = ?;",
        (user_id,),
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


async def revoke_refresh_token(token_hash: str) -> None:
    await execute_query(
        """UPDATE auth.refresh_tokens
           SET revoked_at = GETUTCDATE()
           WHERE token_hash = ? AND revoked_at IS NULL;""",
        (token_hash,),
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
    await execute_query(
        """UPDATE auth.refresh_tokens
           SET revoked_at = GETUTCDATE()
           WHERE user_id = ? AND revoked_at IS NULL;""",
        (user_id,),
    )
