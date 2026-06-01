"""GET/PATCH /api/v1/config/tenant — tenant AI configuration.

Reads/writes the per-tenant config table (PG or SQL Server depending on tenant).
Requires Bearer JWT auth.

Role hierarchy for access:
  superadmin   → can read/write any tenant (pass ?tenant_id=X to scope)
  admin_tenant → read/write their own tenant (tenant_id from JWT)
  direccion    → read/write their own tenant
  other roles  → 403
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.auth.dependencies import get_current_user_dep
from app.db.tenant_config import (
    get_tenant_config,
    get_monthly_spend_usd,
    update_tenant_config,
    invalidate_cache,
)

router = APIRouter(prefix="/config", tags=["config"])

_ADMIN_ROLES = {"super_admin", "superadmin", "admin_tenant", "direccion"}


class TenantConfigResponse(BaseModel):
    monthly_budget_usd: float
    budget_alert_pct: int
    memory_turns: int
    suggestions_enabled: bool
    rate_limits: dict[str, int]
    current_spend_usd: float
    vertical: str


class TenantConfigPatch(BaseModel):
    monthly_budget_usd: float | None = None
    budget_alert_pct: int | None = None
    memory_turns: int | None = None
    suggestions_enabled: bool | None = None
    rate_limit_director: int | None = None
    rate_limit_produccion: int | None = None
    rate_limit_compras: int | None = None
    rate_limit_marca: int | None = None
    rate_limit_tienda: int | None = None
    rate_limit_producto: int | None = None


def _resolve_tenant_id(user, tenant_id_param: int | None) -> int:
    """Returns the effective tenant_id for the request.

    Superadmin can scope to any tenant via ?tenant_id=X.
    All other roles use their own tenant from the JWT.
    """
    if user.role in {"super_admin", "superadmin"} and tenant_id_param is not None:
        return tenant_id_param
    return user.tenant_id


async def _build_response(tenant_id: int) -> TenantConfigResponse:
    cfg = await get_tenant_config(tenant_id)
    spend = await get_monthly_spend_usd(tenant_id)
    return TenantConfigResponse(
        monthly_budget_usd=cfg.monthly_budget_usd,
        budget_alert_pct=cfg.budget_alert_pct,
        memory_turns=cfg.memory_turns,
        suggestions_enabled=cfg.suggestions_enabled,
        rate_limits={
            "director":   cfg.rate_limit_director,
            "produccion": cfg.rate_limit_produccion,
            "compras":    cfg.rate_limit_compras,
            "marca":      cfg.rate_limit_marca,
            "tienda":     cfg.rate_limit_tienda,
            "producto":   cfg.rate_limit_producto,
        },
        current_spend_usd=spend,
        vertical=cfg.vertical,
    )


@router.get("/tenant", response_model=TenantConfigResponse)
async def get_tenant_config_endpoint(
    user=Depends(get_current_user_dep),
    tenant_id: Annotated[int | None, Query(description="Superadmin only: scope to a specific tenant")] = None,
) -> TenantConfigResponse:
    if user.role not in _ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. Se requiere rol admin o dirección.",
        )
    effective_tid = _resolve_tenant_id(user, tenant_id)
    return await _build_response(effective_tid)


@router.patch("/tenant", response_model=TenantConfigResponse)
async def patch_tenant_config(
    payload: TenantConfigPatch,
    user=Depends(get_current_user_dep),
    tenant_id: Annotated[int | None, Query(description="Superadmin only: scope to a specific tenant")] = None,
) -> TenantConfigResponse:
    if user.role not in _ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo roles admin y dirección pueden modificar la configuración.",
        )

    effective_tid = _resolve_tenant_id(user, tenant_id)

    field_map: dict[str, Any] = {
        "monthly_budget_usd":    payload.monthly_budget_usd,
        "budget_alert_pct":      payload.budget_alert_pct,
        "memory_turns":          payload.memory_turns,
        "suggestions_enabled":   payload.suggestions_enabled,
        "rate_limit_director":   payload.rate_limit_director,
        "rate_limit_produccion": payload.rate_limit_produccion,
        "rate_limit_compras":    payload.rate_limit_compras,
        "rate_limit_marca":      payload.rate_limit_marca,
        "rate_limit_tienda":     payload.rate_limit_tienda,
        "rate_limit_producto":   payload.rate_limit_producto,
    }

    for key, value in field_map.items():
        if value is not None:
            await update_tenant_config(
                tenant_id=effective_tid,
                key=key,
                value=str(value).lower() if isinstance(value, bool) else str(value),
                updated_by=None,
            )

    invalidate_cache(effective_tid)
    return await _build_response(effective_tid)


@router.get("/tenant/usage")
async def get_tenant_usage(
    user=Depends(get_current_user_dep),
    tenant_id: Annotated[int | None, Query(description="Superadmin only: scope to a specific tenant")] = None,
) -> dict[str, float]:
    """Returns actual spend for the current month from the audit log."""
    if user.role not in _ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado.",
        )
    effective_tid = _resolve_tenant_id(user, tenant_id)
    spend = await get_monthly_spend_usd(effective_tid)
    return {"tenant_id": float(effective_tid), "current_spend_usd": spend}
