"""
FASE 2 — Migración de datos tenant_id=24 (Prolimpio)
pymeconta_local (SQL Server) -> asistente-ia (PostgreSQL)

Ejecutar: python db/migrations/002_migrate_data_t24.py
Requisito: psycopg2-binary instalado en el venv
"""

import sys
import pyodbc
import psycopg2
import psycopg2.extras

SQL_SERVER_CONN = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=.\\SQLEXPRESS;DATABASE=pymeconta_local;"
    "Trusted_Connection=yes;"
)

PG_CONN = {
    "host": "localhost", "port": 5432,
    "dbname": "asistente-ia",
    "user": "postgres", "password": "postgres",
}

TENANT_ID = 24


def migrate_table(ss, pg, table_name, select_sql, insert_sql, schema="gold_t24"):
    """Migra una tabla completa con DELETE + INSERT en lotes."""
    print(f"\n  -> {schema}.{table_name} ...", end=" ", flush=True)
    ss_cur = ss.cursor()
    pg_cur = pg.cursor()

    ss_cur.execute(select_sql)
    rows = ss_cur.fetchall()

    if not rows:
        print("sin datos")
        return 0

    # Borrar snapshot previo en destino (idempotente)
    pg_cur.execute(f"DELETE FROM {schema}.{table_name} WHERE tenant_id = %s", (TENANT_ID,))

    psycopg2.extras.execute_batch(pg_cur, insert_sql, rows, page_size=500)
    pg.commit()

    print(f"OK {len(rows)} filas")
    return len(rows)


def run():
    print("=" * 62)
    print("MIGRACIÓN tenant_id=24 -> asistente-ia (PostgreSQL)")
    print("=" * 62)

    ss = pyodbc.connect(SQL_SERVER_CONN, autocommit=True)
    pg = psycopg2.connect(**PG_CONN)
    totals = {}

    # ── 1. dim_sku (solo columnas de producción, sin retail)
    totals["dim_sku"] = migrate_table(ss, pg, "dim_sku",
        f"""SELECT tenant_id, sku_code, sku_name,
                   family_code, is_finished, is_active,
                   liters_per_unit, liters_source,
                   NULL AS stock_min_units
            FROM gold.dim_sku
            WHERE tenant_id = {TENANT_ID}""",
        """INSERT INTO gold_t24.dim_sku
           (tenant_id, sku_code, sku_name, family_code, is_finished,
            is_active, liters_per_unit, liters_source, stock_min_units)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (tenant_id, sku_code) DO UPDATE SET
             sku_name        = EXCLUDED.sku_name,
             family_code     = EXCLUDED.family_code,
             is_finished     = EXCLUDED.is_finished,
             liters_per_unit = EXCLUDED.liters_per_unit,
             liters_source   = EXCLUDED.liters_source"""
    )

    # ── 2. dim_reactor
    totals["dim_reactor"] = migrate_table(ss, pg, "dim_reactor",
        f"""SELECT tenant_id, reactor_code, reactor_name,
                   capacity_liters, reactor_type, is_active, notes
            FROM gold.dim_reactor WHERE tenant_id = {TENANT_ID}""",
        """INSERT INTO gold_t24.dim_reactor
           (tenant_id, reactor_code, reactor_name,
            capacity_liters, reactor_type, is_active, notes)
           VALUES (%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (tenant_id, reactor_code) DO UPDATE SET
             capacity_liters = EXCLUDED.capacity_liters,
             reactor_name    = EXCLUDED.reactor_name"""
    )

    # ── 3. dim_recipe_granel
    totals["dim_recipe_granel"] = migrate_table(ss, pg, "dim_recipe_granel",
        f"""SELECT tenant_id, recipe_id, granel_sku, granel_name,
                   batch_liters, recipe_line, component_sku, component_name,
                   component_type, qty_per_batch, qty_per_liter,
                   unit_of_measure, cost_per_batch, is_active
            FROM gold.dim_recipe_granel WHERE tenant_id = {TENANT_ID}""",
        """INSERT INTO gold_t24.dim_recipe_granel
           (tenant_id, recipe_id, granel_sku, granel_name,
            batch_liters, recipe_line, component_sku, component_name,
            component_type, qty_per_batch, qty_per_liter,
            unit_of_measure, cost_per_batch, is_active)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (tenant_id, recipe_id, recipe_line) DO NOTHING"""
    )

    # ── 4. dim_recipe_product
    totals["dim_recipe_product"] = migrate_table(ss, pg, "dim_recipe_product",
        f"""SELECT tenant_id, product_sku, product_name, granel_sku,
                   liters_per_unit, component_sku, component_name,
                   component_type, qty_per_unit, unit_of_measure, is_active
            FROM gold.dim_recipe_product WHERE tenant_id = {TENANT_ID}""",
        """INSERT INTO gold_t24.dim_recipe_product
           (tenant_id, product_sku, product_name, granel_sku,
            liters_per_unit, component_sku, component_name,
            component_type, qty_per_unit, unit_of_measure, is_active)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (tenant_id, product_sku, component_sku) DO NOTHING"""
    )

    # ── 5. fact_component_stock (snapshot más reciente)
    totals["fact_component_stock"] = migrate_table(ss, pg, "fact_component_stock",
        f"""SELECT tenant_id, component_sku, component_name,
                   component_type, store_code, stock_units, stock_kg,
                   unit_of_measure, units_on_order, stock_effective,
                   snapshot_date,
                   CAST(is_critical AS BIT),
                   CAST(is_low AS BIT),
                   stock_min
            FROM gold.fact_component_stock
            WHERE tenant_id = {TENANT_ID}
              AND snapshot_date = (
                SELECT MAX(snapshot_date)
                FROM gold.fact_component_stock
                WHERE tenant_id = {TENANT_ID}
              )""",
        """INSERT INTO gold_t24.fact_component_stock
           (tenant_id, component_sku, component_name,
            component_type, store_code, stock_units, stock_kg,
            unit_of_measure, units_on_order, stock_effective,
            snapshot_date, is_critical, is_low, stock_min)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (tenant_id, component_sku, store_code, snapshot_date)
           DO NOTHING"""
    )

    # ── 6. fact_component_stock_override
    totals["fact_component_stock_override"] = migrate_table(ss, pg, "fact_component_stock_override",
        f"""SELECT tenant_id, component_sku, stock_real,
                   source, override_date, notes, updated_by
            FROM gold.fact_component_stock_override
            WHERE tenant_id = {TENANT_ID}""",
        """INSERT INTO gold_t24.fact_component_stock_override
           (tenant_id, component_sku, stock_real,
            source, override_date, notes, updated_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (tenant_id, component_sku) DO UPDATE SET
             stock_real    = EXCLUDED.stock_real,
             override_date = EXCLUDED.override_date,
             source        = EXCLUDED.source"""
    )

    # ── 7. fact_demand_forecast (solo activas)
    totals["fact_demand_forecast"] = migrate_table(ss, pg, "fact_demand_forecast",
        f"""SELECT tenant_id, sku_code, forecast_date, iso_year_week,
                   predicted_units, model_run_date, model_version,
                   horizon_days, yhat_lower, yhat_upper,
                   CAST(is_active AS BIT)
            FROM gold.fact_demand_forecast
            WHERE tenant_id = {TENANT_ID} AND is_active = 1""",
        """INSERT INTO gold_t24.fact_demand_forecast
           (tenant_id, sku_code, forecast_date, iso_year_week,
            predicted_units, model_run_date, model_version,
            horizon_days, yhat_lower, yhat_upper, is_active)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (tenant_id, sku_code, forecast_date, model_run_date)
           DO NOTHING"""
    )

    # ── 8. fact_production_plan_weekly
    totals["fact_production_plan_weekly"] = migrate_table(ss, pg, "fact_production_plan_weekly",
        f"""SELECT tenant_id, sku_code, iso_year_week,
                   predicted_units_week, predicted_units_30d,
                   stock_current, stock_pending_billing, stock_final,
                   units_to_produce, liters_to_produce, days_of_coverage,
                   CAST(is_critical AS BIT),
                   CAST(has_component_shortage AS BIT),
                   blocking_components
            FROM gold.fact_production_plan_weekly
            WHERE tenant_id = {TENANT_ID}""",
        """INSERT INTO gold_t24.fact_production_plan_weekly
           (tenant_id, sku_code, iso_year_week,
            predicted_units_week, predicted_units_30d,
            stock_current, stock_pending_billing, stock_final,
            units_to_produce, liters_to_produce, days_of_coverage,
            is_critical, has_component_shortage, blocking_components)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (tenant_id, sku_code, iso_year_week) DO NOTHING"""
    )

    # ── 9. fact_production_orders (vacío — se migra igual por completitud)
    totals["fact_production_orders"] = migrate_table(ss, pg, "fact_production_orders",
        f"""SELECT tenant_id, production_date, iso_year_week,
                   sku_code, nro_doc, units_produced,
                   liters_produced, status, operator
            FROM gold.fact_production_orders
            WHERE tenant_id = {TENANT_ID}""",
        """INSERT INTO gold_t24.fact_production_orders
           (tenant_id, production_date, iso_year_week,
            sku_code, nro_doc, units_produced,
            liters_produced, status, operator)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (tenant_id, nro_doc, sku_code) DO NOTHING"""
    )

    # ── 10. fact_purchase_orders
    totals["fact_purchase_orders"] = migrate_table(ss, pg, "fact_purchase_orders",
        f"""SELECT tenant_id, order_date, component_sku,
                   component_name, nro_doc, units_ordered,
                   units_received, units_pending, status, total_cost
            FROM gold.fact_purchase_orders
            WHERE tenant_id = {TENANT_ID}""",
        """INSERT INTO gold_t24.fact_purchase_orders
           (tenant_id, order_date, component_sku,
            component_name, nro_doc, units_ordered,
            units_received, units_pending, status, total_cost)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (tenant_id, nro_doc, component_sku) DO NOTHING"""
    )

    # ── 11. auth.tenants seed
    print("\n  -> auth.tenants seed ...", end=" ", flush=True)
    pg_cur = pg.cursor()
    pg_cur.execute("""
        INSERT INTO auth.tenants (name, slug, vertical, platform_tenant_id, is_active)
        VALUES ('Prolimpio', 'prolimpio', 'produccion', 24, TRUE)
        ON CONFLICT (slug) DO UPDATE SET
            vertical           = EXCLUDED.vertical,
            platform_tenant_id = EXCLUDED.platform_tenant_id
    """)
    pg.commit()
    print("OK")

    # ── 12. config.tenant_config seed
    print("  -> config.tenant_config seed ...", end=" ", flush=True)
    configs = [
        (24, "vertical",    "produccion"),
        (24, "memory",      "3"),
        (24, "rate_limit",  "100"),
        (24, "suggestions", "true"),
    ]
    psycopg2.extras.execute_batch(pg_cur, """
        INSERT INTO config.tenant_config (tenant_id, config_key, config_value)
        VALUES (%s, %s, %s)
        ON CONFLICT (tenant_id, config_key) DO UPDATE SET
            config_value = EXCLUDED.config_value
    """, configs)
    pg.commit()
    print("OK")

    ss.close()
    pg.close()

    # ── Resumen
    print("\n" + "=" * 62)
    print("RESUMEN")
    print("=" * 62)
    for tabla, filas in totals.items():
        print(f"  {tabla:<42} {filas:>6} filas")
    print(f"\n  Total datos: {sum(totals.values())} filas")
    print("=" * 62)


if __name__ == "__main__":
    run()
