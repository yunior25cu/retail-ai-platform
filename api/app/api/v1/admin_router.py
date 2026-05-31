"""Admin endpoints — /api/v1/admin/*

All endpoints require role='superadmin' (JWT).
password_hash is NEVER returned in any response.
Every administrative action is recorded in auth.admin_audit_log.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.dependencies import require_role
from app.auth.service import hash_password
from app.db.connections import _PG_CONN_PARAMS

router = APIRouter(prefix="/admin", tags=["admin"])

_superadmin = require_role("superadmin")

# Roles allowed for tenant users (superadmin cannot be created via this endpoint)
_VALID_ROLES = {"produccion", "compras", "direccion", "admin"}

# DDL template for gold_t{id} schema — same tables as gold_t24
_GOLD_SCHEMA_DDL = """
CREATE SCHEMA IF NOT EXISTS gold_t{tid};

CREATE TABLE IF NOT EXISTS gold_t{tid}.dim_sku (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       INT           NOT NULL DEFAULT {tid},
    sku_code        VARCHAR(50)   NOT NULL,
    sku_name        VARCHAR(200)  NOT NULL,
    family_code     VARCHAR(10)   NULL,
    is_finished     BOOLEAN       NULL,
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    liters_per_unit NUMERIC(10,4) NULL,
    liters_source   VARCHAR(20)   NULL,
    stock_min_units NUMERIC(18,4) NULL,
    UNIQUE(tenant_id, sku_code)
);
CREATE TABLE IF NOT EXISTS gold_t{tid}.dim_reactor (
    id              SERIAL PRIMARY KEY,
    tenant_id       INT           NOT NULL DEFAULT {tid},
    reactor_code    VARCHAR(20)   NOT NULL,
    reactor_name    VARCHAR(100)  NOT NULL,
    capacity_liters NUMERIC(12,2) NULL,
    reactor_type    VARCHAR(20)   NOT NULL,
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    notes           VARCHAR(500)  NULL,
    UNIQUE(tenant_id, reactor_code)
);
CREATE TABLE IF NOT EXISTS gold_t{tid}.dim_recipe_granel (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       INT           NOT NULL DEFAULT {tid},
    recipe_id       INT           NOT NULL,
    granel_sku      VARCHAR(50)   NOT NULL,
    granel_name     VARCHAR(200)  NOT NULL,
    batch_liters    NUMERIC(12,2) NOT NULL,
    recipe_line     INT           NOT NULL,
    component_sku   VARCHAR(50)   NOT NULL,
    component_name  VARCHAR(200)  NOT NULL,
    component_type  VARCHAR(30)   NOT NULL,
    qty_per_batch   NUMERIC(18,6) NOT NULL,
    qty_per_liter   NUMERIC(18,8) NOT NULL,
    unit_of_measure VARCHAR(20)   NOT NULL,
    cost_per_batch  NUMERIC(18,4) NULL,
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    UNIQUE(tenant_id, recipe_id, recipe_line)
);
CREATE TABLE IF NOT EXISTS gold_t{tid}.dim_recipe_product (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       INT           NOT NULL DEFAULT {tid},
    product_sku     VARCHAR(50)   NOT NULL,
    product_name    VARCHAR(200)  NOT NULL,
    granel_sku      VARCHAR(50)   NOT NULL,
    liters_per_unit NUMERIC(10,4) NOT NULL,
    component_sku   VARCHAR(50)   NOT NULL,
    component_name  VARCHAR(200)  NOT NULL,
    component_type  VARCHAR(30)   NOT NULL,
    qty_per_unit    NUMERIC(18,6) NOT NULL DEFAULT 1,
    unit_of_measure VARCHAR(20)   NOT NULL DEFAULT 'Uni',
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    UNIQUE(tenant_id, product_sku, component_sku)
);
CREATE TABLE IF NOT EXISTS gold_t{tid}.fact_component_stock (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       INT           NOT NULL DEFAULT {tid},
    component_sku   VARCHAR(50)   NOT NULL,
    component_name  VARCHAR(200)  NOT NULL,
    component_type  VARCHAR(30)   NOT NULL,
    store_code      CHAR(1)       NOT NULL DEFAULT 'F',
    stock_units     NUMERIC(18,4) NOT NULL,
    stock_kg        NUMERIC(18,4) NULL,
    unit_of_measure VARCHAR(20)   NOT NULL,
    units_on_order  NUMERIC(18,4) NOT NULL DEFAULT 0,
    stock_effective NUMERIC(18,4) NOT NULL DEFAULT 0,
    snapshot_date   DATE          NOT NULL,
    is_critical     BOOLEAN       NOT NULL DEFAULT FALSE,
    is_low          BOOLEAN       NOT NULL DEFAULT FALSE,
    stock_min       NUMERIC(18,4) NULL,
    UNIQUE(tenant_id, component_sku, store_code, snapshot_date)
);
CREATE TABLE IF NOT EXISTS gold_t{tid}.fact_component_stock_override (
    tenant_id     INT           NOT NULL DEFAULT {tid},
    component_sku VARCHAR(50)   NOT NULL,
    stock_real    NUMERIC(18,4) NOT NULL,
    source        VARCHAR(100)  NOT NULL,
    override_date DATE          NOT NULL,
    notes         VARCHAR(500)  NULL,
    updated_by    VARCHAR(100)  NULL,
    updated_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY(tenant_id, component_sku)
);
CREATE TABLE IF NOT EXISTS gold_t{tid}.fact_demand_forecast (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       INT           NOT NULL DEFAULT {tid},
    sku_code        VARCHAR(50)   NOT NULL,
    forecast_date   DATE          NOT NULL,
    iso_year_week   CHAR(8)       NOT NULL,
    predicted_units INT           NOT NULL CHECK(predicted_units >= 0),
    model_run_date  DATE          NOT NULL,
    model_version   VARCHAR(20)   NOT NULL DEFAULT '1.0',
    horizon_days    INT           NOT NULL DEFAULT 60,
    yhat_lower      INT           NULL,
    yhat_upper      INT           NULL,
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(tenant_id, sku_code, forecast_date, model_run_date)
);
CREATE TABLE IF NOT EXISTS gold_t{tid}.fact_production_plan_weekly (
    id                     BIGSERIAL PRIMARY KEY,
    tenant_id              INT           NOT NULL DEFAULT {tid},
    sku_code               VARCHAR(50)   NOT NULL,
    iso_year_week          CHAR(8)       NOT NULL,
    predicted_units_week   INT           NOT NULL DEFAULT 0,
    predicted_units_30d    INT           NOT NULL DEFAULT 0,
    stock_current          INT           NOT NULL DEFAULT 0,
    stock_pending_billing  INT           NOT NULL DEFAULT 0,
    stock_final            INT           NOT NULL DEFAULT 0,
    units_to_produce       INT           NOT NULL DEFAULT 0,
    liters_to_produce      NUMERIC(12,2) NULL,
    days_of_coverage       NUMERIC(6,1)  NULL,
    is_critical            BOOLEAN       NOT NULL DEFAULT FALSE,
    has_component_shortage BOOLEAN       NOT NULL DEFAULT FALSE,
    blocking_components    VARCHAR(500)  NULL,
    refreshed_at           TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(tenant_id, sku_code, iso_year_week)
);
CREATE TABLE IF NOT EXISTS gold_t{tid}.fact_production_orders (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       INT           NOT NULL DEFAULT {tid},
    production_date DATE          NOT NULL,
    iso_year_week   CHAR(8)       NOT NULL,
    sku_code        VARCHAR(50)   NOT NULL,
    nro_doc         VARCHAR(20)   NOT NULL,
    units_produced  NUMERIC(18,4) NOT NULL,
    liters_produced NUMERIC(18,4) NULL,
    status          VARCHAR(20)   NOT NULL DEFAULT 'ejecutado',
    operator        VARCHAR(100)  NULL,
    UNIQUE(tenant_id, nro_doc, sku_code)
);
CREATE TABLE IF NOT EXISTS gold_t{tid}.fact_purchase_orders (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       INT           NOT NULL DEFAULT {tid},
    order_date      DATE          NOT NULL,
    component_sku   VARCHAR(50)   NOT NULL,
    component_name  VARCHAR(200)  NOT NULL,
    nro_doc         VARCHAR(20)   NOT NULL,
    units_ordered   NUMERIC(18,4) NOT NULL,
    units_received  NUMERIC(18,4) NOT NULL DEFAULT 0,
    units_pending   NUMERIC(18,4) NOT NULL,
    status          VARCHAR(20)   NOT NULL,
    total_cost      NUMERIC(18,4) NULL,
    UNIQUE(tenant_id, nro_doc, component_sku)
);
"""


# ── helpers ───────────────────────────────────────────────────────────────────

def _pg() -> psycopg2.extensions.connection:
    return psycopg2.connect(**_PG_CONN_PARAMS)


def _resolve_tenant(cur: Any, tenant_id: int) -> int | None:
    """Return the canonical PG auth.tenants.id.

    Accepts both the internal PG id AND platform_tenant_id so that
    callers can pass either (e.g. platform_tenant_id=24 for Prolimpio
    whose PG id is 1).
    """
    cur.execute(
        "SELECT id FROM auth.tenants "
        "WHERE (id = %s OR platform_tenant_id = %s) AND is_active = TRUE "
        "LIMIT 1",
        (tenant_id, tenant_id),
    )
    row = cur.fetchone()
    return row["id"] if row else None


def _audit(
    conn: Any,
    admin_id: int,
    action: str,
    target_type: str,
    target_id: str | None = None,
    detail: dict | None = None,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO auth.admin_audit_log
           (admin_id, action, target_type, target_id, detail)
           VALUES (%s, %s, %s, %s, %s)""",
        (admin_id, action, target_type, target_id,
         json.dumps(detail, default=str) if detail else None),
    )


def _get_admin_id(user: Any) -> int:
    return int(user.id) if hasattr(user, "id") else 0


# ── Schemas ───────────────────────────────────────────────────────────────────

class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1)
    slug: str = Field(..., min_length=1, pattern=r"^[a-z0-9-]+$")
    vertical: str = Field(..., pattern=r"^(retail|produccion)$")
    platform_tenant_id: int | None = None


class TenantOut(BaseModel):
    id: int
    name: str
    slug: str
    vertical: str
    is_active: bool
    user_count: int
    platform_tenant_id: int | None
    created_at: datetime


class UserCreate(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)
    role: str


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    is_active: bool
    last_login: datetime | None
    created_at: datetime


class UserPatch(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8)


class ConfigOut(BaseModel):
    tenant_id: int
    config: dict[str, str]


class ConfigPatch(BaseModel):
    vertical: str | None = None
    memory: str | None = None
    rate_limit: str | None = None
    suggestions: str | None = None


# ── Tenant endpoints ──────────────────────────────────────────────────────────

@router.post("/tenants", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: TenantCreate,
    admin=Depends(_superadmin),
) -> TenantOut:
    conn = _pg()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1. Check slug uniqueness
        cur.execute("SELECT id FROM auth.tenants WHERE slug = %s", (payload.slug,))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail=f"Slug '{payload.slug}' ya existe")

        # 2. Insert tenant
        cur.execute(
            """INSERT INTO auth.tenants (name, slug, vertical, platform_tenant_id)
               VALUES (%s, %s, %s, %s) RETURNING id, name, slug, vertical,
               is_active, platform_tenant_id, created_at""",
            (payload.name, payload.slug, payload.vertical, payload.platform_tenant_id),
        )
        tenant = dict(cur.fetchone())

        # 3. Default config
        configs = [
            (tenant["id"], "vertical",    payload.vertical),
            (tenant["id"], "memory",      "3"),
            (tenant["id"], "rate_limit",  "100"),
            (tenant["id"], "suggestions", "true"),
        ]
        psycopg2.extras.execute_batch(
            cur,
            """INSERT INTO config.tenant_config (tenant_id, config_key, config_value)
               VALUES (%s, %s, %s) ON CONFLICT (tenant_id, config_key) DO NOTHING""",
            configs,
        )

        # 4. If produccion, create gold schema
        if payload.vertical == "produccion":
            tid = tenant["id"]
            ddl = _GOLD_SCHEMA_DDL.format(tid=tid)
            cur.execute(ddl)

        # 5. Audit
        _audit(conn, _get_admin_id(admin), "create_tenant", "tenant",
               str(tenant["id"]), {"name": payload.name, "vertical": payload.vertical})

        conn.commit()
        tenant["user_count"] = 0
        return TenantOut(**tenant)
    finally:
        conn.close()


@router.get("/tenants", response_model=list[TenantOut])
async def list_tenants(admin=Depends(_superadmin)) -> list[TenantOut]:
    conn = _pg()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT t.id, t.name, t.slug, t.vertical, t.is_active,
                   t.platform_tenant_id, t.created_at,
                   COUNT(u.id) AS user_count
            FROM auth.tenants t
            LEFT JOIN auth.users u ON u.tenant_id = t.id AND u.is_active = TRUE
            GROUP BY t.id ORDER BY t.created_at DESC
        """)
        return [TenantOut(**r) for r in cur.fetchall()]
    finally:
        conn.close()


# ── User endpoints ────────────────────────────────────────────────────────────

@router.post(
    "/tenants/{tenant_id}/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    tenant_id: int,
    payload: UserCreate,
    admin=Depends(_superadmin),
) -> UserOut:
    if payload.role not in _VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Role invalido. Permitidos: {sorted(_VALID_ROLES)}",
        )
    conn = _pg()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Resolve: accept both PG id and platform_tenant_id
        pg_tid = _resolve_tenant(cur, tenant_id)
        if not pg_tid:
            raise HTTPException(status_code=404, detail="Tenant no encontrado")
        tenant_id = pg_tid  # use canonical PG id for all operations

        # Check email uniqueness
        cur.execute("SELECT id FROM auth.users WHERE email = %s", (payload.email,))
        if cur.fetchone():
            raise HTTPException(status_code=400,
                                detail=f"Email '{payload.email}' ya existe")

        pw_hash = hash_password(payload.password)
        cur.execute(
            """INSERT INTO auth.users (tenant_id, email, password_hash, role)
               VALUES (%s, %s, %s, %s)
               RETURNING id, email, role, is_active, last_login, created_at""",
            (tenant_id, payload.email.lower().strip(), pw_hash, payload.role),
        )
        user = dict(cur.fetchone())

        _audit(conn, _get_admin_id(admin), "create_user", "user",
               str(user["id"]),
               {"email": payload.email, "role": payload.role, "tenant_id": tenant_id})
        conn.commit()
        return UserOut(**user)
    finally:
        conn.close()


@router.get("/tenants/{tenant_id}/users", response_model=list[UserOut])
async def list_users(
    tenant_id: int,
    admin=Depends(_superadmin),
) -> list[UserOut]:
    conn = _pg()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        pg_tid = _resolve_tenant(cur, tenant_id) or tenant_id
        cur.execute(
            """SELECT id, email, role, is_active, last_login, created_at
               FROM auth.users WHERE tenant_id = %s ORDER BY created_at DESC""",
            (pg_tid,),
        )
        return [UserOut(**r) for r in cur.fetchall()]
    finally:
        conn.close()


@router.patch("/users/{user_id}", response_model=UserOut)
async def patch_user(
    user_id: int,
    payload: UserPatch,
    admin=Depends(_superadmin),
) -> UserOut:
    conn = _pg()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            "SELECT id, email, role, is_active FROM auth.users WHERE id = %s",
            (user_id,),
        )
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        if existing["role"] == "superadmin":
            raise HTTPException(status_code=403,
                                detail="No se puede modificar un superadmin desde este endpoint")

        changes: dict[str, Any] = {}
        parts, vals = [], []

        if payload.role is not None and payload.role != existing["role"]:
            if payload.role not in _VALID_ROLES:
                raise HTTPException(status_code=400, detail="Role invalido")
            parts.append("role = %s"); vals.append(payload.role)
            changes["role"] = {"antes": existing["role"], "despues": payload.role}

        if payload.is_active is not None and payload.is_active != existing["is_active"]:
            parts.append("is_active = %s"); vals.append(payload.is_active)
            changes["is_active"] = {"antes": existing["is_active"],
                                     "despues": payload.is_active}
            if not payload.is_active:
                cur.execute(
                    "UPDATE auth.refresh_tokens SET revoked = TRUE "
                    "WHERE user_id = %s AND revoked = FALSE",
                    (user_id,),
                )

        if payload.password is not None:
            parts.append("password_hash = %s"); vals.append(hash_password(payload.password))
            changes["password"] = {"antes": "***", "despues": "***"}

        if parts:
            vals.append(user_id)
            cur.execute(
                f"UPDATE auth.users SET {', '.join(parts)} WHERE id = %s",
                tuple(vals),
            )
            _audit(conn, _get_admin_id(admin), "update_user", "user",
                   str(user_id), changes)

        conn.commit()

        cur.execute(
            "SELECT id, email, role, is_active, last_login, created_at "
            "FROM auth.users WHERE id = %s",
            (user_id,),
        )
        return UserOut(**cur.fetchone())
    finally:
        conn.close()


# ── Config endpoints ──────────────────────────────────────────────────────────

@router.get("/tenants/{tenant_id}/config", response_model=ConfigOut)
async def get_config(
    tenant_id: int,
    admin=Depends(_superadmin),
) -> ConfigOut:
    conn = _pg()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        pg_tid = _resolve_tenant(cur, tenant_id) or tenant_id
        cur.execute(
            "SELECT config_key, config_value FROM config.tenant_config "
            "WHERE tenant_id = %s",
            (pg_tid,),
        )
        cfg = {r["config_key"]: r["config_value"] for r in cur.fetchall()}
        return ConfigOut(tenant_id=pg_tid, config=cfg)
    finally:
        conn.close()


@router.patch("/tenants/{tenant_id}/config", response_model=ConfigOut)
async def patch_config(
    tenant_id: int,
    payload: ConfigPatch,
    admin=Depends(_superadmin),
) -> ConfigOut:
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Sin campos a actualizar")

    if "vertical" in updates and updates["vertical"] not in ("retail", "produccion"):
        raise HTTPException(status_code=400,
                            detail="vertical debe ser 'retail' o 'produccion'")

    conn = _pg()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        pg_tid = _resolve_tenant(cur, tenant_id) or tenant_id
        for key, val in updates.items():
            cur.execute(
                """INSERT INTO config.tenant_config (tenant_id, config_key, config_value)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (tenant_id, config_key) DO UPDATE
                   SET config_value = EXCLUDED.config_value,
                       updated_at   = NOW()""",
                (pg_tid, key, val),
            )
        _audit(conn, _get_admin_id(admin), "update_config", "config",
               str(pg_tid), updates)
        conn.commit()

        cur.execute(
            "SELECT config_key, config_value FROM config.tenant_config "
            "WHERE tenant_id = %s",
            (pg_tid,),
        )
        cfg = {r["config_key"]: r["config_value"] for r in cur.fetchall()}
        return ConfigOut(tenant_id=pg_tid, config=cfg)
    finally:
        conn.close()


# ── Audit endpoint ────────────────────────────────────────────────────────────

@router.get("/tenants/{tenant_id}/audit")
async def get_audit(
    tenant_id: int,
    admin=Depends(_superadmin),
) -> list[dict]:
    conn = _pg()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        pg_tid = _resolve_tenant(cur, tenant_id) or tenant_id
        cur.execute(
            """SELECT a.action, a.target_type, a.target_id,
                      a.detail, a.created_at
               FROM auth.admin_audit_log a
               WHERE a.target_id IN (
                   SELECT CAST(id AS VARCHAR) FROM auth.users
                   WHERE tenant_id = %s
                   UNION ALL SELECT CAST(%s AS VARCHAR)
               )
               ORDER BY a.created_at DESC LIMIT 100""",
            (pg_tid, pg_tid),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
