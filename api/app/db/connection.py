"""SQL Server connection pool + async execution wrapper.

The pool is sync (pyodbc has no native async). Queries are pushed to a
threadpool via ``asyncio.to_thread`` to keep the FastAPI event loop free.

If contention becomes a problem we can swap this layer for aioodbc without
touching call sites (the public surface is ``execute_query`` + ``ping``).
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from queue import Empty, Queue
from typing import Any

import pyodbc
import structlog

from app.config import settings

log = structlog.get_logger(__name__)


class ConnectionPool:
    """Bounded pool of pyodbc connections. Connections are pre-created on
    ``initialize()`` and recycled via the ``acquire()`` context manager."""

    def __init__(self, conn_str: str, size: int) -> None:
        self._conn_str = conn_str
        self._size = size
        self._pool: Queue[pyodbc.Connection] = Queue(maxsize=size)
        self._lock = threading.Lock()
        self._initialized = False

    def initialize(self) -> None:
        with self._lock:
            if self._initialized:
                return
            for _ in range(self._size):
                self._pool.put(pyodbc.connect(self._conn_str, autocommit=True))
            self._initialized = True
            log.info("db.pool.initialized", size=self._size)

    def close_all(self) -> None:
        with self._lock:
            while not self._pool.empty():
                try:
                    conn = self._pool.get_nowait()
                    conn.close()
                except Empty:
                    break
            self._initialized = False
            log.info("db.pool.closed")

    @contextmanager
    def acquire(self):
        """Yield a connection; return it to the pool on exit."""
        if not self._initialized:
            self.initialize()
        conn = self._pool.get(timeout=10)
        try:
            yield conn
        finally:
            self._pool.put(conn)


pool = ConnectionPool(settings.odbc_connection_string, settings.sql_pool_size)


def _execute_sync(query: str, params: tuple[Any, ...] | None) -> list[dict[str, Any]]:
    """Run a query synchronously and return rows as list of dicts."""
    with pool.acquire() as conn:
        cursor = conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        if cursor.description is None:
            return []
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        return [dict(zip(columns, row, strict=False)) for row in rows]


async def execute_query(
    query: str, params: tuple[Any, ...] | None = None
) -> list[dict[str, Any]]:
    """Run a parametrised SELECT and return list-of-dict rows.

    Use ONLY parameterised queries: pass placeholders (``?``) in ``query`` and
    values in ``params``. Never f-string user input into the SQL.
    """
    return await asyncio.to_thread(_execute_sync, query, params)


async def ping() -> dict[str, Any]:
    """Lightweight health probe.

    Returns ``{"db_ok": True, "db_database": <name>, "tenant_count": <n>|None}``
    or ``{"db_ok": False, "error": <msg>}`` on failure.
    """
    try:
        rows = await execute_query("SELECT DB_NAME() AS db;")
        if not rows:
            return {"db_ok": False, "error": "empty response"}
        result: dict[str, Any] = {"db_ok": True, "db_database": rows[0]["db"]}
        # Tenant count is best-effort; degrade gracefully if [empresa] isn't there.
        try:
            t_rows = await execute_query(
                "SELECT COUNT(*) AS n FROM dbo.empresa WHERE [delete] = 0;"
            )
            result["tenant_count"] = int(t_rows[0]["n"]) if t_rows else None
        except Exception as inner:  # noqa: BLE001
            log.warning("db.ping.tenant_count_unavailable", error=str(inner))
            result["tenant_count"] = None
        return result
    except Exception as e:  # noqa: BLE001
        log.exception("db.ping.failed", error=str(e))
        return {"db_ok": False, "error": str(e)}
