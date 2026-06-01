"""Per-tenant configuration for the AI Assistant.

Reads + writes:
  - SQL Server tenants: ``api_audit.ai_tenant_config``
  - PostgreSQL tenants:  ``config.tenant_config``

Routing is determined by ``connections.is_postgres(tenant_id)``.
Missing keys fall back to TenantConfig defaults so a brand-new tenant always works.

In-memory cache: 5 minutes per tenant. Single-process semantics — if you
run multiple uvicorn workers, an update made in worker A is invisible
to worker B until that worker's cache expires.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.db.connection import execute_query

_CACHE_TTL_SECONDS = 300

_VALID_KEYS = frozenset(
    {
        "memory_turns",
        "monthly_budget_usd",
        "budget_alert_pct",
        "rate_limit_director",
        "rate_limit_marca",
        "rate_limit_tienda",
        "rate_limit_producto",
        "rate_limit_produccion",
        "rate_limit_compras",
        "suggestions_enabled",
        "vertical",             # 'retail' | 'produccion' | extensible
    }
)


@dataclass
class TenantConfig:
    """Typed snapshot of the AI settings for one tenant.

    Defaults mirror the SQL seed in ``13_tenant_config.sql``. Don't change
    them in only one place — keep both in sync.
    """

    memory_turns: int = 3
    monthly_budget_usd: float = 0.0  # 0 means unlimited, NOT zero budget
    budget_alert_pct: int = 80
    rate_limit_director: int = 50
    rate_limit_marca: int = 30
    rate_limit_tienda: int = 15
    rate_limit_producto: int = 15
    rate_limit_produccion: int = 30
    rate_limit_compras: int = 30
    suggestions_enabled: bool = True
    vertical: str = "retail"          # 'retail' | 'produccion' | extensible

    def rate_limit_for_role(self, role: str) -> int:
        """Returns the per-hour cap for a given role string."""
        mapping = {
            "direccion":   self.rate_limit_director,
            "marca":       self.rate_limit_marca,
            "tienda":      self.rate_limit_tienda,
            "sku":         self.rate_limit_producto,
            "producto":    self.rate_limit_producto,
            "produccion":  self.rate_limit_produccion,
            "compras":     self.rate_limit_compras,
        }
        return mapping.get(role, self.rate_limit_producto)


# tenant_id -> (loaded_at, config)
_cache: dict[int, tuple[float, TenantConfig]] = {}


def _apply_row(cfg: TenantConfig, key: str, value: str) -> None:
    """Coerce a single key/value pair onto the dataclass. Silent on
    malformed values (we keep the default rather than raising; the PATCH
    endpoint is the place to reject bad input)."""
    try:
        if key == "memory_turns":
            cfg.memory_turns = int(value)
        elif key == "monthly_budget_usd":
            cfg.monthly_budget_usd = float(value)
        elif key == "budget_alert_pct":
            cfg.budget_alert_pct = int(value)
        elif key == "rate_limit_director":
            cfg.rate_limit_director = int(value)
        elif key == "rate_limit_marca":
            cfg.rate_limit_marca = int(value)
        elif key == "rate_limit_tienda":
            cfg.rate_limit_tienda = int(value)
        elif key == "rate_limit_producto":
            cfg.rate_limit_producto = int(value)
        elif key == "rate_limit_produccion":
            cfg.rate_limit_produccion = int(value)
        elif key == "rate_limit_compras":
            cfg.rate_limit_compras = int(value)
        elif key == "vertical":
            cfg.vertical = value.lower().strip()
        elif key == "suggestions_enabled":
            cfg.suggestions_enabled = value.lower() == "true"
    except (TypeError, ValueError):
        pass


async def get_tenant_config(tenant_id: int) -> TenantConfig:
    """Returns the config for ``tenant_id`` (cached 5 min). Missing rows
    fall back to TenantConfig defaults."""
    now = time.time()
    cached = _cache.get(tenant_id)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    from app.db.connections import is_postgres, _execute_pg

    if is_postgres(tenant_id):
        rows = await _execute_pg(
            "SELECT config_key, config_value FROM config.tenant_config WHERE tenant_id = ?",
            (tenant_id,),
        )
    else:
        rows = await execute_query(
            """
            SELECT config_key, config_value
            FROM api_audit.ai_tenant_config
            WHERE tenant_id = ?;
            """,
            (tenant_id,),
        )

    cfg = TenantConfig()
    for row in rows:
        _apply_row(cfg, row["config_key"], row["config_value"])

    _cache[tenant_id] = (now, cfg)
    return cfg


async def update_tenant_config(
    tenant_id: int, key: str, value: str, updated_by: int | None
) -> None:
    """Upserts a single key. Invalidates the tenant cache so the next read
    returns fresh data within this process. Caller is responsible for
    validation — this layer only enforces the allowed key set."""
    if key not in _VALID_KEYS:
        raise ValueError(f"unknown config_key: {key!r}")

    from app.db.connections import is_postgres, _execute_pg_write

    if is_postgres(tenant_id):
        await _execute_pg_write(
            """
            INSERT INTO config.tenant_config (tenant_id, config_key, config_value)
            VALUES (?, ?, ?)
            ON CONFLICT (tenant_id, config_key)
            DO UPDATE SET config_value = EXCLUDED.config_value,
                          updated_at   = NOW()
            """,
            (tenant_id, key, value),
        )
    else:
        await execute_query(
            """
            MERGE api_audit.ai_tenant_config AS target
            USING (SELECT ? AS tenant_id, ? AS config_key) AS source
                ON target.tenant_id = source.tenant_id
               AND target.config_key = source.config_key
            WHEN MATCHED THEN
                UPDATE SET config_value = ?,
                           updated_at  = SYSUTCDATETIME(),
                           updated_by  = ?
            WHEN NOT MATCHED THEN
                INSERT (tenant_id, config_key, config_value, updated_by)
                VALUES (?, ?, ?, ?);
            """,
            (
                tenant_id, key,
                value, updated_by,
                tenant_id, key, value, updated_by,
            ),
        )

    _cache.pop(tenant_id, None)


def invalidate_cache(tenant_id: int | None = None) -> None:
    """Test helper / admin tool. ``None`` clears the whole cache."""
    if tenant_id is None:
        _cache.clear()
    else:
        _cache.pop(tenant_id, None)


async def get_monthly_spend_usd(tenant_id: int) -> float:
    """Sum of cost_usd over the current UTC month.

    - PG tenants: audit.conversation_log has tokens_used but no cost column.
      Estimated at $9 / 1M tokens (claude-sonnet-4 blended rate).
    - SS tenants: reads api_audit.ai_audit_log.cost_usd (exact).
    """
    from app.db.connections import is_postgres, _execute_pg

    if is_postgres(tenant_id):
        rows = await _execute_pg(
            """
            SELECT COALESCE(SUM(cost_usd), 0.0) AS total
            FROM audit.conversation_log
            WHERE tenant_id = ?
              AND DATE_TRUNC('month', created_at) = DATE_TRUNC('month', NOW())
            """,
            (tenant_id,),
        )
        return float(rows[0]["total"]) if rows else 0.0
    else:
        rows = await execute_query(
            """
            SELECT ISNULL(SUM(CAST(cost_usd AS FLOAT)), 0) AS total
            FROM api_audit.ai_audit_log
            WHERE tenant_id = ?
              AND timestamp_utc >= DATEFROMPARTS(
                      YEAR(SYSUTCDATETIME()), MONTH(SYSUTCDATETIME()), 1)
              AND timestamp_utc <  DATEADD(MONTH, 1,
                      DATEFROMPARTS(
                          YEAR(SYSUTCDATETIME()), MONTH(SYSUTCDATETIME()), 1))
              AND status = 'SUCCESS';
            """,
            (tenant_id,),
        )

    return float(rows[0]["total"]) if rows else 0.0
