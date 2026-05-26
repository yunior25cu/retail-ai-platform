"""In-memory sliding-window rate limiter.

Quotas (configurable via env):
    - per tenant: RATE_LIMIT_TENANT_HOUR requests / hour
    - per user:   RATE_LIMIT_USER_HOUR   requests / hour
    - per tenant: RATE_LIMIT_TOKENS_DAY  tokens   / 24h

Notes:
    - In-memory means counters do NOT survive across processes. For multi-
      worker deployments swap this for a Redis-backed implementation.
    - Thread-safe via a single ``threading.Lock`` around all mutations. The
      hot path is O(window-size) per call.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque

from app.config import settings

_HOUR_SECONDS = 3600
_DAY_SECONDS = 86_400


class RateLimitExceeded(Exception):
    """Raised when a quota has been breached. ``.scope`` indicates which one."""

    def __init__(self, scope: str, detail: str) -> None:
        super().__init__(detail)
        self.scope = scope
        self.detail = detail


class RateLimiter:
    """Sliding-window limiter for requests and token usage."""

    def __init__(
        self,
        *,
        tenant_per_hour: int | None = None,
        user_per_hour: int | None = None,
        tokens_per_day_per_tenant: int | None = None,
    ) -> None:
        self.tenant_per_hour = tenant_per_hour or settings.rate_limit_tenant_hour
        self.user_per_hour = user_per_hour or settings.rate_limit_user_hour
        self.tokens_per_day = (
            tokens_per_day_per_tenant or settings.rate_limit_tokens_day
        )

        self._tenant_hits: dict[int, Deque[float]] = defaultdict(deque)
        self._user_hits: dict[tuple[int, str], Deque[float]] = defaultdict(deque)
        self._tenant_tokens: dict[int, Deque[tuple[float, int]]] = defaultdict(deque)
        self._lock = threading.Lock()

    # ---------- Public API ----------

    def check_and_record_request(self, tenant_id: int, user_id: str) -> None:
        """Check both tenant- and user-level quotas; record a hit if allowed.

        Raises ``RateLimitExceeded`` with ``scope`` of ``tenant`` or ``user``
        when a quota is breached.
        """
        now = time.monotonic()
        with self._lock:
            t_hits = self._tenant_hits[tenant_id]
            u_hits = self._user_hits[(tenant_id, user_id)]
            _trim(t_hits, now - _HOUR_SECONDS)
            _trim(u_hits, now - _HOUR_SECONDS)

            if len(t_hits) >= self.tenant_per_hour:
                raise RateLimitExceeded(
                    "tenant",
                    f"tenant {tenant_id} exceeded {self.tenant_per_hour}/h",
                )
            if len(u_hits) >= self.user_per_hour:
                raise RateLimitExceeded(
                    "user",
                    f"user {user_id} exceeded {self.user_per_hour}/h",
                )
            t_hits.append(now)
            u_hits.append(now)

    def check_token_budget(self, tenant_id: int) -> None:
        """Raise ``RateLimitExceeded`` if tenant has already used its daily
        token budget. Called BEFORE invoking the LLM."""
        now = time.monotonic()
        with self._lock:
            q = self._tenant_tokens[tenant_id]
            _trim_pairs(q, now - _DAY_SECONDS)
            used = sum(n for _, n in q)
            if used >= self.tokens_per_day:
                raise RateLimitExceeded(
                    "tokens",
                    f"tenant {tenant_id} exceeded {self.tokens_per_day} tokens/day",
                )

    def record_tokens(self, tenant_id: int, tokens: int) -> None:
        if tokens <= 0:
            return
        now = time.monotonic()
        with self._lock:
            self._tenant_tokens[tenant_id].append((now, tokens))

    # ---------- Test helpers ----------

    def reset(self) -> None:
        """Wipe all counters. Used by tests to isolate cases."""
        with self._lock:
            self._tenant_hits.clear()
            self._user_hits.clear()
            self._tenant_tokens.clear()

    def snapshot(self, tenant_id: int) -> dict[str, int]:
        """Read-only snapshot of current usage for the given tenant."""
        now = time.monotonic()
        with self._lock:
            t_hits = self._tenant_hits.get(tenant_id, deque())
            _trim(t_hits, now - _HOUR_SECONDS)
            tokens_q = self._tenant_tokens.get(tenant_id, deque())
            _trim_pairs(tokens_q, now - _DAY_SECONDS)
            return {
                "requests_last_hour": len(t_hits),
                "tokens_last_day": sum(n for _, n in tokens_q),
            }


# ---------- helpers ----------


def _trim(q: Deque[float], cutoff: float) -> None:
    while q and q[0] < cutoff:
        q.popleft()


def _trim_pairs(q: Deque[tuple[float, int]], cutoff: float) -> None:
    while q and q[0][0] < cutoff:
        q.popleft()


# Module-level singleton used by the chat endpoint.
limiter = RateLimiter()
