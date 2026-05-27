/* ============================================================
 * 03_enrichment_tables.sql  (originally: block_3)
 * Purpose : MANUAL enrichment tables (data not present in source ERP).
 *           Brand, season, store classification, society, business rules,
 *           sales plan. Each table includes a sentinel row (tenant_id=0)
 *           for COALESCE-based defaults in downstream views.
 * Depends : 01_schema_and_logging.sql
 * Frequency: once on deploy (structure). Data loaded via seed procs
 *            (04_seeding_procs.sql) or admin UI.
 * ============================================================ */

------------------------------------------------------------------
-- dim_brand_mapping : SKU -> brand mapping per tenant
------------------------------------------------------------------
IF OBJECT_ID('gold.dim_brand_mapping','U') IS NOT NULL DROP TABLE gold.dim_brand_mapping;
GO
CREATE TABLE gold.dim_brand_mapping (
    tenant_id       BIGINT          NOT NULL,
    sku_code        NVARCHAR(255)   NOT NULL,
    brand_id        BIGINT          NOT NULL,
    brand_name      NVARCHAR(120)   NOT NULL,
    business_type   NVARCHAR(50)    NOT NULL CONSTRAINT df_brand_biztype DEFAULT N'RETAIL', -- RETAIL/WHOLESALE/SERVICE
    created_at      DATETIME2(3)    NOT NULL CONSTRAINT df_brand_created DEFAULT SYSUTCDATETIME(),
    updated_at      DATETIME2(3)    NOT NULL CONSTRAINT df_brand_updated DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_dim_brand_mapping PRIMARY KEY CLUSTERED (tenant_id, sku_code)
);
CREATE INDEX ix_brand_mapping_brand ON gold.dim_brand_mapping (tenant_id, brand_id);
GO
INSERT INTO gold.dim_brand_mapping (tenant_id, sku_code, brand_id, brand_name, business_type)
VALUES (0, N'__SENTINEL__', 0, N'SIN MARCA', N'NONE');
GO

------------------------------------------------------------------
-- dim_season_mapping : SKU -> active season(s)
------------------------------------------------------------------
IF OBJECT_ID('gold.dim_season_mapping','U') IS NOT NULL DROP TABLE gold.dim_season_mapping;
GO
CREATE TABLE gold.dim_season_mapping (
    tenant_id           BIGINT         NOT NULL,
    sku_code            NVARCHAR(255)  NOT NULL,
    season_id           INT            NOT NULL,
    season_name         NVARCHAR(50)   NOT NULL,
    season_start_date   DATE           NOT NULL,
    season_end_date     DATE           NOT NULL,
    season_month        TINYINT        NULL,
    created_at          DATETIME2(3)   NOT NULL CONSTRAINT df_season_created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_dim_season_mapping PRIMARY KEY CLUSTERED (tenant_id, sku_code, season_id),
    CONSTRAINT ck_season_dates CHECK (season_end_date >= season_start_date)
);
CREATE INDEX ix_season_mapping_season ON gold.dim_season_mapping (tenant_id, season_id);
GO
INSERT INTO gold.dim_season_mapping
    (tenant_id, sku_code, season_id, season_name, season_start_date, season_end_date, season_month)
VALUES (0, N'__SENTINEL__', 0, N'SIN TEMPORADA', '1900-01-01', '2999-12-31', NULL);
GO

------------------------------------------------------------------
-- dim_store_classification : store-level metadata (retail flag, block, region)
------------------------------------------------------------------
IF OBJECT_ID('gold.dim_store_classification','U') IS NOT NULL DROP TABLE gold.dim_store_classification;
GO
CREATE TABLE gold.dim_store_classification (
    tenant_id       BIGINT          NOT NULL,
    store_id        BIGINT          NOT NULL,
    is_store_flag   BIT             NOT NULL CONSTRAINT df_storecls_isstore DEFAULT 0, -- 1=retail store, 0=warehouse
    block_AB        NVARCHAR(20)    NOT NULL CONSTRAINT df_storecls_block   DEFAULT N'NO CLASIFICADO',
    region          NVARCHAR(50)    NOT NULL CONSTRAINT df_storecls_region  DEFAULT N'NO CLASIFICADO',
    store_format    NVARCHAR(50)    NULL,
    created_at      DATETIME2(3)    NOT NULL CONSTRAINT df_storecls_created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_dim_store_classification PRIMARY KEY CLUSTERED (tenant_id, store_id)
);
CREATE INDEX ix_storecls_block ON gold.dim_store_classification (tenant_id, block_AB);
GO
INSERT INTO gold.dim_store_classification (tenant_id, store_id, is_store_flag, block_AB, region)
VALUES (0, 0, 0, N'NO CLASIFICADO', N'NO CLASIFICADO');
GO

------------------------------------------------------------------
-- dim_society_mapping : tenant -> legal entity mapping
------------------------------------------------------------------
IF OBJECT_ID('gold.dim_society_mapping','U') IS NOT NULL DROP TABLE gold.dim_society_mapping;
GO
CREATE TABLE gold.dim_society_mapping (
    tenant_id        BIGINT         NOT NULL,
    society_id       INT            NOT NULL,
    society_name     NVARCHAR(120)  NOT NULL,
    society_rut      NVARCHAR(50)   NULL,
    parent_group_id  INT            NULL,
    created_at       DATETIME2(3)   NOT NULL CONSTRAINT df_society_created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_dim_society_mapping PRIMARY KEY CLUSTERED (tenant_id)
);
GO
INSERT INTO gold.dim_society_mapping (tenant_id, society_id, society_name)
VALUES (0, 0, N'NO ASIGNADA');
GO

------------------------------------------------------------------
-- dim_business_rules : coverage/obsolescence/action rules with priority resolution
------------------------------------------------------------------
IF OBJECT_ID('gold.dim_business_rules','U') IS NOT NULL DROP TABLE gold.dim_business_rules;
GO
CREATE TABLE gold.dim_business_rules (
    rule_id                 BIGINT IDENTITY(1,1) NOT NULL,
    tenant_id               BIGINT         NOT NULL,
    brand_id                BIGINT         NOT NULL CONSTRAINT df_rules_brand DEFAULT 0,
    category_id             BIGINT         NOT NULL CONSTRAINT df_rules_cat   DEFAULT 0,
    season_month            TINYINT        NULL,
    coverage_min_days       INT            NOT NULL,
    coverage_max_days       INT            NOT NULL,
    days_no_sale_obsolete   INT            NOT NULL,
    primary_action          NVARCHAR(30)   NOT NULL,
    discount_pct            DECIMAL(9,4)   NULL,
    priority                INT            NOT NULL CONSTRAINT df_rules_prio DEFAULT 100,
    is_active               BIT            NOT NULL CONSTRAINT df_rules_active DEFAULT 1,
    created_at              DATETIME2(3)   NOT NULL CONSTRAINT df_rules_created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_dim_business_rules PRIMARY KEY CLUSTERED (rule_id),
    CONSTRAINT ck_rules_action CHECK (primary_action IN (N'REPONER',N'TRANSFERIR',N'LIQUIDAR',N'AJUSTAR_PRECIO')),
    CONSTRAINT ck_rules_coverage CHECK (coverage_max_days >= coverage_min_days)
);
CREATE INDEX ix_rules_lookup ON gold.dim_business_rules (tenant_id, brand_id, category_id, season_month, is_active);
GO
SET IDENTITY_INSERT gold.dim_business_rules ON;
INSERT INTO gold.dim_business_rules
    (rule_id, tenant_id, brand_id, category_id, season_month, coverage_min_days, coverage_max_days,
     days_no_sale_obsolete, primary_action, discount_pct, priority, is_active)
VALUES
    (0, 0, 0, 0, NULL, 0, 999, 9999, N'REPONER', NULL, 999, 0);  -- inactive sentinel
SET IDENTITY_INSERT gold.dim_business_rules OFF;
GO

------------------------------------------------------------------
-- fact_sales_plan : manually loaded (or derived) weekly sales plan per brand/store
------------------------------------------------------------------
IF OBJECT_ID('gold.fact_sales_plan','U') IS NOT NULL DROP TABLE gold.fact_sales_plan;
GO
CREATE TABLE gold.fact_sales_plan (
    tenant_id        BIGINT         NOT NULL,
    iso_year_week    CHAR(8)        NOT NULL,
    brand_id         BIGINT         NOT NULL,
    store_id         BIGINT         NOT NULL CONSTRAINT df_plan_store DEFAULT 0, -- 0 = aggregate (all stores)
    plan_version     NVARCHAR(20)   NOT NULL CONSTRAINT df_plan_ver   DEFAULT N'v1-baseline',
    planned_units    DECIMAL(18,4)  NOT NULL,
    planned_revenue  DECIMAL(18,4)  NOT NULL,
    currency_code    NVARCHAR(3)    NOT NULL CONSTRAINT df_plan_ccy   DEFAULT N'UYU',
    created_at       DATETIME2(3)   NOT NULL CONSTRAINT df_plan_created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_fact_sales_plan PRIMARY KEY CLUSTERED (tenant_id, iso_year_week, brand_id, store_id, plan_version)
);
CREATE INDEX ix_plan_lookup ON gold.fact_sales_plan (tenant_id, iso_year_week, brand_id);
GO
INSERT INTO gold.fact_sales_plan
    (tenant_id, iso_year_week, brand_id, store_id, plan_version, planned_units, planned_revenue, currency_code)
VALUES (0, N'1900-W01', 0, 0, N'__SENTINEL__', 0, 0, N'UYU');
GO
