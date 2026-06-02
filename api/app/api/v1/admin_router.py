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


# ---------------------------------------------------------------------------
# /admin/platform_metrics
#
# Cross-tenant AI usage for the AdminPlatformMetrics page.
# Aggregates current-month chats from BOTH engines:
#   - PG: audit.conversation_log (1 row per assistant message = 1 turn)
#   - SS: api_audit.ai_audit_log  (1 row per chat with status=SUCCESS)
# Joins with auth.tenants on platform_tenant_id for display names.
# Super-admin only. Same JSON-tool-parser as /internal/metrics.
# ---------------------------------------------------------------------------

from collections import Counter
from datetime import datetime, timezone


def _current_month_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _aggregate_pg_metrics() -> dict[str, Any]:
    conn = _pg()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """SELECT tenant_id,
                      COUNT(*) AS chats,
                      COALESCE(SUM(cost_usd), 0) AS cost_usd
               FROM audit.conversation_log
               WHERE role = 'assistant'
                 AND DATE_TRUNC('month', created_at) = DATE_TRUNC('month', NOW())
               GROUP BY tenant_id""",
        )
        per_tenant = [dict(r) for r in cur.fetchall()]
        cur.execute(
            """SELECT tools_used FROM audit.conversation_log
               WHERE role = 'assistant'
                 AND tools_used IS NOT NULL
                 AND DATE_TRUNC('month', created_at) = DATE_TRUNC('month', NOW())""",
        )
        tool_rows = [r["tools_used"] for r in cur.fetchall()]
        return {"per_tenant": per_tenant, "tool_rows": tool_rows}
    finally:
        conn.close()


def _aggregate_ss_metrics() -> dict[str, Any]:
    try:
        from app.db.connection import _execute_sync
    except Exception:
        return {"per_tenant": [], "tool_rows": []}
    try:
        per_tenant_rows = _execute_sync(
            """SELECT tenant_id,
                      COUNT(*) AS chats,
                      ISNULL(SUM(CAST(cost_usd AS FLOAT)), 0) AS cost_usd
               FROM api_audit.ai_audit_log
               WHERE timestamp_utc >= DATEFROMPARTS(
                       YEAR(SYSUTCDATETIME()), MONTH(SYSUTCDATETIME()), 1)
                 AND timestamp_utc <  DATEADD(MONTH, 1, DATEFROMPARTS(
                       YEAR(SYSUTCDATETIME()), MONTH(SYSUTCDATETIME()), 1))
                 AND status = 'SUCCESS'
               GROUP BY tenant_id;""",
            None,
        )
        tool_rows_raw = _execute_sync(
            """SELECT tools_invoked FROM api_audit.ai_audit_log
               WHERE timestamp_utc >= DATEFROMPARTS(
                       YEAR(SYSUTCDATETIME()), MONTH(SYSUTCDATETIME()), 1)
                 AND timestamp_utc <  DATEADD(MONTH, 1, DATEFROMPARTS(
                       YEAR(SYSUTCDATETIME()), MONTH(SYSUTCDATETIME()), 1))
                 AND status = 'SUCCESS'
                 AND tools_invoked IS NOT NULL;""",
            None,
        )
    except Exception:
        return {"per_tenant": [], "tool_rows": []}
    return {
        "per_tenant": [
            {"tenant_id": int(r["tenant_id"]),
             "chats": int(r["chats"]),
             "cost_usd": float(r["cost_usd"] or 0)}
            for r in per_tenant_rows
        ],
        "tool_rows": [
            r["tools_invoked"] for r in tool_rows_raw if r.get("tools_invoked")
        ],
    }


def _top_tool_from_rows(rows: list[str]) -> tuple[str, int]:
    counter: Counter[str] = Counter()
    for raw in rows:
        try:
            tools = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(tools, list):
            continue
        for entry in tools:
            if isinstance(entry, str):
                counter[entry] += 1
            elif isinstance(entry, dict):
                name = entry.get("name") or entry.get("tool")
                if isinstance(name, str):
                    counter[name] += 1
    if not counter:
        return "", 0
    return counter.most_common(1)[0]


def _resolve_tenant_names_pg(cur, platform_ids: set[int]) -> dict[int, str]:
    if not platform_ids:
        return {}
    cur.execute(
        "SELECT platform_tenant_id, name FROM auth.tenants "
        "WHERE platform_tenant_id = ANY(%s)",
        (list(platform_ids),),
    )
    return {r["platform_tenant_id"]: r["name"] for r in cur.fetchall()
            if r["platform_tenant_id"] is not None}


def _resolve_tenant_names_ss(platform_ids: set[int]) -> dict[int, str]:
    if not platform_ids:
        return {}
    try:
        from app.db.connection import _execute_sync
        placeholders = ", ".join(["?"] * len(platform_ids))
        rows = _execute_sync(
            f"SELECT platform_tenant_id, name FROM auth.tenants "
            f"WHERE platform_tenant_id IN ({placeholders})",
            tuple(platform_ids),
        )
        return {r["platform_tenant_id"]: r["name"] for r in rows
                if r.get("platform_tenant_id") is not None}
    except Exception:
        return {}


class PlatformTenantRow(BaseModel):
    tenant_id: int
    tenant_name: str
    chats: int
    cost_usd: float


class PlatformMetricsResponse(BaseModel):
    period: str = Field(description="ISO month YYYY-MM (UTC)")
    total_chats: int
    total_cost_usd: float
    active_tenants: int
    top_tool: str
    top_tool_count: int
    by_tenant: list[PlatformTenantRow]


@router.get(
    "/platform_metrics",
    response_model=PlatformMetricsResponse,
    summary="Cross-tenant AI Assistant usage (super-admin only)",
)
async def get_platform_metrics(
    admin=Depends(_superadmin),
) -> PlatformMetricsResponse:
    pg_data = _aggregate_pg_metrics()
    ss_data = _aggregate_ss_metrics()

    merged: dict[int, dict[str, Any]] = {}
    for r in pg_data["per_tenant"] + ss_data["per_tenant"]:
        tid = int(r["tenant_id"])
        bucket = merged.setdefault(tid, {"chats": 0, "cost_usd": 0.0})
        bucket["chats"] += int(r["chats"])
        bucket["cost_usd"] += float(r["cost_usd"] or 0)

    pg_conn = _pg()
    try:
        cur = pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        name_map_pg = _resolve_tenant_names_pg(cur, set(merged.keys()))
    finally:
        pg_conn.close()
    missing = {tid for tid in merged if tid not in name_map_pg}
    name_map_ss = _resolve_tenant_names_ss(missing)
    name_map = {**name_map_ss, **name_map_pg}

    by_tenant_rows = sorted(
        (
            PlatformTenantRow(
                tenant_id=tid,
                tenant_name=name_map.get(tid, f"Tenant {tid}"),
                chats=int(data["chats"]),
                cost_usd=round(float(data["cost_usd"]), 4),
            )
            for tid, data in merged.items()
        ),
        key=lambda r: r.chats,
        reverse=True,
    )

    top_tool_name, top_tool_count = _top_tool_from_rows(
        pg_data["tool_rows"] + ss_data["tool_rows"]
    )

    return PlatformMetricsResponse(
        period=_current_month_iso(),
        total_chats=sum(b["chats"] for b in merged.values()),
        total_cost_usd=round(sum(b["cost_usd"] for b in merged.values()), 4),
        active_tenants=len(merged),
        top_tool=top_tool_name,
        top_tool_count=top_tool_count,
        by_tenant=by_tenant_rows,
    )


# ---------------------------------------------------------------------------
# /admin/logs — cross-tenant audit trail viewer (super-admin only)
#
# Unifies rows from both engines into a single timeline:
#   - PG: audit.conversation_log filtered to role='assistant'
#         (one row per chat turn; user_question is in a separate row).
#   - SS: api_audit.ai_audit_log (one row per chat with user_question in
#         the same row).
#
# Each unified row carries enough info for an admin to triage: when,
# which tenant, who, what role, status, tokens, cost, plus a short
# preview text (user question if available, otherwise the assistant
# response truncated).
#
# Pagination: cap to limit_per_engine each side, merge, sort by
# timestamp DESC, slice. Acceptable for the current scale (~hundreds
# of rows / month / tenant). When that grows we add a unified materialised
# view; not now.
# ---------------------------------------------------------------------------

_LOG_PREVIEW_CHARS = 160
_LOG_DEFAULT_LIMIT = 50
_LOG_MAX_LIMIT = 200
# Per-engine cap to keep memory + sort bounded — adjusted upwards if a real
# log spans many tenants and we miss recent activity from the SS side.
_LOG_PER_ENGINE_CAP = 500


def _truncate(text: str | None, n: int = _LOG_PREVIEW_CHARS) -> str:
    if not text:
        return ""
    flat = " ".join(text.split())
    return flat if len(flat) <= n else flat[:n] + "…"


def _fetch_logs_pg(tenant_id: int | None, status_filter: str | None) -> list[dict[str, Any]]:
    """One row per chat turn (assistant rows). user_question is fetched
    from the user row at sequence-1 (same conversation) — but PG also has
    audit.conversation_message for that. For the admin viewer we settle
    for the assistant message_text as preview (the response) — cheaper
    and good enough to triage."""
    conn = _pg()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        clauses = ["cl.role = 'assistant'"]
        params: list[Any] = []
        if tenant_id is not None:
            clauses.append("cl.tenant_id = %s")
            params.append(tenant_id)
        if status_filter:
            clauses.append("cl.message_type = %s")
            params.append(status_filter)
        where_sql = " AND ".join(clauses)
        params.append(_LOG_PER_ENGINE_CAP)
        cur.execute(
            f"""SELECT cl.created_at,
                       cl.tenant_id,
                       t.name AS tenant_name,
                       cl.user_id,
                       cl.conversation_id,
                       cl.message_type AS status,
                       COALESCE(cl.tokens_input, 0) + COALESCE(cl.tokens_output, 0) AS tokens,
                       COALESCE(cl.cost_usd, 0) AS cost_usd,
                       cl.message_text AS preview
                FROM audit.conversation_log cl
                LEFT JOIN auth.tenants t
                       ON t.platform_tenant_id = cl.tenant_id
                WHERE {where_sql}
                ORDER BY cl.created_at DESC
                LIMIT %s""",
            tuple(params),
        )
        return [
            {
                "timestamp": r["created_at"].isoformat() if r["created_at"] else None,
                "tenant_id": int(r["tenant_id"]),
                "tenant_name": r["tenant_name"],
                "user_id": str(r["user_id"]) if r["user_id"] is not None else "",
                "user_role": "",  # not stored on PG side
                "conversation_id": r["conversation_id"],
                "status": r["status"],
                "tokens": int(r["tokens"] or 0),
                "cost_usd": float(r["cost_usd"] or 0),
                "preview": _truncate(r["preview"]),
                "source": "pg",
            }
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


def _fetch_logs_ss(tenant_id: int | None, status_filter: str | None) -> list[dict[str, Any]]:
    try:
        from app.db.connection import _execute_sync
    except Exception:
        return []
    clauses: list[str] = []
    params: list[Any] = [_LOG_PER_ENGINE_CAP]  # TOP (?)
    if tenant_id is not None:
        clauses.append("tenant_id = ?")
        params.append(tenant_id)
    if status_filter:
        clauses.append("status = ?")
        params.append(status_filter)
    where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    try:
        rows = _execute_sync(
            f"""SELECT TOP (?)
                       timestamp_utc, tenant_id, user_id, user_role,
                       conversation_id, status,
                       ISNULL(tokens_input, 0) + ISNULL(tokens_output, 0) AS tokens,
                       ISNULL(cost_usd, 0) AS cost_usd,
                       user_question AS preview
                FROM api_audit.ai_audit_log
                {where_sql}
                ORDER BY timestamp_utc DESC;""",
            tuple(params),
        )
    except Exception:
        return []

    # Tenant name lookup in one shot (SS auth.tenants)
    tenant_ids = {int(r["tenant_id"]) for r in rows}
    name_map = _resolve_tenant_names_ss(tenant_ids) if tenant_ids else {}

    return [
        {
            "timestamp": (
                r["timestamp_utc"].isoformat()
                if hasattr(r["timestamp_utc"], "isoformat")
                else str(r["timestamp_utc"])
            ),
            "tenant_id": int(r["tenant_id"]),
            "tenant_name": name_map.get(int(r["tenant_id"])),
            "user_id": str(r["user_id"]) if r["user_id"] is not None else "",
            "user_role": r.get("user_role") or "",
            "conversation_id": str(r["conversation_id"]) if r["conversation_id"] else None,
            "status": r["status"],
            "tokens": int(r["tokens"] or 0),
            "cost_usd": float(r["cost_usd"] or 0),
            "preview": _truncate(r["preview"]),
            "source": "ss",
        }
        for r in rows
    ]


class LogRow(BaseModel):
    timestamp: str | None
    tenant_id: int
    tenant_name: str | None
    user_id: str
    user_role: str
    conversation_id: str | None
    status: str
    tokens: int
    cost_usd: float
    preview: str
    source: str  # "pg" | "ss"


class LogsResponse(BaseModel):
    total: int
    rows: list[LogRow]


@router.get(
    "/logs",
    response_model=LogsResponse,
    summary="Cross-tenant chat audit logs (super-admin only)",
)
async def get_logs(
    admin=Depends(_superadmin),
    tenant_id: int | None = None,
    status_filter: str | None = None,
    limit: int = _LOG_DEFAULT_LIMIT,
    offset: int = 0,
) -> LogsResponse:
    # Sanitize paging
    limit = max(1, min(_LOG_MAX_LIMIT, limit))
    offset = max(0, offset)
    # Normalize status: accept SUCCESS / ERROR / PARTIAL / None
    status_filter = (status_filter or "").upper().strip() or None
    if status_filter and status_filter not in ("SUCCESS", "ERROR", "PARTIAL"):
        raise HTTPException(400, "status_filter must be SUCCESS, ERROR or PARTIAL")

    pg_rows = _fetch_logs_pg(tenant_id, status_filter)
    ss_rows = _fetch_logs_ss(tenant_id, status_filter)
    combined = pg_rows + ss_rows
    # Sort DESC by timestamp string (ISO 8601 sorts lexicographically)
    combined.sort(key=lambda r: r["timestamp"] or "", reverse=True)

    total = len(combined)
    page = combined[offset : offset + limit]
    return LogsResponse(total=total, rows=[LogRow(**r) for r in page])
