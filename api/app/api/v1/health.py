"""GET /api/v1/health — liveness + DB readiness probe."""

from fastapi import APIRouter
from pydantic import BaseModel

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
