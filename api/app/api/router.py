"""Top-level v1 router aggregating endpoints under /api/v1."""

from fastapi import APIRouter

from app.api.v1 import chat, conversations, health

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(chat.router)
router.include_router(conversations.router)
