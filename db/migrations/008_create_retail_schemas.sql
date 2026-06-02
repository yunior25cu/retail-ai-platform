/* ============================================================
 * 008_create_retail_schemas.sql
 *
 * Crea el schema `gold_t23` en PostgreSQL con las 8 tablas que
 * usa el vertical retail. Mismo modelo que `gold.*` en SQL Server
 * pero con tipos PG correctos. NO datos — la carga la hace
 * 010_migrate_data_t23.py.
 *
 * Sembramos dim_date acá porque es compartida y no es tenant-specific:
 * un generate_series 2020-01-01 .. 2030-12-31.
 *
 * Idempotente: CREATE SCHEMA IF NOT EXISTS + CREATE TABLE IF NOT EXISTS.
 * ============================================================ */

CREATE SCHEMA IF NOT EXISTS gold_t23;

-- ── dim_date ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gold_t23.dim_date (
    date_id          INT          PRIMARY KEY,
    date             DATE         NOT NULL UNIQUE,
    year             INT          NOT NULL,
    quarter          SMALLINT     NOT NULL,
    month            SMALLINT     NOT NULL,
    iso_week         SMALLINT     NOT NULL,
    iso_year         INT          NOT NULL,
    iso_year_week    CHAR(8)      NOT NULL,
    day_of_week      SMALLINT     NOT NULL,
    is_weekend       BOOLEAN      NOT NULL,
    week_start_date  DATE         NOT NULL,
    week_end_date    DATE         NOT NULL,
    season_id        INT          NOT NULL,
    season_month     SMALLINT     NULL,
    year_month_iso   CHAR(7)      NULL,
    month_id_iso     INT          NULL
);
CREATE INDEX IF NOT EXISTS ix_dim_date_iso_week ON gold_t23.dim_date (iso_year_week);
CREATE INDEX IF NOT EXISTS ix_dim_date_ym       ON gold_t23.dim_date (year_month_iso);

-- Seed dim_date 2020-2030 (idempotente con ON CONFLICT)
INSERT INTO gold_t23.dim_date (
    date_id, date, year, quarter, month, iso_week, iso_year, iso_year_week,
    day_of_week, is_weekend, week_start_date, week_end_date,
    season_id, season_month, year_month_iso, month_id_iso
)
SELECT
    CAST(TO_CHAR(d, 'YYYYMMDD') AS INT) AS date_id,
    d::date,
    EXTRACT(YEAR FROM d)::int,
    EXTRACT(QUARTER FROM d)::smallint,
    EXTRACT(MONTH FROM d)::smallint,
    EXTRACT(WEEK FROM d)::smallint,
    EXTRACT(ISOYEAR FROM d)::int,
    TO_CHAR(d, 'IYYY-"W"IW') AS iso_year_week,
    EXTRACT(ISODOW FROM d)::smallint AS day_of_week,
    (EXTRACT(ISODOW FROM d) IN (6,7))                AS is_weekend,
    (d - ((EXTRACT(ISODOW FROM d) - 1)::int) * INTERVAL '1 day')::date AS week_start_date,
    (d + (7 - EXTRACT(ISODOW FROM d))::int * INTERVAL '1 day')::date    AS week_end_date,
    EXTRACT(MONTH FROM d)::int     AS season_id,
    EXTRACT(MONTH FROM d)::smallint AS season_month,
    TO_CHAR(d, 'YYYY-MM')          AS year_month_iso,
    (EXTRACT(YEAR FROM d) * 100 + EXTRACT(MONTH FROM d))::int AS month_id_iso
FROM generate_series('2020-01-01'::date, '2030-12-31'::date, '1 day') AS d
ON CONFLICT (date_id) DO NOTHING;


-- ── dim_sku ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gold_t23.dim_sku (
    tenant_id              BIGINT       NOT NULL,
    sku_id                 BIGINT       NOT NULL,
    sku_code               VARCHAR(255) NOT NULL,
    sku_barcode            VARCHAR(255) NULL,
    sku_name               VARCHAR(255) NOT NULL,
    is_service             BOOLEAN      NOT NULL,
    category_id            BIGINT       NULL,
    subcategory_id         BIGINT       NULL,
    unit_of_measure_id     BIGINT       NULL,
    product_type_id        BIGINT       NULL,
    list_price             NUMERIC(18,4) NULL,
    reorder_point          NUMERIC(18,4) NULL,
    variant_parent_sku_id  BIGINT       NULL,
    brand_id               BIGINT       NOT NULL,
    brand_name             VARCHAR(120) NOT NULL,
    season_id              INT          NOT NULL,
    season_name            VARCHAR(50)  NOT NULL,
    season_month           SMALLINT     NULL,
    is_active              BOOLEAN      NOT NULL,
    etl_loaded_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    etl_batch_id           UUID         NULL,
    etl_source_hash        BYTEA        NULL,
    liters_per_unit        NUMERIC(10,4) NULL,
    liters_source          VARCHAR(20)  NULL,
    family_code            VARCHAR(10)  NULL,
    is_finished            BOOLEAN      NULL,
    CONSTRAINT pk_dim_sku_t23 PRIMARY KEY (tenant_id, sku_id)
);
CREATE INDEX IF NOT EXISTS ix_dim_sku_t23_brand   ON gold_t23.dim_sku (tenant_id, brand_id);
CREATE INDEX IF NOT EXISTS ix_dim_sku_t23_active  ON gold_t23.dim_sku (tenant_id, is_active);

-- ── dim_store ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gold_t23.dim_store (
    tenant_id          BIGINT       NOT NULL,
    store_id           BIGINT       NOT NULL,
    store_code         VARCHAR(255) NOT NULL,
    store_name         VARCHAR(255) NOT NULL,
    is_main            BOOLEAN      NOT NULL,
    address            TEXT         NULL,
    latitude           DOUBLE PRECISION NULL,
    longitude          DOUBLE PRECISION NULL,
    valuation_method_id BIGINT      NULL,
    is_store_flag      BOOLEAN      NOT NULL,
    block_ab           VARCHAR(20)  NOT NULL DEFAULT 'A',
    region             VARCHAR(50)  NOT NULL DEFAULT 'centro',
    society_id         INT          NOT NULL DEFAULT 0,
    CONSTRAINT pk_dim_store_t23 PRIMARY KEY (tenant_id, store_id)
);

-- ── dim_category ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gold_t23.dim_category (
    tenant_id          BIGINT       NOT NULL,
    category_id        BIGINT       NOT NULL,
    category_code      VARCHAR(255) NOT NULL,
    category_name      VARCHAR(255) NOT NULL,
    parent_category_id BIGINT       NULL,
    category_level     SMALLINT     NOT NULL,
    is_active          BOOLEAN      NOT NULL,
    etl_loaded_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    etl_batch_id       UUID         NULL,
    etl_source_hash    BYTEA        NULL,
    CONSTRAINT pk_dim_category_t23 PRIMARY KEY (tenant_id, category_id)
);

-- ── dim_business_rules ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gold_t23.dim_business_rules (
    rule_id              BIGSERIAL PRIMARY KEY,
    tenant_id            BIGINT       NOT NULL,
    brand_id             BIGINT       NOT NULL,
    category_id          BIGINT       NOT NULL,
    season_month         SMALLINT     NULL,
    coverage_min_days    INT          NOT NULL,
    coverage_max_days    INT          NOT NULL,
    days_no_sale_obsolete INT         NOT NULL,
    primary_action       VARCHAR(30)  NOT NULL,
    discount_pct         NUMERIC(9,4) NULL,
    priority             INT          NOT NULL,
    is_active            BOOLEAN      NOT NULL,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_business_rules_t23
    ON gold_t23.dim_business_rules (tenant_id, brand_id, category_id, priority);

-- ── fact_sales_weekly ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gold_t23.fact_sales_weekly (
    tenant_id         BIGINT       NOT NULL,
    iso_year_week     CHAR(8)      NOT NULL,
    store_id          BIGINT       NOT NULL,
    sku_id            BIGINT       NOT NULL,
    brand_id          BIGINT       NOT NULL,
    category_id       BIGINT       NOT NULL,
    units_sold_gross  NUMERIC(18,4) NOT NULL,
    units_returned    NUMERIC(18,4) NOT NULL,
    units_sold_net    NUMERIC(18,4) NOT NULL,
    revenue_gross     NUMERIC(18,4) NOT NULL,
    revenue_returned  NUMERIC(18,4) NOT NULL,
    revenue_net       NUMERIC(18,4) NOT NULL,
    cogs              NUMERIC(18,4) NOT NULL,
    gross_margin      NUMERIC(18,4) NOT NULL,
    gross_margin_pct  NUMERIC(9,4) NULL,
    tickets           INT          NOT NULL,
    avg_ticket        NUMERIC(18,4) NULL,
    discount_amount   NUMERIC(18,4) NOT NULL,
    currency_code     VARCHAR(3)   NOT NULL,
    etl_loaded_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    etl_batch_id      UUID         NULL,
    CONSTRAINT pk_fact_sales_weekly_t23 PRIMARY KEY (tenant_id, iso_year_week, store_id, sku_id)
);
CREATE INDEX IF NOT EXISTS ix_fact_sales_weekly_t23_brand
    ON gold_t23.fact_sales_weekly (tenant_id, iso_year_week, brand_id);

-- ── fact_stock_weekly ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gold_t23.fact_stock_weekly (
    tenant_id               BIGINT       NOT NULL,
    iso_year_week           CHAR(8)      NOT NULL,
    store_id                BIGINT       NOT NULL,
    sku_id                  BIGINT       NOT NULL,
    stock_units             NUMERIC(18,4) NOT NULL,
    stock_value             NUMERIC(18,4) NOT NULL,
    unit_cost               NUMERIC(18,4) NOT NULL,
    stock_min               NUMERIC(18,4) NULL,
    stock_max               NUMERIC(18,4) NULL,
    has_zero_stock_flag     BOOLEAN      NOT NULL,
    days_since_last_sale    INT          NULL,
    days_since_last_movement INT         NULL,
    last_sale_date          DATE         NULL,
    last_movement_date      DATE         NULL,
    is_obsolete_flag        BOOLEAN      NOT NULL,
    currency_code           VARCHAR(3)   NOT NULL,
    etl_loaded_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    etl_batch_id            UUID         NULL,
    CONSTRAINT pk_fact_stock_weekly_t23 PRIMARY KEY (tenant_id, iso_year_week, store_id, sku_id)
);

-- ── fact_sales_plan ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gold_t23.fact_sales_plan (
    tenant_id        BIGINT       NOT NULL,
    iso_year_week    CHAR(8)      NOT NULL,
    brand_id         BIGINT       NOT NULL,
    store_id         BIGINT       NOT NULL,
    plan_version     VARCHAR(20)  NOT NULL,
    planned_units    NUMERIC(18,4) NOT NULL,
    planned_revenue  NUMERIC(18,4) NOT NULL,
    currency_code    VARCHAR(3)   NOT NULL,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_fact_sales_plan_t23
        PRIMARY KEY (tenant_id, iso_year_week, brand_id, store_id, plan_version)
);
