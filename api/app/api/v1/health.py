"""GET /api/v1/health — liveness + DB readiness probe."""

from fastapi import APIRouter

from app.db.connection import ping

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    db_info = await ping()
    status = "ok" if db_info.get("db_ok") else "degraded"
    return {"status": status, **db_info}
