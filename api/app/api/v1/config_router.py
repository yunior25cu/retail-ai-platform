"""GET/PATCH /api/v1/config/tenant — tenant AI configuration.

Reads/writes api_audit.ai_tenant_config.
Requires Bearer JWT auth. Only direccion and super_admin can PATCH.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import get_current_user_dep
from app.db.connection import execute_query
from app.db.tenant_config import get_tenant_config, update_tenant_config, invalidate_cache, get_monthly_spend_usd

router = APIRouter(prefix="/config", tags=["config"])

_ADMIN_ROLES = {"super_admin", "direccion"}


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


@router.get("/tenant", response_model=TenantConfigResponse)
async def get_tenant_config_endpoint(
    user=Depends(get_current_user_dep),
) -> TenantConfigResponse:
    cfg = await get_tenant_config(user.tenant_id)
    spend = await get_monthly_spend_usd(user.tenant_id)

    # Read vertical from auth.tenants via platform_tenant_id
    vertical_rows = await execute_query(
        """SELECT t.vertical FROM auth.tenants t
           JOIN auth.users u ON u.tenant_id = t.id
           WHERE u.id = ?""",
        (str(user.id),),
    )
    vertical = vertical_rows[0]["vertical"] if vertical_rows else "retail"

    return TenantConfigResponse(
        monthly_budget_usd=cfg.monthly_budget_usd,
        budget_alert_pct=cfg.budget_alert_pct,
        memory_turns=cfg.memory_turns,
        suggestions_enabled=cfg.suggestions_enabled,
        rate_limits={
            "director":   cfg.rate_limit_director,
            "produccion": cfg.rate_limit_produccion,
            "marca":      cfg.rate_limit_marca,
            "tienda":     cfg.rate_limit_tienda,
            "producto":   cfg.rate_limit_producto,
        },
        current_spend_usd=spend,
        vertical=vertical,
    )


@router.patch("/tenant", response_model=TenantConfigResponse)
async def patch_tenant_config(
    payload: TenantConfigPatch,
    user=Depends(get_current_user_dep),
) -> TenantConfigResponse:
    if user.role not in _ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo roles admin y dirección pueden modificar la configuración.",
        )

    field_map: dict[str, Any] = {
        "monthly_budget_usd":   payload.monthly_budget_usd,
        "budget_alert_pct":     payload.budget_alert_pct,
        "memory_turns":         payload.memory_turns,
        "suggestions_enabled":  payload.suggestions_enabled,
        "rate_limit_director":  payload.rate_limit_director,
        "rate_limit_produccion":payload.rate_limit_produccion,
        "rate_limit_marca":     payload.rate_limit_marca,
        "rate_limit_tienda":    payload.rate_limit_tienda,
        "rate_limit_producto":  payload.rate_limit_producto,
    }

    for key, value in field_map.items():
        if value is not None:
            await update_tenant_config(
                tenant_id=user.tenant_id,
                key=key,
                value=str(value).lower() if isinstance(value, bool) else str(value),
                updated_by=None,
            )

    invalidate_cache(user.tenant_id)
    return await get_tenant_config_endpoint(user)
