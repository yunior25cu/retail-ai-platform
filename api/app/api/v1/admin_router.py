"""Admin endpoints — /api/v1/admin/*

Protected by require_role('super_admin').
CRUD for auth.tenants, auth.users, and verticales listing.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import require_role
from app.auth import repository as repo
from app.auth.service import hash_password
from app.db.connection import execute_query

router = APIRouter(prefix="/admin", tags=["admin"])

_super_admin = require_role("super_admin")


# ── Schemas ──────────────────────────────────────────────────────────────────

class TenantOut(BaseModel):
    id: int
    name: str
    slug: str
    vertical: str
    plan: str
    is_active: bool
    created_at: datetime
    platform_tenant_id: int | None

class TenantCreate(BaseModel):
    name: str
    slug: str
    vertical: str
    plan: str = "starter"
    platform_tenant_id: int | None = None

class TenantPatch(BaseModel):
    name: str | None = None
    vertical: str | None = None
    plan: str | None = None
    is_active: bool | None = None
    platform_tenant_id: int | None = None

class UserOut(BaseModel):
    id: str
    email: str
    role: str
    full_name: str | None
    tenant_id: int
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None

class UserInvite(BaseModel):
    email: str
    password: str
    role: str
    full_name: str | None = None
    tenant_id: int

class UserPatch(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    full_name: str | None = None

class VerticalOut(BaseModel):
    name: str
    label: str
    tool_count: int
    tenant_count: int


# ── Tenants ───────────────────────────────────────────────────────────────────

@router.get("/tenants", response_model=list[TenantOut])
async def list_tenants(_user=Depends(_super_admin)) -> list[TenantOut]:
    rows = await execute_query(
        "SELECT * FROM auth.tenants ORDER BY created_at DESC;", ()
    )
    return [
        TenantOut(
            id=r["id"], name=r["name"], slug=r["slug"],
            vertical=r["vertical"], plan=r.get("tenant_plan", "starter"),
            is_active=bool(r["is_active"]), created_at=r["created_at"],
            platform_tenant_id=r.get("platform_tenant_id"),
        )
        for r in rows
    ]


@router.post("/tenants", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: TenantCreate, _user=Depends(_super_admin)
) -> TenantOut:
    rows = await execute_query(
        """INSERT INTO auth.tenants (name, slug, vertical, tenant_plan, platform_tenant_id)
           OUTPUT INSERTED.*
           VALUES (?, ?, ?, ?, ?);""",
        (payload.name, payload.slug, payload.vertical, payload.plan, payload.platform_tenant_id),
    )
    r = rows[0]
    return TenantOut(
        id=r["id"], name=r["name"], slug=r["slug"],
        vertical=r["vertical"], plan=r.get("tenant_plan", "starter"),
        is_active=bool(r["is_active"]), created_at=r["created_at"],
        platform_tenant_id=r.get("platform_tenant_id"),
    )


@router.patch("/tenants/{tenant_id}", response_model=TenantOut)
async def patch_tenant(
    tenant_id: int, payload: TenantPatch, _user=Depends(_super_admin)
) -> TenantOut:
    parts, vals = [], []
    if payload.name       is not None: parts.append("name=?");         vals.append(payload.name)
    if payload.vertical   is not None: parts.append("vertical=?");     vals.append(payload.vertical)
    if payload.plan       is not None: parts.append("tenant_plan=?");  vals.append(payload.plan)
    if payload.is_active  is not None: parts.append("is_active=?");    vals.append(int(payload.is_active))
    if payload.platform_tenant_id is not None:
        parts.append("platform_tenant_id=?"); vals.append(payload.platform_tenant_id)
    if not parts:
        raise HTTPException(status_code=400, detail="No fields to update")
    vals.append(tenant_id)
    await execute_query(f"UPDATE auth.tenants SET {', '.join(parts)} WHERE id=?;", tuple(vals))
    rows = await execute_query("SELECT * FROM auth.tenants WHERE id=?;", (tenant_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Tenant not found")
    r = rows[0]
    return TenantOut(
        id=r["id"], name=r["name"], slug=r["slug"],
        vertical=r["vertical"], plan=r.get("tenant_plan", "starter"),
        is_active=bool(r["is_active"]), created_at=r["created_at"],
        platform_tenant_id=r.get("platform_tenant_id"),
    )


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserOut])
async def list_users(
    tenant_id: int | None = None, _user=Depends(_super_admin)
) -> list[UserOut]:
    if tenant_id:
        rows = await execute_query(
            "SELECT * FROM auth.users WHERE tenant_id=? ORDER BY created_at DESC;",
            (tenant_id,),
        )
    else:
        rows = await execute_query(
            "SELECT * FROM auth.users ORDER BY created_at DESC;", ()
        )
    return [
        UserOut(
            id=str(r["id"]), email=r["email"], role=r["role"],
            full_name=r.get("full_name"), tenant_id=r["tenant_id"],
            is_active=bool(r["is_active"]), created_at=r["created_at"],
            last_login_at=r.get("last_login_at"),
        )
        for r in rows
    ]


@router.post("/users/invite", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def invite_user(
    payload: UserInvite, _user=Depends(_super_admin)
) -> UserOut:
    pw_hash = hash_password(payload.password)
    user = await repo.create_user(
        tenant_id=payload.tenant_id,
        email=payload.email,
        password_hash=pw_hash,
        role=payload.role,
        full_name=payload.full_name,
    )
    return UserOut(
        id=str(user.id), email=user.email, role=user.role,
        full_name=user.full_name, tenant_id=user.tenant_id,
        is_active=user.is_active, created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


@router.patch("/users/{user_id}", response_model=UserOut)
async def patch_user(
    user_id: str, payload: UserPatch, _user=Depends(_super_admin)
) -> UserOut:
    parts, vals = [], []
    if payload.role      is not None: parts.append("role=?");      vals.append(payload.role)
    if payload.is_active is not None: parts.append("is_active=?"); vals.append(int(payload.is_active))
    if payload.full_name is not None: parts.append("full_name=?"); vals.append(payload.full_name)
    if not parts:
        raise HTTPException(status_code=400, detail="No fields to update")
    vals.append(user_id)
    await execute_query(f"UPDATE auth.users SET {', '.join(parts)} WHERE id=?;", tuple(vals))
    user = await repo.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut(
        id=str(user.id), email=user.email, role=user.role,
        full_name=user.full_name, tenant_id=user.tenant_id,
        is_active=user.is_active, created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


# ── Verticales (read-only) ────────────────────────────────────────────────────

@router.get("/verticals", response_model=list[VerticalOut])
async def list_verticals(_user=Depends(_super_admin)) -> list[VerticalOut]:
    rows = await execute_query(
        """SELECT vertical, COUNT(*) AS tenant_count
           FROM auth.tenants GROUP BY vertical;""", ()
    )
    counts = {r["vertical"]: r["tenant_count"] for r in rows}

    _TOOL_COUNTS = {"retail": 15, "produccion": 6}
    _LABELS      = {"retail": "Retail / Distribución", "produccion": "Manufactura / Producción"}

    verticals = ["retail", "produccion"]
    return [
        VerticalOut(
            name=v,
            label=_LABELS.get(v, v),
            tool_count=_TOOL_COUNTS.get(v, 0),
            tenant_count=counts.get(v, 0),
        )
        for v in verticals
    ]
