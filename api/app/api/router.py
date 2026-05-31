"""Top-level v1 router aggregating endpoints under /api/v1."""

from fastapi import APIRouter

from app.api.v1 import chat, conversations, health, internal
from app.api.v1.config_router import router as config_router
from app.api.v1.admin_router import router as admin_router

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(chat.router)
router.include_router(conversations.router)
router.include_router(internal.router)
router.include_router(config_router)
router.include_router(admin_router)
