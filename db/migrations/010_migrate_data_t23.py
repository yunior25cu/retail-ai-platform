"""
010_migrate_data_t23.py

FASE 3 — Migración de datos tenant_id=23 (DEMO RETAIL CO, vertical retail)
pymeconta_local (SQL Server) -> asistente-ia (PostgreSQL).

Mismo patrón que 002_migrate_data_t24.py: DELETE + batch INSERT,
idempotente (re-ejecutable sin duplicar). Reporta conteos al final.

Tablas:
    dim_sku, dim_store, dim_category, dim_business_rules,
    fact_sales_weekly, fact_stock_weekly, fact_sales_plan

NO se migra:
    - dim_date         (se sembró en 008_create_retail_schemas.sql)
    - dim_brand_mapping / dim_season_mapping / dim_society_mapping /
      dim_store_classification / fact_stock_movements / fact_transfers
      (0 filas para tenant 23 en SS — sin nada que migrar)

Ejecutar: python db/migrations/010_migrate_data_t23.py
"""

import sys
from datetime import datetime, date

import pyodbc
import psycopg2
import psycopg2.extras

SQL_SERVER_CONN = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=Ryzen7PC\\SQLEXPRESS;DATABASE=pymeconta_local;"
    "Trusted_Connection=yes;"
)

PG_CONN = {
    "host": "localhost", "port": 5432,
    "dbname": "asistente-ia",
    "user": "postgres", "password": "postgres",
}

TENANT_ID = 23
SCHEMA = "gold_t23"


def migrate_table(ss, pg, table_name, select_sql, insert_sql):
    """Migra una tabla completa con DELETE + INSERT en lotes."""
    print(f"  -> {SCHEMA}.{table_name} ...", end=" ", flush=True)
    ss_cur = ss.cursor()
    pg_cur = pg.cursor()

    ss_cur.execute(select_sql)
    rows = ss_cur.fetchall()

    if not rows:
        print("sin datos en SS")
        return 0

    pg_cur.execute(f"DELETE FROM {SCHEMA}.{table_name} WHERE tenant_id = %s", (TENANT_ID,))

    # Convert pyodbc.Row -> tuple; PG psycopg2 acepta tuplas directamente
    data = [tuple(r) for r in rows]
    psycopg2.extras.execute_batch(pg_cur, insert_sql, data, page_size=500)
    pg.commit()

    print(f"OK {len(rows)} filas")
    return len(rows)


def run():
    print(f"\n=== Migración tenant {TENANT_ID} (retail) SS -> PG ===\n")
    ss = pyodbc.connect(SQL_SERVER_CONN)
    pg = psycopg2.connect(**PG_CONN)
    totals = {}

    try:
        # ── dim_sku ────────────────────────────────────────────────────
        totals["dim_sku"] = migrate_table(
            ss, pg, "dim_sku",
            """SELECT tenant_id, sku_id, sku_code, sku_barcode, sku_name,
                      is_service, category_id, subcategory_id,
                      unit_of_measure_id, product_type_id, list_price,
                      reorder_point, variant_parent_sku_id, brand_id,
                      brand_name, season_id, season_name, season_month,
                      is_active, etl_loaded_at, etl_batch_id,
                      etl_source_hash, liters_per_unit, liters_source,
                      family_code, is_finished
               FROM gold.dim_sku WHERE tenant_id = ?""".replace("?", str(TENANT_ID)),
            f"""INSERT INTO {SCHEMA}.dim_sku
                   (tenant_id, sku_id, sku_code, sku_barcode, sku_name,
                    is_service, category_id, subcategory_id,
                    unit_of_measure_id, product_type_id, list_price,
                    reorder_point, variant_parent_sku_id, brand_id,
                    brand_name, season_id, season_name, season_month,
                    is_active, etl_loaded_at, etl_batch_id,
                    etl_source_hash, liters_per_unit, liters_source,
                    family_code, is_finished)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        )

        # ── dim_store ──────────────────────────────────────────────────
        totals["dim_store"] = migrate_table(
            ss, pg, "dim_store",
            f"""SELECT tenant_id, store_id, store_code, store_name, is_main,
                       address, latitude, longitude, valuation_method_id,
                       is_store_flag, block_AB, region, society_id
                FROM gold.dim_store WHERE tenant_id = {TENANT_ID}""",
            f"""INSERT INTO {SCHEMA}.dim_store
                   (tenant_id, store_id, store_code, store_name, is_main,
                    address, latitude, longitude, valuation_method_id,
                    is_store_flag, block_ab, region, society_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        )

        # ── dim_category ───────────────────────────────────────────────
        totals["dim_category"] = migrate_table(
            ss, pg, "dim_category",
            f"""SELECT tenant_id, category_id, category_code, category_name,
                       parent_category_id, category_level, is_active,
                       etl_loaded_at, etl_batch_id, etl_source_hash
                FROM gold.dim_category WHERE tenant_id = {TENANT_ID}""",
            f"""INSERT INTO {SCHEMA}.dim_category
                   (tenant_id, category_id, category_code, category_name,
                    parent_category_id, category_level, is_active,
                    etl_loaded_at, etl_batch_id, etl_source_hash)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        )

        # ── dim_business_rules ────────────────────────────────────────
        # rule_id es BIGSERIAL en PG; lo sembramos con el valor de SS para
        # mantener referencias estables (las vistas filtran por rule_id > 0).
        totals["dim_business_rules"] = migrate_table(
            ss, pg, "dim_business_rules",
            f"""SELECT rule_id, tenant_id, brand_id, category_id,
                       season_month, coverage_min_days, coverage_max_days,
                       days_no_sale_obsolete, primary_action, discount_pct,
                       priority, is_active, created_at
                FROM gold.dim_business_rules WHERE tenant_id = {TENANT_ID}""",
            f"""INSERT INTO {SCHEMA}.dim_business_rules
                   (rule_id, tenant_id, brand_id, category_id,
                    season_month, coverage_min_days, coverage_max_days,
                    days_no_sale_obsolete, primary_action, discount_pct,
                    priority, is_active, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        )
        # Reset secuencia para futuros INSERTs
        with pg.cursor() as c:
            c.execute(f"""SELECT setval(pg_get_serial_sequence(
                '{SCHEMA}.dim_business_rules', 'rule_id'),
                COALESCE((SELECT MAX(rule_id) FROM {SCHEMA}.dim_business_rules), 1))""")
            pg.commit()

        # ── fact_sales_weekly ──────────────────────────────────────────
        totals["fact_sales_weekly"] = migrate_table(
            ss, pg, "fact_sales_weekly",
            f"""SELECT tenant_id, iso_year_week, store_id, sku_id, brand_id,
                       category_id, units_sold_gross, units_returned,
                       units_sold_net, revenue_gross, revenue_returned,
                       revenue_net, cogs, gross_margin, gross_margin_pct,
                       tickets, avg_ticket, discount_amount, currency_code,
                       etl_loaded_at, etl_batch_id
                FROM gold.fact_sales_weekly WHERE tenant_id = {TENANT_ID}""",
            f"""INSERT INTO {SCHEMA}.fact_sales_weekly
                   (tenant_id, iso_year_week, store_id, sku_id, brand_id,
                    category_id, units_sold_gross, units_returned,
                    units_sold_net, revenue_gross, revenue_returned,
                    revenue_net, cogs, gross_margin, gross_margin_pct,
                    tickets, avg_ticket, discount_amount, currency_code,
                    etl_loaded_at, etl_batch_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        )

        # ── fact_stock_weekly ──────────────────────────────────────────
        totals["fact_stock_weekly"] = migrate_table(
            ss, pg, "fact_stock_weekly",
            f"""SELECT tenant_id, iso_year_week, store_id, sku_id,
                       stock_units, stock_value, unit_cost, stock_min,
                       stock_max, has_zero_stock_flag, days_since_last_sale,
                       days_since_last_movement, last_sale_date,
                       last_movement_date, is_obsolete_flag, currency_code,
                       etl_loaded_at, etl_batch_id
                FROM gold.fact_stock_weekly WHERE tenant_id = {TENANT_ID}""",
            f"""INSERT INTO {SCHEMA}.fact_stock_weekly
                   (tenant_id, iso_year_week, store_id, sku_id,
                    stock_units, stock_value, unit_cost, stock_min,
                    stock_max, has_zero_stock_flag, days_since_last_sale,
                    days_since_last_movement, last_sale_date,
                    last_movement_date, is_obsolete_flag, currency_code,
                    etl_loaded_at, etl_batch_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        )

        # ── fact_sales_plan ────────────────────────────────────────────
        totals["fact_sales_plan"] = migrate_table(
            ss, pg, "fact_sales_plan",
            f"""SELECT tenant_id, iso_year_week, brand_id, store_id,
                       plan_version, planned_units, planned_revenue,
                       currency_code, created_at
                FROM gold.fact_sales_plan WHERE tenant_id = {TENANT_ID}""",
            f"""INSERT INTO {SCHEMA}.fact_sales_plan
                   (tenant_id, iso_year_week, brand_id, store_id,
                    plan_version, planned_units, planned_revenue,
                    currency_code, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        )

    finally:
        ss.close()
        pg.close()

    print("\n=== Totales ===")
    for t, n in totals.items():
        print(f"  {t:<25} {n:>8} filas")
    print(f"  {'TOTAL':<25} {sum(totals.values()):>8} filas\n")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)
