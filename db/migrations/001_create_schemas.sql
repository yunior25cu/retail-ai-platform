-- ============================================================
-- FASE 1 — DDL PostgreSQL
-- Base de datos: asistente-ia
-- Clientes industriales (Prolimpio tenant_id=24 y futuros)
-- ============================================================

-- ── Schema: auth ─────────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.tenants (
    id                  SERIAL PRIMARY KEY,
    name                VARCHAR(200) NOT NULL,
    slug                VARCHAR(100) NOT NULL UNIQUE,
    vertical            VARCHAR(50)  NOT NULL DEFAULT 'retail',
    platform_tenant_id  INT          NULL,
    is_active           BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS auth.users (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INT          NOT NULL REFERENCES auth.tenants(id),
    email               VARCHAR(200) NOT NULL UNIQUE,
    password_hash       VARCHAR(200) NOT NULL,
    role                VARCHAR(50)  NOT NULL,
    is_active           BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_login          TIMESTAMP WITH TIME ZONE NULL
);
CREATE INDEX IF NOT EXISTS ix_users_tenant ON auth.users(tenant_id);
CREATE INDEX IF NOT EXISTS ix_users_email  ON auth.users(email);

CREATE TABLE IF NOT EXISTS auth.refresh_tokens (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT      NOT NULL REFERENCES auth.users(id),
    token_hash  VARCHAR(200) NOT NULL UNIQUE,
    expires_at  TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    revoked     BOOLEAN     NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_refresh_tokens_user ON auth.refresh_tokens(user_id);

-- ── Schema: config ────────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS config;

CREATE TABLE IF NOT EXISTS config.tenant_config (
    id           SERIAL PRIMARY KEY,
    tenant_id    INT          NOT NULL,
    config_key   VARCHAR(100) NOT NULL,
    config_value TEXT         NOT NULL,
    updated_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(tenant_id, config_key)
);

-- ── Schema: audit ─────────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS audit.conversation_log (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       INT          NOT NULL,
    user_id         BIGINT       NULL,
    conversation_id VARCHAR(100) NOT NULL,
    role            VARCHAR(50)  NOT NULL,
    message_type    VARCHAR(20)  NOT NULL,
    message_text    TEXT         NOT NULL,
    tools_used      TEXT         NULL,
    tokens_used     INT          NULL,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_conv_log_tenant ON audit.conversation_log(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_conv_log_conv   ON audit.conversation_log(conversation_id);

-- ── Schema: gold_t24 (Prolimpio) ──────────────────────────────

CREATE SCHEMA IF NOT EXISTS gold_t24;

CREATE TABLE IF NOT EXISTS gold_t24.dim_sku (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       INT           NOT NULL DEFAULT 24,
    sku_code        VARCHAR(50)   NOT NULL,
    sku_name        VARCHAR(200)  NOT NULL,
    family_code     VARCHAR(10)   NULL,
    is_finished     BOOLEAN       NULL,
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    liters_per_unit NUMERIC(10,4) NULL,
    liters_source   VARCHAR(20)   NULL,
    stock_min_units NUMERIC(18,4) NULL,
    UNIQUE(tenant_id, sku_code)
);

CREATE TABLE IF NOT EXISTS gold_t24.dim_reactor (
    id              SERIAL PRIMARY KEY,
    tenant_id       INT           NOT NULL DEFAULT 24,
    reactor_code    VARCHAR(20)   NOT NULL,
    reactor_name    VARCHAR(100)  NOT NULL,
    capacity_liters NUMERIC(12,2) NULL,
    reactor_type    VARCHAR(20)   NOT NULL,
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    notes           VARCHAR(500)  NULL,
    UNIQUE(tenant_id, reactor_code)
);

CREATE TABLE IF NOT EXISTS gold_t24.dim_recipe_granel (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       INT           NOT NULL DEFAULT 24,
    recipe_id       INT           NOT NULL,
    granel_sku      VARCHAR(50)   NOT NULL,
    granel_name     VARCHAR(200)  NOT NULL,
    batch_liters    NUMERIC(12,2) NOT NULL,
    recipe_line     INT           NOT NULL,
    component_sku   VARCHAR(50)   NOT NULL,
    component_name  VARCHAR(200)  NOT NULL,
    component_type  VARCHAR(30)   NOT NULL,
    qty_per_batch   NUMERIC(18,6) NOT NULL,
    qty_per_liter   NUMERIC(18,8) NOT NULL,
    unit_of_measure VARCHAR(20)   NOT NULL,
    cost_per_batch  NUMERIC(18,4) NULL,
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    UNIQUE(tenant_id, recipe_id, recipe_line)
);
CREATE INDEX IF NOT EXISTS ix_recipe_granel_sku ON gold_t24.dim_recipe_granel(granel_sku);

CREATE TABLE IF NOT EXISTS gold_t24.dim_recipe_product (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       INT           NOT NULL DEFAULT 24,
    product_sku     VARCHAR(50)   NOT NULL,
    product_name    VARCHAR(200)  NOT NULL,
    granel_sku      VARCHAR(50)   NOT NULL,
    liters_per_unit NUMERIC(10,4) NOT NULL,
    component_sku   VARCHAR(50)   NOT NULL,
    component_name  VARCHAR(200)  NOT NULL,
    component_type  VARCHAR(30)   NOT NULL,
    qty_per_unit    NUMERIC(18,6) NOT NULL DEFAULT 1,
    unit_of_measure VARCHAR(20)   NOT NULL DEFAULT 'Uni',
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    UNIQUE(tenant_id, product_sku, component_sku)
);
CREATE INDEX IF NOT EXISTS ix_recipe_product_sku ON gold_t24.dim_recipe_product(product_sku);

CREATE TABLE IF NOT EXISTS gold_t24.fact_component_stock (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       INT           NOT NULL DEFAULT 24,
    component_sku   VARCHAR(50)   NOT NULL,
    component_name  VARCHAR(200)  NOT NULL,
    component_type  VARCHAR(30)   NOT NULL,
    store_code      CHAR(1)       NOT NULL DEFAULT 'F',
    stock_units     NUMERIC(18,4) NOT NULL,
    stock_kg        NUMERIC(18,4) NULL,
    unit_of_measure VARCHAR(20)   NOT NULL,
    units_on_order  NUMERIC(18,4) NOT NULL DEFAULT 0,
    stock_effective NUMERIC(18,4) NOT NULL DEFAULT 0,
    snapshot_date   DATE          NOT NULL,
    is_critical     BOOLEAN       NOT NULL DEFAULT FALSE,
    is_low          BOOLEAN       NOT NULL DEFAULT FALSE,
    stock_min       NUMERIC(18,4) NULL,
    UNIQUE(tenant_id, component_sku, store_code, snapshot_date)
);
CREATE INDEX IF NOT EXISTS ix_comp_stock_date
    ON gold_t24.fact_component_stock(tenant_id, snapshot_date DESC);

CREATE TABLE IF NOT EXISTS gold_t24.fact_component_stock_override (
    tenant_id     INT           NOT NULL DEFAULT 24,
    component_sku VARCHAR(50)   NOT NULL,
    stock_real    NUMERIC(18,4) NOT NULL,
    source        VARCHAR(100)  NOT NULL,
    override_date DATE          NOT NULL,
    notes         VARCHAR(500)  NULL,
    updated_by    VARCHAR(100)  NULL,
    updated_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY(tenant_id, component_sku)
);

CREATE TABLE IF NOT EXISTS gold_t24.fact_demand_forecast (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       INT           NOT NULL DEFAULT 24,
    sku_code        VARCHAR(50)   NOT NULL,
    forecast_date   DATE          NOT NULL,
    iso_year_week   CHAR(8)       NOT NULL,
    predicted_units INT           NOT NULL CHECK(predicted_units >= 0),
    model_run_date  DATE          NOT NULL,
    model_version   VARCHAR(20)   NOT NULL DEFAULT '1.0',
    horizon_days    INT           NOT NULL DEFAULT 60,
    yhat_lower      INT           NULL,
    yhat_upper      INT           NULL,
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(tenant_id, sku_code, forecast_date, model_run_date)
);
CREATE INDEX IF NOT EXISTS ix_forecast_lookup
    ON gold_t24.fact_demand_forecast(tenant_id, sku_code, forecast_date)
    WHERE is_active = TRUE;

CREATE TABLE IF NOT EXISTS gold_t24.fact_production_plan_weekly (
    id                     BIGSERIAL PRIMARY KEY,
    tenant_id              INT           NOT NULL DEFAULT 24,
    sku_code               VARCHAR(50)   NOT NULL,
    iso_year_week          CHAR(8)       NOT NULL,
    predicted_units_week   INT           NOT NULL DEFAULT 0,
    predicted_units_30d    INT           NOT NULL DEFAULT 0,
    stock_current          INT           NOT NULL DEFAULT 0,
    stock_pending_billing  INT           NOT NULL DEFAULT 0,
    stock_final            INT           NOT NULL DEFAULT 0,
    units_to_produce       INT           NOT NULL DEFAULT 0,
    liters_to_produce      NUMERIC(12,2) NULL,
    days_of_coverage       NUMERIC(6,1)  NULL,
    is_critical            BOOLEAN       NOT NULL DEFAULT FALSE,
    has_component_shortage BOOLEAN       NOT NULL DEFAULT FALSE,
    blocking_components    VARCHAR(500)  NULL,
    refreshed_at           TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(tenant_id, sku_code, iso_year_week)
);

CREATE TABLE IF NOT EXISTS gold_t24.fact_production_orders (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       INT           NOT NULL DEFAULT 24,
    production_date DATE          NOT NULL,
    iso_year_week   CHAR(8)       NOT NULL,
    sku_code        VARCHAR(50)   NOT NULL,
    nro_doc         VARCHAR(20)   NOT NULL,
    units_produced  NUMERIC(18,4) NOT NULL,
    liters_produced NUMERIC(18,4) NULL,
    status          VARCHAR(20)   NOT NULL DEFAULT 'ejecutado',
    operator        VARCHAR(100)  NULL,
    UNIQUE(tenant_id, nro_doc, sku_code)
);

CREATE TABLE IF NOT EXISTS gold_t24.fact_purchase_orders (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       INT           NOT NULL DEFAULT 24,
    order_date      DATE          NOT NULL,
    component_sku   VARCHAR(50)   NOT NULL,
    component_name  VARCHAR(200)  NOT NULL,
    nro_doc         VARCHAR(20)   NOT NULL,
    units_ordered   NUMERIC(18,4) NOT NULL,
    units_received  NUMERIC(18,4) NOT NULL DEFAULT 0,
    units_pending   NUMERIC(18,4) NOT NULL,
    status          VARCHAR(20)   NOT NULL,
    total_cost      NUMERIC(18,4) NULL,
    UNIQUE(tenant_id, nro_doc, component_sku)
);
