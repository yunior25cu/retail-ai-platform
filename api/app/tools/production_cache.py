"""In-memory cache for production tool results + per-request hit tracker.

Simple dict + threading.Lock + TTL — no external dependencies.
Sufficient for MVP with uvicorn workers=1.

Known limitation: if scaled to multiple uvicorn workers the cache
is fragmented per process. Acceptable for MVP; replace with Redis
or a shared cache backend if multi-worker deployment is needed.
"""

from __future__ import annotations

import threading
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Any

# ── Per-request cache hit tracker (async-safe via contextvars) ────────────────
_request_cache_hits: ContextVar[list[str]] = ContextVar("_request_cache_hits", default=[])


def request_cache_hits_reset() -> None:
    """Call at the start of each request to clear the hit list."""
    _request_cache_hits.set([])


def request_cache_hits_get() -> list[str]:
    """Return tool names that were served from cache in this request."""
    return list(_request_cache_hits.get())


def _record_hit(tool_name: str) -> None:
    hits = _request_cache_hits.get()
    _request_cache_hits.set([*hits, tool_name])

_cache: dict[str, tuple[Any, datetime]] = {}
_lock = threading.Lock()

# Default TTLs
_TTL_SHORT   = timedelta(minutes=5)   # forecast, coverage, stock
_TTL_REACTOR = timedelta(minutes=30)  # reactors almost never change


def cache_get(key: str) -> Any | None:
    """Return cached value if present and not expired, else None."""
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        value, ts = entry
        ttl = _TTL_REACTOR if ":reactors" in key else _TTL_SHORT
        if datetime.now() - ts < ttl:
            return value
        del _cache[key]
    return None


def cache_set(key: str, value: Any) -> None:
    """Store value with current timestamp."""
    with _lock:
        _cache[key] = (value, datetime.now())


def cache_invalidate_tenant(tenant_id: int) -> None:
    """Invalidate all cached entries for a tenant (e.g. after data refresh)."""
    prefix = f"{tenant_id}:"
    with _lock:
        stale = [k for k in _cache if k.startswith(prefix)]
        for k in stale:
            del _cache[k]


def cache_stats() -> dict[str, Any]:
    """Debug helper — number of live entries per tenant."""
    with _lock:
        total = len(_cache)
        by_tenant: dict[str, int] = {}
        for k in _cache:
            tid = k.split(":")[0]
            by_tenant[tid] = by_tenant.get(tid, 0) + 1
    return {"total_entries": total, "by_tenant": by_tenant, "ttl_minutes": 5}
