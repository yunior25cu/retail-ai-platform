"""GET /api/v1/health — liveness + DB readiness probe.
GET /api/v1/health/ready — deep readiness probe for ERP startup check.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings
from app.db.connection import ping

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    db_ok: bool
    db_database: str | None = None
    tenant_count: int | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "ok",
                    "db_ok": True,
                    "db_database": "pymeconta_local",
                    "tenant_count": 12,
                }
            ]
        }
    }


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description=(
        "Liveness and database readiness probe. "
        "`status` is `ok` when the DB is reachable, `degraded` otherwise. "
        "No authentication required."
    ),
)
async def health() -> HealthResponse:
    db_info = await ping()
    status = "ok" if db_info.get("db_ok") else "degraded"
    return HealthResponse(status=status, **db_info)


_ANTHROPIC_PLACEHOLDER = "sk-ant-replace-me"


class ReadyResponse(BaseModel):
    status: str   # 'ready' | 'not_ready'
    mode: str     # 'service' (SERVICE_KEY configured) | 'dev'
    db_ok: bool
    anthropic_ok: bool


@router.get(
    "/health/ready",
    response_model=ReadyResponse,
    summary="Deep readiness probe (ERP startup check)",
    description=(
        "Verifies DB connectivity, Anthropic API key, and service-key configuration. "
        "ERP proxies should call this at startup before routing user traffic. "
        "No authentication required."
    ),
)
async def health_ready() -> ReadyResponse:
    db_info = await ping()
    db_ok: bool = bool(db_info.get("db_ok"))
    anthropic_ok: bool = bool(
        settings.anthropic_api_key
        and settings.anthropic_api_key != _ANTHROPIC_PLACEHOLDER
    )
    mode = "service" if settings.service_key else "dev"
    all_ready = db_ok and anthropic_ok
    return ReadyResponse(
        status="ready" if all_ready else "not_ready",
        mode=mode,
        db_ok=db_ok,
        anthropic_ok=anthropic_ok,
    )
