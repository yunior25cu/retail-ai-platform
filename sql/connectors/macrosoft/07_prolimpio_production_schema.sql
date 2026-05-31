-- ============================================================
-- FASE 1 — TABLAS GOLD DE PRODUCCIÓN PROLIMPIO
-- Tenant: 100
-- Destino: pymeconta_local (schema gold)
-- Todas idempotentes (IF NOT EXISTS / IF NOT EXISTS column)
-- ============================================================

-- ────────────────────────────────────────────────────────────
-- 1. fact_demand_forecast
--    Output del modelo Prophet. Solo fechas futuras. predicted_units >= 0.
-- ────────────────────────────────────────────────────────────
IF OBJECT_ID('gold.fact_demand_forecast', 'U') IS NULL
CREATE TABLE gold.fact_demand_forecast (
    id                BIGINT        IDENTITY PRIMARY KEY,
    tenant_id         INT           NOT NULL,
    sku_code          NVARCHAR(50)  NOT NULL,
    forecast_date     DATE          NOT NULL,
    iso_year_week     NCHAR(8)      NOT NULL,
    predicted_units   INT           NOT NULL
                      CONSTRAINT chk_forecast_positive CHECK (predicted_units >= 0),
    model_run_date    DATE          NOT NULL,
    model_version     NVARCHAR(20)  NOT NULL DEFAULT '1.0',
    horizon_days      INT           NOT NULL DEFAULT 60,
    yhat_lower        INT           NULL,
    yhat_upper        INT           NULL,
    is_active         BIT           NOT NULL DEFAULT 1,
    created_at        DATETIME2     DEFAULT GETUTCDATE(),
    CONSTRAINT uq_forecast
        UNIQUE (tenant_id, sku_code, forecast_date, model_run_date)
);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('gold.fact_demand_forecast')
      AND name = 'ix_forecast_lookup'
)
CREATE INDEX ix_forecast_lookup
    ON gold.fact_demand_forecast (tenant_id, sku_code, forecast_date)
    WHERE is_active = 1;
GO

-- ────────────────────────────────────────────────────────────
-- 2. fact_production_plan_weekly
--    Resumen operativo semanal para la IA. Se recalcula cada lunes.
-- ────────────────────────────────────────────────────────────
IF OBJECT_ID('gold.fact_production_plan_weekly', 'U') IS NULL
CREATE TABLE gold.fact_production_plan_weekly (
    id                      BIGINT        IDENTITY PRIMARY KEY,
    tenant_id               INT           NOT NULL,
    sku_code                NVARCHAR(50)  NOT NULL,
    iso_year_week           NCHAR(8)      NOT NULL,
    predicted_units_week    INT           NOT NULL DEFAULT 0,
    predicted_units_30d     INT           NOT NULL DEFAULT 0,
    stock_current           INT           NOT NULL DEFAULT 0,
    stock_pending_billing   INT           NOT NULL DEFAULT 0,
    stock_final             INT           NOT NULL DEFAULT 0,
    units_to_produce        INT           NOT NULL DEFAULT 0,
    liters_to_produce       DECIMAL(12,2) NULL,
    days_of_coverage        DECIMAL(6,1)  NULL,
    is_critical             BIT           NOT NULL DEFAULT 0,
    has_component_shortage  BIT           NOT NULL DEFAULT 0,
    blocking_components     NVARCHAR(500) NULL,
    refreshed_at            DATETIME2     DEFAULT GETUTCDATE(),
    CONSTRAINT uq_plan_weekly
        UNIQUE (tenant_id, sku_code, iso_year_week)
);
GO

-- ────────────────────────────────────────────────────────────
-- 3. dim_recipe_granel
--    Nivel 1 — fórmulas químicas (graneles F1, F2, F3...)
--    Fuente: Recetas WHERE CODARTICULO LIKE 'F%' + RecetasLineas
-- ────────────────────────────────────────────────────────────
IF OBJECT_ID('gold.dim_recipe_granel', 'U') IS NULL
CREATE TABLE gold.dim_recipe_granel (
    id                  BIGINT        IDENTITY PRIMARY KEY,
    tenant_id           INT           NOT NULL,
    recipe_id           INT           NOT NULL,
    granel_sku          NVARCHAR(50)  NOT NULL,
    granel_name         NVARCHAR(200) NOT NULL,
    batch_liters        DECIMAL(12,2) NOT NULL,
    recipe_line         INT           NOT NULL,
    component_sku       NVARCHAR(50)  NOT NULL,
    component_name      NVARCHAR(200) NOT NULL,
    component_type      NVARCHAR(30)  NOT NULL,  -- 'quimico'|'envase'|'etiqueta'|'fragancia'
    qty_per_batch       DECIMAL(18,6) NOT NULL,
    qty_per_liter       DECIMAL(18,8) NOT NULL,
    unit_of_measure     NVARCHAR(20)  NOT NULL,
    cost_per_batch      DECIMAL(18,4) NULL,
    is_active           BIT           NOT NULL DEFAULT 1,
    CONSTRAINT uq_recipe_granel
        UNIQUE (tenant_id, recipe_id, recipe_line)
);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('gold.dim_recipe_granel')
      AND name = 'ix_recipe_granel_sku'
)
CREATE INDEX ix_recipe_granel_sku
    ON gold.dim_recipe_granel (tenant_id, granel_sku)
    WHERE is_active = 1;
GO

-- ────────────────────────────────────────────────────────────
-- 4. dim_recipe_product
--    Nivel 2 — productos envasados (CodArticulo NOT LIKE 'F%')
--    Fuente: Recetas + RecetasLineas de Macrosoft (no CSV)
-- ────────────────────────────────────────────────────────────
IF OBJECT_ID('gold.dim_recipe_product', 'U') IS NULL
CREATE TABLE gold.dim_recipe_product (
    id                  BIGINT        IDENTITY PRIMARY KEY,
    tenant_id           INT           NOT NULL,
    product_sku         NVARCHAR(50)  NOT NULL,
    product_name        NVARCHAR(200) NOT NULL,
    granel_sku          NVARCHAR(50)  NOT NULL,
    liters_per_unit     DECIMAL(10,4) NOT NULL,
    component_sku       NVARCHAR(50)  NOT NULL,
    component_name      NVARCHAR(200) NOT NULL,
    component_type      NVARCHAR(30)  NOT NULL,  -- 'quimico'|'envase'|'etiqueta'|'fragancia'|'granel'
    qty_per_unit        DECIMAL(18,6) NOT NULL DEFAULT 1,
    unit_of_measure     NVARCHAR(20)  NOT NULL DEFAULT 'Uni',
    is_active           BIT           NOT NULL DEFAULT 1,
    CONSTRAINT uq_recipe_product
        UNIQUE (tenant_id, product_sku, component_sku)
);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('gold.dim_recipe_product')
      AND name = 'ix_recipe_product_sku'
)
CREATE INDEX ix_recipe_product_sku
    ON gold.dim_recipe_product (tenant_id, product_sku)
    WHERE is_active = 1;
GO

-- ────────────────────────────────────────────────────────────
-- 5. fact_component_stock
--    Stock diario de MP, envases y graneles. Fuente: DOYSTOCKDP.
-- ────────────────────────────────────────────────────────────
IF OBJECT_ID('gold.fact_component_stock', 'U') IS NULL
CREATE TABLE gold.fact_component_stock (
    id                  BIGINT        IDENTITY PRIMARY KEY,
    tenant_id           INT           NOT NULL,
    component_sku       NVARCHAR(50)  NOT NULL,
    component_name      NVARCHAR(200) NOT NULL,
    component_type      NVARCHAR(30)  NOT NULL,  -- 'quimico'|'envase'|'etiqueta'|'fragancia'|'granel'
    store_code          NCHAR(1)      NOT NULL DEFAULT 'F',
    stock_units         DECIMAL(18,4) NOT NULL,
    stock_kg            DECIMAL(18,4) NULL,
    unit_of_measure     NVARCHAR(20)  NOT NULL,
    units_on_order      DECIMAL(18,4) NOT NULL DEFAULT 0,
    stock_effective     DECIMAL(18,4) NOT NULL DEFAULT 0,
    snapshot_date       DATE          NOT NULL,
    is_critical         BIT           NOT NULL DEFAULT 0,
    is_low              BIT           NOT NULL DEFAULT 0,
    stock_min           DECIMAL(18,4) NULL,
    CONSTRAINT uq_comp_stock
        UNIQUE (tenant_id, component_sku, store_code, snapshot_date)
);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('gold.fact_component_stock')
      AND name = 'ix_comp_stock_date'
)
CREATE INDEX ix_comp_stock_date
    ON gold.fact_component_stock (tenant_id, snapshot_date DESC);
GO

-- ────────────────────────────────────────────────────────────
-- 6. dim_reactor
--    Reactores de producción con capacidad en litros.
-- ────────────────────────────────────────────────────────────
IF OBJECT_ID('gold.dim_reactor', 'U') IS NULL
CREATE TABLE gold.dim_reactor (
    id                  BIGINT        IDENTITY PRIMARY KEY,
    tenant_id           INT           NOT NULL,
    reactor_code        NVARCHAR(20)  NOT NULL,
    reactor_name        NVARCHAR(100) NOT NULL,
    capacity_liters     DECIMAL(12,2) NOT NULL,
    reactor_type        NVARCHAR(20)  NOT NULL,
    is_active           BIT           NOT NULL DEFAULT 1,
    notes               NVARCHAR(500) NULL,
    CONSTRAINT uq_reactor UNIQUE (tenant_id, reactor_code)
);
GO

-- Seed con 4 reactores (R1/R2 = 200L, R3/R4 = 5000L) — idempotente
INSERT INTO gold.dim_reactor (tenant_id, reactor_code, reactor_name, capacity_liters, reactor_type)
SELECT v.tenant_id, v.code, v.name, v.cap, v.tipo
FROM (VALUES
    (100, 'R1', 'Reactor pequeño 1', 200.0,  'pequeno'),
    (100, 'R2', 'Reactor pequeño 2', 200.0,  'pequeno'),
    (100, 'R3', 'Reactor grande 1',  5000.0, 'grande'),
    (100, 'R4', 'Reactor grande 2',  5000.0, 'grande')
) v(tenant_id, code, name, cap, tipo)
WHERE NOT EXISTS (
    SELECT 1 FROM gold.dim_reactor
    WHERE tenant_id = 100
);
GO

-- ────────────────────────────────────────────────────────────
-- 7. fact_production_orders
--    Órdenes de producción ejecutadas. Fuente: Lineas2/Cabezal2, Documento='112'.
-- ────────────────────────────────────────────────────────────
IF OBJECT_ID('gold.fact_production_orders', 'U') IS NULL
CREATE TABLE gold.fact_production_orders (
    id                  BIGINT        IDENTITY PRIMARY KEY,
    tenant_id           INT           NOT NULL,
    production_date     DATE          NOT NULL,
    iso_year_week       NCHAR(8)      NOT NULL,
    sku_code            NVARCHAR(50)  NOT NULL,
    nro_doc             NVARCHAR(20)  NOT NULL,
    units_produced      DECIMAL(18,4) NOT NULL,
    liters_produced     DECIMAL(18,4) NULL,
    status              NVARCHAR(20)  NOT NULL DEFAULT 'ejecutado',
    operator            NVARCHAR(100) NULL,
    CONSTRAINT uq_prod_order
        UNIQUE (tenant_id, nro_doc, sku_code)
);
GO

-- ────────────────────────────────────────────────────────────
-- 8. fact_purchase_orders
--    OC de componentes y MP pendientes. Fuente: Lineas2/Cabezal2, Documento='26'.
-- ────────────────────────────────────────────────────────────
IF OBJECT_ID('gold.fact_purchase_orders', 'U') IS NULL
CREATE TABLE gold.fact_purchase_orders (
    id                  BIGINT        IDENTITY PRIMARY KEY,
    tenant_id           INT           NOT NULL,
    order_date          DATE          NOT NULL,
    component_sku       NVARCHAR(50)  NOT NULL,
    component_name      NVARCHAR(200) NOT NULL,
    nro_doc             NVARCHAR(20)  NOT NULL,
    units_ordered       DECIMAL(18,4) NOT NULL,
    units_received      DECIMAL(18,4) NOT NULL DEFAULT 0,
    units_pending       DECIMAL(18,4) NOT NULL,
    status              NVARCHAR(20)  NOT NULL,
    total_cost          DECIMAL(18,4) NULL,
    CONSTRAINT uq_po UNIQUE (tenant_id, nro_doc, component_sku)
);
GO

-- ────────────────────────────────────────────────────────────
-- 9. fact_component_stock_override
--    Overrides manuales de stock para componentes con valor -1
--    (negativo grande detectado en sp_refresh_component_stock).
--    Fuente: carga manual. PK (tenant_id, component_sku).
-- ────────────────────────────────────────────────────────────
IF OBJECT_ID('gold.fact_component_stock_override','U') IS NULL
CREATE TABLE gold.fact_component_stock_override (
    tenant_id       INT             NOT NULL,
    component_sku   NVARCHAR(50)    NOT NULL,
    stock_real      DECIMAL(18,4)   NOT NULL,
    source          NVARCHAR(100)   NOT NULL,
    override_date   DATE            NOT NULL,
    notes           NVARCHAR(500)   NULL,
    updated_by      NVARCHAR(100)   NULL,
    updated_at      DATETIME2       DEFAULT GETUTCDATE(),
    PRIMARY KEY (tenant_id, component_sku)
);
GO

-- ────────────────────────────────────────────────────────────
-- Columnas adicionales en gold.dim_sku (solo si no existen)
-- ────────────────────────────────────────────────────────────
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('gold.dim_sku')
      AND name = 'liters_per_unit'
)
BEGIN
    ALTER TABLE gold.dim_sku
    ADD liters_per_unit DECIMAL(10,4) NULL,
        liters_source   NVARCHAR(20)  NULL;
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('gold.dim_sku')
      AND name = 'family_code'
)
BEGIN
    ALTER TABLE gold.dim_sku
    ADD family_code  NVARCHAR(10) NULL,
        is_finished  BIT          NULL;
    -- family_code: '1.1' productos terminados | '3.1' MP/componentes | '2.3' graneles
    -- is_finished:  1 = producto terminado (1.1) | 0 = insumo/componente
END;
GO

-- ────────────────────────────────────────────────────────────
-- Verificación post-creación
-- ────────────────────────────────────────────────────────────
SELECT 'fact_demand_forecast'      AS tabla, COUNT(*) AS filas FROM gold.fact_demand_forecast
UNION ALL
SELECT 'fact_production_plan_weekly',         COUNT(*) FROM gold.fact_production_plan_weekly
UNION ALL
SELECT 'dim_recipe_granel',                   COUNT(*) FROM gold.dim_recipe_granel
UNION ALL
SELECT 'dim_recipe_product',                  COUNT(*) FROM gold.dim_recipe_product
UNION ALL
SELECT 'fact_component_stock',                COUNT(*) FROM gold.fact_component_stock
UNION ALL
SELECT 'dim_reactor',                         COUNT(*) FROM gold.dim_reactor
UNION ALL
SELECT 'fact_production_orders',              COUNT(*) FROM gold.fact_production_orders
UNION ALL
SELECT 'fact_purchase_orders',                COUNT(*) FROM gold.fact_purchase_orders
UNION ALL
SELECT 'fact_component_stock_override',       COUNT(*) FROM gold.fact_component_stock_override;
-- dim_reactor debe mostrar 4 filas: R1(200), R2(200), R3(5000), R4(5000)
