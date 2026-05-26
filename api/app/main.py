"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.router import router as v1_router
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
    log.info("api.startup", database=settings.sql_database, server=settings.sql_server)
    pool.initialize()
    try:
        yield
    finally:
        pool.close_all()
        log.info("api.shutdown")


app = FastAPI(
    title="Retail AI Platform — API",
    version="0.1.0",
    description=(
        "Backend exposing Gold data warehouse as Claude tools (multi-tenant). "
        "Phase 4 of the retail-ai-platform project."
    ),
    lifespan=lifespan,
)

app.include_router(v1_router)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {"name": "retail-ai-api", "version": app.version, "docs": "/docs"}
