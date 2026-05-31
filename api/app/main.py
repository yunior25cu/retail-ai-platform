"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded as SlowApiRateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api.router import router as v1_router
from app.auth.router import router as auth_router, limiter as auth_limiter
from app.config import settings
from app.db.connection import pool


def _configure_logging() -> None:
    """Configure structlog to emit either JSON (prod) or pretty console (dev)."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


_configure_logging()
log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise resources on startup, dispose on shutdown."""
    log.info(
        "api.startup",
        environment=settings.environment,
        gold_db_host=settings.sql_server,
        gold_db_name=settings.sql_database,
    )
    pool.initialize()
    try:
        yield
    finally:
        pool.close_all()
        log.info("api.shutdown")


app = FastAPI(
    title="Retail AI Platform — API",
    version="0.9.0",
    description=(
        "Multi-tenant conversational analytics API. "
        "Exposes ten Gold data warehouse tools (alerts, dashboards, SKU analysis, "
        "period comparison, audit trail) via Anthropic function-calling. "
        "Every request is JWT-authenticated, role-gated, rate-limited, and fully "
        "audited in the `api_audit` schema.\n\n"
        "**Authentication**: Bearer JWT (HS256) required in production. "
        "Set `AUTH_REQUIRE_JWT=true` to disable the `X-Mock-*` header fallback.\n\n"
        "**Roles**: `direccion` (full access) · `marca` · `tienda` · `sku` "
        "(sanitizer active — entity IDs replaced with opaque tokens).\n\n"
        "Interactive docs: `/docs` (Swagger UI) · `/redoc` (ReDoc)"
    ),
    contact={"name": "Retail AI Platform", "url": "https://github.com/your-org/retail-ai-platform"},
    license_info={"name": "MIT"},
    lifespan=lifespan,
)

app.state.limiter = auth_limiter
app.add_exception_handler(SlowApiRateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.include_router(v1_router)
app.include_router(auth_router)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {"name": "retail-ai-api", "version": app.version, "docs": "/docs"}
