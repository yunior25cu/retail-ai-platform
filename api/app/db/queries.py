"""SQL queries against the [gold] layer.

Conventions:
    - Every function takes ``tenant_id`` as first positional arg and uses it as
      the FIRST predicate in the WHERE clause. NO query may omit it.
    - Queries are parameterised with ``?`` placeholders (pyodbc style). Never
      f-string user input into the SQL.
    - Each function returns a list of dict rows (column name -> value).
    - Nullable filters use the ``(? IS NULL OR col = ?)`` pattern; the same
      value is bound twice.
"""

from __future__ import annotations

from typing import Any

from app.db.connection import execute_query


# ----------------------------------------------------------------------------
# vw_active_alerts
# ----------------------------------------------------------------------------
async def fetch_active_alerts(
    tenant_id: int,
    *,
    level: str | None = None,
    severity: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    sql = """
        SELECT TOP (?)
            alert_id,
            iso_year_week,
            [level],
            alert_type,
            severity,
            store_id,
            sku_id,
            brand_id,
            metric_value,
            threshold,
            suggested_action,
            estimated_impact_usd
        FROM gold.vw_active_alerts
        WHERE tenant_id = ?
          AND (? IS NULL OR [level]   = ?)
          AND (? IS NULL OR severity  = ?)
        ORDER BY estimated_impact_usd DESC, alert_id;
    """
    params = (limit, tenant_id, level, level, severity, severity)
    return await execute_query(sql, params)


# ----------------------------------------------------------------------------
# vw_store_dashboard
# ----------------------------------------------------------------------------
async def fetch_store_dashboard(
    tenant_id: int,
    *,
    store_id: int | None = None,
    week_id: str | None = None,
) -> list[dict[str, Any]]:
    # NOTE: vw_store_dashboard returns rows for the latest iso_year_week per
    # tenant by design. The week_id filter, when supplied, is applied on top.
    # If it does not match the latest week, the result will be empty — that is
    # an honest signal that historical week views require a different tool.
    sql = """
        SELECT
            iso_year_week,
            store_id,
            store_code,
            store_name,
            block_AB,
            is_store_flag,
            units_sold,
            revenue,
            cogs,
            gross_margin,
            gross_margin_pct,
            tickets,
            avg_ticket,
            stock_units,
            stock_value,
            skus_in_store,
            skus_zero_stock,
            skus_obsolete
        FROM gold.vw_store_dashboard
        WHERE tenant_id = ?
          AND (? IS NULL OR store_id      = ?)
          AND (? IS NULL OR iso_year_week = ?)
        ORDER BY revenue DESC, store_id;
    """
    params = (tenant_id, store_id, store_id, week_id, week_id)
    return await execute_query(sql, params)


# ----------------------------------------------------------------------------
# vw_brand_performance
# ----------------------------------------------------------------------------
async def fetch_brand_performance(
    tenant_id: int,
    *,
    brand_id: int | None = None,
    week_id: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            iso_year_week,
            brand_id,
            brand_name,
            units_sold,
            revenue,
            cogs,
            gross_margin,
            gross_margin_pct,
            planned_units,
            planned_revenue,
            units_vs_plan_pct,
            revenue_vs_plan_pct,
            stock_units,
            stock_value,
            skus_count,
            skus_zero_stock,
            skus_obsolete
        FROM gold.vw_brand_performance
        WHERE tenant_id = ?
          AND (? IS NULL OR brand_id      = ?)
          AND (? IS NULL OR iso_year_week = ?)
        ORDER BY revenue DESC, brand_id;
    """
    params = (tenant_id, brand_id, brand_id, week_id, week_id)
    return await execute_query(sql, params)
