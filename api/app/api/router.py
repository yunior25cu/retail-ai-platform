"""Top-level v1 router aggregating endpoints under /api/v1."""

from fastapi import APIRouter

from app.api.v1 import health

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
