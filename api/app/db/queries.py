"""SQL queries against the [gold] (and [api_audit]) layers.

Conventions:
    - Every function takes ``tenant_id`` as first positional arg and uses it as
      the FIRST predicate in the WHERE clause. NO query may omit it.
    - Queries are parameterised with ``?`` placeholders (pyodbc style). Never
      f-string user input into the SQL.
    - Each function returns a list of dict rows (column name -> value).
    - Nullable filters use the ``(? IS NULL OR col = ?)`` pattern; the same
      value is bound twice.
    - Where the metric/scope column itself is dynamic (e.g. compare_periods),
      the caller MUST pass an enum-validated value so the value is part of a
      hard-coded allowlist before it lands in the SQL string.
"""

from __future__ import annotations

from typing import Any

from app.db.connection import execute_query

# ----------------------------------------------------------------------------
# Allowlists for dynamic SQL fragments. Adding a value here is the ONLY way
# it becomes injectable into a query string.
# ----------------------------------------------------------------------------
COMPARE_METRICS = {
    "units_sold_net",
    "units_sold_gross",
    "revenue_net",
    "revenue_gross",
    "gross_margin",
    "cogs",
    "tickets",
    "discount_amount",
}
COMPARE_SCOPES = {"tenant", "brand", "store"}


# ----------------------------------------------------------------------------
# vw_active_alerts (used by get_active_alerts + executive_summary top-3)
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
            alert_id, iso_year_week, [level], alert_type, severity,
            store_id, sku_id, brand_id,
            sku_code, sku_name, brand_name, store_name,
            metric_value, threshold, suggested_action, estimated_impact_usd
        FROM gold.vw_active_alerts
        WHERE tenant_id = ?
          AND (? IS NULL OR [level]  = ?)
          AND (? IS NULL OR severity = ?)
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
    sql = """
        SELECT
            iso_year_week, store_id, store_code, store_name, block_AB,
            is_store_flag, units_sold, revenue, cogs, gross_margin,
            gross_margin_pct, tickets, avg_ticket, stock_units, stock_value,
            skus_in_store, skus_zero_stock, skus_obsolete
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
            iso_year_week, brand_id, brand_name,
            units_sold, revenue, cogs, gross_margin, gross_margin_pct,
            planned_units, planned_revenue, units_vs_plan_pct, revenue_vs_plan_pct,
            stock_units, stock_value, skus_count, skus_zero_stock, skus_obsolete
        FROM gold.vw_brand_performance
        WHERE tenant_id = ?
          AND (? IS NULL OR brand_id      = ?)
          AND (? IS NULL OR iso_year_week = ?)
        ORDER BY revenue DESC, brand_id;
    """
    params = (tenant_id, brand_id, brand_id, week_id, week_id)
    return await execute_query(sql, params)


# ----------------------------------------------------------------------------
# vw_sku_coverage_status
# ----------------------------------------------------------------------------
async def fetch_sku_coverage_status(
    tenant_id: int,
    *,
    brand_id: int | None = None,
    store_id: int | None = None,
    status: str | None = None,
    sku_id: int | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    sql = """
        SELECT TOP (?)
            iso_year_week, store_id, sku_id, sku_code, sku_name, store_name,
            brand_id, brand_name, category_id,
            stock_units, stock_value, unit_cost,
            has_zero_stock_flag, is_obsolete_flag, days_since_last_sale,
            units_per_day_4w, days_coverage,
            target_min_days, target_max_days,
            suggested_action, suggested_discount_pct, status_color
        FROM gold.vw_sku_coverage_status
        WHERE tenant_id = ?
          AND (? IS NULL OR brand_id     = ?)
          AND (? IS NULL OR store_id     = ?)
          AND (? IS NULL OR status_color = ?)
          AND (? IS NULL OR sku_id       = ?)
        ORDER BY
            CASE status_color
                WHEN N'RED' THEN 1 WHEN N'YELLOW' THEN 2
                WHEN N'GREY' THEN 3 WHEN N'GREEN' THEN 4 ELSE 5
            END,
            stock_value DESC,
            sku_id;
    """
    params = (
        limit,
        tenant_id,
        brand_id, brand_id,
        store_id, store_id,
        status, status,
        sku_id, sku_id,
    )
    return await execute_query(sql, params)


# ----------------------------------------------------------------------------
# vw_sku_velocity_segmented
# ----------------------------------------------------------------------------
async def fetch_velocity_segmentation(
    tenant_id: int,
    *,
    segment: str | None = None,
    brand_id: int | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    sql = """
        SELECT TOP (?)
            sku_id, sku_code, sku_name, brand_id, brand_name, category_id,
            units_8w, revenue_8w, weeks_with_sales, units_per_day_avg,
            velocity_segment
        FROM gold.vw_sku_velocity_segmented
        WHERE tenant_id = ?
          AND (? IS NULL OR velocity_segment = ?)
          AND (? IS NULL OR brand_id         = ?)
        ORDER BY units_8w DESC, sku_id;
    """
    params = (limit, tenant_id, segment, segment, brand_id, brand_id)
    return await execute_query(sql, params)


# ----------------------------------------------------------------------------
# vw_action_recommendation_priority
# ----------------------------------------------------------------------------
async def fetch_action_recommendations(
    tenant_id: int,
    *,
    scope: str | None = None,
    severity: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    # ``scope`` accepts the same domain as vw_active_alerts.[level]:
    # SKU / STORE / BRAND / EXECUTIVE.
    sql = """
        SELECT TOP (?)
            alert_id, iso_year_week, [level], alert_type, severity,
            store_id, sku_id, brand_id,
            sku_code, sku_name, brand_name, store_name,
            metric_value, threshold, suggested_action, estimated_impact_usd,
            severity_weight, priority_score, priority_rank
        FROM gold.vw_action_recommendation_priority
        WHERE tenant_id = ?
          AND (? IS NULL OR [level]  = ?)
          AND (? IS NULL OR severity = ?)
        ORDER BY priority_rank;
    """
    params = (limit, tenant_id, scope, scope, severity, severity)
    return await execute_query(sql, params)


# ----------------------------------------------------------------------------
# Executive summary helpers
# ----------------------------------------------------------------------------
async def fetch_tenant_weekly_totals(
    tenant_id: int, *, week_id: str | None = None
) -> dict[str, Any] | None:
    """Aggregate fact_sales_weekly to tenant level for a given week.

    If ``week_id`` is NULL we pick the latest iso_year_week present in
    fact_sales_weekly for this tenant. The latest-week lookup is done in a
    separate round-trip rather than as a CTE because pyodbc's NULL parameter
    binding interacts poorly with SQL Server's ISNULL type inference.
    """
    if week_id is None:
        latest = await execute_query(
            "SELECT MAX(iso_year_week) AS w FROM gold.fact_sales_weekly WHERE tenant_id = ?;",
            (tenant_id,),
        )
        if not latest or latest[0]["w"] is None:
            return None
        week_id = latest[0]["w"]

    sql = """
        SELECT
            ? AS iso_year_week,
            COUNT(*)                  AS rows_in_week,
            SUM(units_sold_net)       AS units_sold,
            SUM(revenue_net)          AS revenue,
            SUM(cogs)                 AS cogs,
            SUM(gross_margin)         AS gross_margin,
            CASE WHEN SUM(revenue_net) > 0
                 THEN CAST(SUM(gross_margin) / SUM(revenue_net) AS DECIMAL(9,4))
                 ELSE NULL END        AS gross_margin_pct
        FROM gold.fact_sales_weekly
        WHERE tenant_id = ? AND iso_year_week = ?;
    """
    rows = await execute_query(sql, (week_id, tenant_id, week_id))
    if not rows or rows[0]["rows_in_week"] == 0:
        return None
    return rows[0]


async def fetch_tenant_plan_totals(
    tenant_id: int, *, week_id: str
) -> dict[str, Any] | None:
    sql = """
        SELECT
            SUM(planned_units)   AS planned_units,
            SUM(planned_revenue) AS planned_revenue
        FROM gold.fact_sales_plan
        WHERE tenant_id = ? AND iso_year_week = ?;
    """
    rows = await execute_query(sql, (tenant_id, week_id))
    return rows[0] if rows else None


async def fetch_tenant_distinct_tickets(
    tenant_id: int, *, week_id: str
) -> int:
    """COUNT(DISTINCT factura.id) — tickets is a semi-additive metric in the
    fact, so we go to source to get the correct count."""
    sql = """
        SELECT COUNT(DISTINCT d.id) AS tickets
        FROM dbo.documento d
        JOIN gold.dim_date dd ON dd.[date] = d.fecha_emision
        WHERE d.id_empresa     = ?
          AND d.tipo_documento = 3
          AND d.estado         IN (1, 2)
          AND d.[delete]       = 0
          AND dd.iso_year_week = ?;
    """
    rows = await execute_query(sql, (tenant_id, week_id))
    return int(rows[0]["tickets"]) if rows else 0


# ----------------------------------------------------------------------------
# SKU detail
# ----------------------------------------------------------------------------
async def fetch_sku_master(tenant_id: int, sku_id: int) -> dict[str, Any] | None:
    sql = """
        SELECT
            sku_id, sku_code, sku_barcode, sku_name, is_service,
            category_id, subcategory_id, list_price, reorder_point,
            brand_id, brand_name, season_id, season_name
        FROM gold.dim_sku
        WHERE tenant_id = ? AND sku_id = ? AND is_active = 1;
    """
    rows = await execute_query(sql, (tenant_id, sku_id))
    return rows[0] if rows else None


async def fetch_sku_sales_8w(
    tenant_id: int, sku_id: int, *, store_id: int | None = None
) -> list[dict[str, Any]]:
    """Per-week sales of a SKU for the last 8 ISO weeks present in the fact."""
    sql = """
        ;WITH last8 AS (
            SELECT TOP (8) iso_year_week
            FROM gold.fact_sales_weekly
            WHERE tenant_id = ? AND sku_id = ?
              AND (? IS NULL OR store_id = ?)
            GROUP BY iso_year_week
            ORDER BY iso_year_week DESC
        )
        SELECT
            f.iso_year_week,
            SUM(f.units_sold_net) AS units_sold,
            SUM(f.revenue_net)    AS revenue,
            SUM(f.gross_margin)   AS gross_margin,
            SUM(f.tickets)        AS tickets_semiadd  -- semi-additive: see Phase 3 docs
        FROM gold.fact_sales_weekly f
        JOIN last8 w ON w.iso_year_week = f.iso_year_week
        WHERE f.tenant_id = ? AND f.sku_id = ?
          AND (? IS NULL OR f.store_id = ?)
        GROUP BY f.iso_year_week
        ORDER BY f.iso_year_week DESC;
    """
    params = (tenant_id, sku_id, store_id, store_id, tenant_id, sku_id, store_id, store_id)
    return await execute_query(sql, params)


async def fetch_sku_stock_current(
    tenant_id: int, sku_id: int, *, store_id: int | None = None
) -> list[dict[str, Any]]:
    sql = """
        ;WITH latest AS (
            SELECT MAX(iso_year_week) AS iso_year_week
            FROM gold.fact_stock_weekly WHERE tenant_id = ?
        )
        SELECT
            s.iso_year_week, s.store_id,
            s.stock_units, s.stock_value, s.unit_cost,
            s.has_zero_stock_flag, s.is_obsolete_flag,
            s.days_since_last_sale, s.days_since_last_movement,
            s.last_sale_date, s.last_movement_date
        FROM gold.fact_stock_weekly s
        JOIN latest l ON l.iso_year_week = s.iso_year_week
        WHERE s.tenant_id = ? AND s.sku_id = ?
          AND (? IS NULL OR s.store_id = ?)
        ORDER BY s.store_id;
    """
    params = (tenant_id, tenant_id, sku_id, store_id, store_id)
    return await execute_query(sql, params)


# ----------------------------------------------------------------------------
# compare_periods (dynamic metric/scope; both are enum-validated upstream)
# ----------------------------------------------------------------------------
def _scope_select(scope: str) -> tuple[str, str]:
    """Return (group_by_expr, select_label_join). Scope MUST be allowlisted."""
    if scope == "tenant":
        return ("0", "")  # 0 placeholder; we strip GROUP BY below
    if scope == "brand":
        return ("f.brand_id", "")
    if scope == "store":
        return ("f.store_id", "")
    raise ValueError(f"Unsupported scope: {scope!r}")  # safety net


async def fetch_compare_periods(
    tenant_id: int,
    *,
    metric: str,
    period_a: str,
    period_b: str,
    scope: str = "tenant",
) -> list[dict[str, Any]]:
    if metric not in COMPARE_METRICS:
        raise ValueError(f"metric {metric!r} not in allowlist")
    if scope not in COMPARE_SCOPES:
        raise ValueError(f"scope {scope!r} not in allowlist")

    if scope == "tenant":
        sql = f"""
            SELECT
                CAST(NULL AS BIGINT) AS scope_id,
                CAST(NULL AS NVARCHAR(120)) AS scope_label,
                SUM(CASE WHEN iso_year_week = ? THEN {metric} ELSE 0 END) AS value_a,
                SUM(CASE WHEN iso_year_week = ? THEN {metric} ELSE 0 END) AS value_b
            FROM gold.fact_sales_weekly
            WHERE tenant_id = ? AND iso_year_week IN (?, ?);
        """
        params = (period_a, period_b, tenant_id, period_a, period_b)
        return await execute_query(sql, params)

    if scope == "brand":
        sql = f"""
            SELECT
                ds.brand_id    AS scope_id,
                MAX(ds.brand_name) AS scope_label,
                SUM(CASE WHEN f.iso_year_week = ? THEN f.{metric} ELSE 0 END) AS value_a,
                SUM(CASE WHEN f.iso_year_week = ? THEN f.{metric} ELSE 0 END) AS value_b
            FROM gold.fact_sales_weekly f
            JOIN gold.dim_sku ds
                ON ds.tenant_id = f.tenant_id AND ds.sku_id = f.sku_id
            WHERE f.tenant_id = ? AND f.iso_year_week IN (?, ?)
            GROUP BY ds.brand_id;
        """
        params = (period_a, period_b, tenant_id, period_a, period_b)
        return await execute_query(sql, params)

    # scope == "store"
    sql = f"""
        SELECT
            f.store_id     AS scope_id,
            MAX(ds.store_name) AS scope_label,
            SUM(CASE WHEN f.iso_year_week = ? THEN f.{metric} ELSE 0 END) AS value_a,
            SUM(CASE WHEN f.iso_year_week = ? THEN f.{metric} ELSE 0 END) AS value_b
        FROM gold.fact_sales_weekly f
        LEFT JOIN gold.dim_store ds
            ON ds.tenant_id = f.tenant_id AND ds.store_id = f.store_id
        WHERE f.tenant_id = ? AND f.iso_year_week IN (?, ?)
        GROUP BY f.store_id;
    """
    params = (period_a, period_b, tenant_id, period_a, period_b)
    return await execute_query(sql, params)


# ----------------------------------------------------------------------------
# Monthly periodicity — vw_sales_monthly / vw_brand_performance_monthly /
# vw_store_dashboard_monthly  (sub-phase 4.7)
# ----------------------------------------------------------------------------

async def fetch_latest_month(tenant_id: int) -> str | None:
    """Return the latest year_month_iso (YYYY-MM) with sales data for the tenant."""
    rows = await execute_query(
        "SELECT MAX(year_month_iso) AS m FROM gold.vw_sales_monthly WHERE tenant_id = ?;",
        (tenant_id,),
    )
    return rows[0]["m"] if rows and rows[0]["m"] else None


async def fetch_monthly_totals(
    tenant_id: int,
    *,
    year_month: str | None = None,
    scope_brand_id: int | None = None,
    scope_store_id: int | None = None,
) -> dict[str, Any] | None:
    """Tenant-level (or brand/store-scoped) monthly totals from vw_sales_monthly.

    When year_month is None the latest month is returned.
    scope_brand_id and scope_store_id are mutually exclusive filters.
    """
    if year_month is None:
        year_month = await fetch_latest_month(tenant_id)
        if year_month is None:
            return None

    sql = """
        SELECT
            year_month_iso, month_id_iso,
            SUM(units_sold_net)  AS units_sold,
            SUM(revenue_net)     AS revenue,
            SUM(cogs)            AS cogs,
            SUM(gross_margin)    AS gross_margin,
            SUM(discount_amount) AS discount_amount,
            MAX(currency_code)   AS currency_code
        FROM gold.vw_sales_monthly
        WHERE tenant_id       = ?
          AND year_month_iso  = ?
          AND (? IS NULL OR brand_id = ?)
          AND (? IS NULL OR store_id = ?)
        GROUP BY year_month_iso, month_id_iso;
    """
    params = (
        tenant_id, year_month,
        scope_brand_id, scope_brand_id,
        scope_store_id, scope_store_id,
    )
    rows = await execute_query(sql, params)
    return rows[0] if rows else None


async def fetch_monthly_brand_performance(
    tenant_id: int,
    *,
    brand_id: int | None = None,
    year_month: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            year_month_iso, month_id_iso, brand_id, brand_name,
            units_sold, revenue, cogs, gross_margin, gross_margin_pct,
            planned_units, planned_revenue, units_vs_plan_pct, revenue_vs_plan_pct,
            stock_units, stock_value, skus_count, skus_zero_stock, skus_obsolete
        FROM gold.vw_brand_performance_monthly
        WHERE tenant_id = ?
          AND (? IS NULL OR brand_id       = ?)
          AND (? IS NULL OR year_month_iso = ?)
        ORDER BY year_month_iso DESC, revenue DESC, brand_id;
    """
    params = (tenant_id, brand_id, brand_id, year_month, year_month)
    return await execute_query(sql, params)


async def fetch_monthly_store_dashboard(
    tenant_id: int,
    *,
    store_id: int | None = None,
    year_month: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            year_month_iso, month_id_iso, store_id, store_code, store_name,
            block_AB, is_store_flag,
            units_sold, revenue, cogs, gross_margin, discount_amount,
            gross_margin_pct, tickets, avg_ticket,
            stock_units, stock_value, skus_in_store, skus_zero_stock, skus_obsolete
        FROM gold.vw_store_dashboard_monthly
        WHERE tenant_id = ?
          AND (? IS NULL OR store_id      = ?)
          AND (? IS NULL OR year_month_iso = ?)
        ORDER BY year_month_iso DESC, revenue DESC, store_id;
    """
    params = (tenant_id, store_id, store_id, year_month, year_month)
    return await execute_query(sql, params)


async def fetch_compare_periods_monthly(
    tenant_id: int,
    *,
    metric: str,
    period_a: str,
    period_b: str,
    scope: str = "tenant",
) -> list[dict[str, Any]]:
    """Monthly variant of fetch_compare_periods. Queries vw_sales_monthly with
    year_month_iso as the period column. metric and scope are enum-validated
    upstream; column name is injected via the same COMPARE_METRICS allowlist."""
    if metric not in COMPARE_METRICS:
        raise ValueError(f"metric {metric!r} not in allowlist")
    if scope not in COMPARE_SCOPES:
        raise ValueError(f"scope {scope!r} not in allowlist")

    if scope == "tenant":
        sql = f"""
            SELECT
                CAST(NULL AS BIGINT)       AS scope_id,
                CAST(NULL AS NVARCHAR(120)) AS scope_label,
                SUM(CASE WHEN year_month_iso = ? THEN {metric} ELSE 0 END) AS value_a,
                SUM(CASE WHEN year_month_iso = ? THEN {metric} ELSE 0 END) AS value_b
            FROM gold.vw_sales_monthly
            WHERE tenant_id = ? AND year_month_iso IN (?, ?);
        """
        params = (period_a, period_b, tenant_id, period_a, period_b)
        return await execute_query(sql, params)

    if scope == "brand":
        sql = f"""
            SELECT
                m.brand_id                 AS scope_id,
                MAX(ds.brand_name)         AS scope_label,
                SUM(CASE WHEN m.year_month_iso = ? THEN m.{metric} ELSE 0 END) AS value_a,
                SUM(CASE WHEN m.year_month_iso = ? THEN m.{metric} ELSE 0 END) AS value_b
            FROM gold.vw_sales_monthly m
            LEFT JOIN gold.dim_sku ds
                ON ds.tenant_id = m.tenant_id AND ds.brand_id = m.brand_id
               AND ds.is_active = 1
            WHERE m.tenant_id = ? AND m.year_month_iso IN (?, ?)
            GROUP BY m.brand_id;
        """
        params = (period_a, period_b, tenant_id, period_a, period_b)
        return await execute_query(sql, params)

    # scope == "store"
    sql = f"""
        SELECT
            m.store_id                 AS scope_id,
            MAX(ds.store_name)         AS scope_label,
            SUM(CASE WHEN m.year_month_iso = ? THEN m.{metric} ELSE 0 END) AS value_a,
            SUM(CASE WHEN m.year_month_iso = ? THEN m.{metric} ELSE 0 END) AS value_b
        FROM gold.vw_sales_monthly m
        LEFT JOIN gold.dim_store ds
            ON ds.tenant_id = m.tenant_id AND ds.store_id = m.store_id
        WHERE m.tenant_id = ? AND m.year_month_iso IN (?, ?)
        GROUP BY m.store_id;
    """
    params = (period_a, period_b, tenant_id, period_a, period_b)
    return await execute_query(sql, params)


# ----------------------------------------------------------------------------
# Week resolution helpers (used by composite briefing tools)
# ----------------------------------------------------------------------------
async def fetch_latest_week(
    tenant_id: int, *, store_id: int | None = None
) -> str | None:
    """Latest ISO week with sales for the tenant, optionally scoped to a store."""
    sql = """
        SELECT MAX(iso_year_week) AS w
        FROM gold.fact_sales_weekly
        WHERE tenant_id = ?
          AND (? IS NULL OR store_id = ?);
    """
    rows = await execute_query(sql, (tenant_id, store_id, store_id))
    return rows[0]["w"] if rows and rows[0]["w"] else None


# ----------------------------------------------------------------------------
# api_audit.ai_audit_log
# ----------------------------------------------------------------------------
async def fetch_audit_trail(
    tenant_id: int, request_id: str
) -> dict[str, Any] | None:
    sql = """
        SELECT
            CAST(request_id AS NVARCHAR(50))    AS request_id,
            CAST(conversation_id AS NVARCHAR(50)) AS conversation_id,
            tenant_id, user_id, user_role,
            CONVERT(NVARCHAR(30), timestamp_utc, 126) AS timestamp_utc,
            user_question, system_prompt_hash,
            tools_invoked, tool_responses_hash, final_response,
            tokens_input, tokens_output, cost_usd, duration_ms, status, error_msg
        FROM api_audit.ai_audit_log
        WHERE tenant_id = ? AND request_id = CAST(? AS UNIQUEIDENTIFIER);
    """
    rows = await execute_query(sql, (tenant_id, request_id))
    return rows[0] if rows else None
