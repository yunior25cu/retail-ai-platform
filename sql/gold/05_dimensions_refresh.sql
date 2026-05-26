/* ============================================================
 * 05_dimensions_refresh.sql  (originally: block_5)
 * Purpose : Gold dimensions derived from source ERP via MERGE.
 *           dim_category, dim_store, dim_sku + their refresh procs.
 *           Each refresh proc uses HASHBYTES('SHA2_256') for change
 *           detection, soft-deletes on NOT MATCHED BY SOURCE, and logs
 *           per-batch to etl_batch_log.
 * Depends : 01-04
 * Frequency: per-tenant refresh during nightly pipeline.
 * ============================================================ */

------------------------------------------------------------------
-- dim_category
------------------------------------------------------------------
IF OBJECT_ID('gold.dim_category','U') IS NOT NULL DROP TABLE gold.dim_category;
GO
CREATE TABLE gold.dim_category (
    tenant_id           BIGINT          NOT NULL,
    category_id         BIGINT          NOT NULL,
    category_code       NVARCHAR(255)   NOT NULL,
    category_name       NVARCHAR(255)   NOT NULL,
    parent_category_id  BIGINT          NULL,
    category_level      TINYINT         NOT NULL,           -- 1=root, 2=leaf
    is_active           BIT             NOT NULL CONSTRAINT df_dimcat_active DEFAULT 1,
    etl_loaded_at       DATETIME2(3)    NOT NULL CONSTRAINT df_dimcat_loaded DEFAULT SYSUTCDATETIME(),
    etl_batch_id        UNIQUEIDENTIFIER NULL,
    etl_source_hash     VARBINARY(32)   NULL,
    CONSTRAINT pk_dim_category PRIMARY KEY CLUSTERED (tenant_id, category_id)
);
CREATE INDEX ix_dim_category_parent ON gold.dim_category (tenant_id, parent_category_id);
GO

IF OBJECT_ID('gold.sp_refresh_dim_category','P') IS NOT NULL DROP PROCEDURE gold.sp_refresh_dim_category;
GO
CREATE PROCEDURE gold.sp_refresh_dim_category
    @tenant_id BIGINT,
    @batch_id  UNIQUEIDENTIFIER = NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @batch_id IS NULL SET @batch_id = NEWID();

    DECLARE @log_id BIGINT, @rows BIGINT = 0;
    INSERT INTO gold.etl_batch_log (batch_id, tenant_id, step_name) VALUES (@batch_id, @tenant_id, N'sp_refresh_dim_category');
    SET @log_id = SCOPE_IDENTITY();

    BEGIN TRY
        ;WITH src AS (
            SELECT
                c.id_empresa                                                     AS tenant_id,
                c.id                                                             AS category_id,
                c.codigo                                                         AS category_code,
                c.denominacion                                                   AS category_name,
                c.id_categoria                                                   AS parent_category_id,
                CASE WHEN c.id_categoria IS NULL THEN 1 ELSE 2 END               AS category_level,
                HASHBYTES('SHA2_256',
                    CONCAT_WS(N'|', c.codigo, c.denominacion,
                              CAST(ISNULL(c.id_categoria, -1) AS NVARCHAR(20)))) AS h
            FROM dbo.categoria c
            WHERE c.id_empresa = @tenant_id AND c.[delete] = 0
        )
        MERGE gold.dim_category WITH (HOLDLOCK) AS tgt
        USING src
           ON tgt.tenant_id = src.tenant_id AND tgt.category_id = src.category_id
        WHEN MATCHED AND (tgt.etl_source_hash IS NULL OR tgt.etl_source_hash <> src.h OR tgt.is_active = 0) THEN
            UPDATE SET
                category_code      = src.category_code,
                category_name      = src.category_name,
                parent_category_id = src.parent_category_id,
                category_level     = src.category_level,
                is_active          = 1,
                etl_loaded_at      = SYSUTCDATETIME(),
                etl_batch_id       = @batch_id,
                etl_source_hash    = src.h
        WHEN NOT MATCHED BY TARGET THEN
            INSERT (tenant_id, category_id, category_code, category_name, parent_category_id,
                    category_level, is_active, etl_loaded_at, etl_batch_id, etl_source_hash)
            VALUES (src.tenant_id, src.category_id, src.category_code, src.category_name, src.parent_category_id,
                    src.category_level, 1, SYSUTCDATETIME(), @batch_id, src.h)
        WHEN NOT MATCHED BY SOURCE AND tgt.tenant_id = @tenant_id AND tgt.is_active = 1 THEN
            UPDATE SET is_active = 0, etl_loaded_at = SYSUTCDATETIME(), etl_batch_id = @batch_id;

        SET @rows = @@ROWCOUNT;
        UPDATE gold.etl_batch_log
           SET finished_at = SYSUTCDATETIME(), status = N'SUCCESS', rows_processed = @rows
         WHERE id = @log_id;
    END TRY
    BEGIN CATCH
        UPDATE gold.etl_batch_log
           SET finished_at = SYSUTCDATETIME(), status = N'FAILED', error_msg = ERROR_MESSAGE()
         WHERE id = @log_id;
        THROW;
    END CATCH
END;
GO

------------------------------------------------------------------
-- dim_store : almacen + enrichment from dim_store_classification / dim_society_mapping
------------------------------------------------------------------
IF OBJECT_ID('gold.dim_store','U') IS NOT NULL DROP TABLE gold.dim_store;
GO
CREATE TABLE gold.dim_store (
    tenant_id            BIGINT          NOT NULL,
    store_id             BIGINT          NOT NULL,
    store_code           NVARCHAR(255)   NOT NULL,
    store_name           NVARCHAR(255)   NOT NULL,
    is_main              BIT             NOT NULL,
    address              NVARCHAR(MAX)   NULL,
    latitude             FLOAT           NULL,
    longitude            FLOAT           NULL,
    valuation_method_id  BIGINT          NULL,
    -- enrichment (MANUAL)
    is_store_flag        BIT             NOT NULL CONSTRAINT df_dimstore_is_store DEFAULT 0,
    block_AB             NVARCHAR(20)    NOT NULL CONSTRAINT df_dimstore_block    DEFAULT N'NO CLASIFICADO',
    region               NVARCHAR(50)    NOT NULL CONSTRAINT df_dimstore_region   DEFAULT N'NO CLASIFICADO',
    society_id           INT             NOT NULL CONSTRAINT df_dimstore_society  DEFAULT 0,
    is_active            BIT             NOT NULL CONSTRAINT df_dimstore_active   DEFAULT 1,
    etl_loaded_at        DATETIME2(3)    NOT NULL CONSTRAINT df_dimstore_loaded   DEFAULT SYSUTCDATETIME(),
    etl_batch_id         UNIQUEIDENTIFIER NULL,
    etl_source_hash      VARBINARY(32)   NULL,
    CONSTRAINT pk_dim_store PRIMARY KEY CLUSTERED (tenant_id, store_id)
);
CREATE INDEX ix_dim_store_block ON gold.dim_store (tenant_id, block_AB);
GO

IF OBJECT_ID('gold.sp_refresh_dim_store','P') IS NOT NULL DROP PROCEDURE gold.sp_refresh_dim_store;
GO
CREATE PROCEDURE gold.sp_refresh_dim_store
    @tenant_id BIGINT,
    @batch_id  UNIQUEIDENTIFIER = NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @batch_id IS NULL SET @batch_id = NEWID();

    DECLARE @log_id BIGINT, @rows BIGINT = 0;
    INSERT INTO gold.etl_batch_log (batch_id, tenant_id, step_name) VALUES (@batch_id, @tenant_id, N'sp_refresh_dim_store');
    SET @log_id = SCOPE_IDENTITY();

    BEGIN TRY
        ;WITH src AS (
            SELECT
                a.id_empresa                                                AS tenant_id,
                a.id                                                        AS store_id,
                a.codigo                                                    AS store_code,
                a.denominacion                                              AS store_name,
                a.principal                                                 AS is_main,
                a.direccion                                                 AS address,
                a.latitude                                                  AS latitude,
                a.longitude                                                 AS longitude,
                a.id_metodo_valuacion                                       AS valuation_method_id,
                COALESCE(sc.is_store_flag, 0)                               AS is_store_flag,
                COALESCE(sc.block_AB,  N'NO CLASIFICADO')                   AS block_AB,
                COALESCE(sc.region,    N'NO CLASIFICADO')                   AS region,
                COALESCE(sm.society_id, 0)                                  AS society_id,
                HASHBYTES('SHA2_256',
                    CONCAT_WS(N'|', a.codigo, a.denominacion, CAST(a.principal AS NCHAR(1)),
                              CAST(ISNULL(a.latitude, 0) AS NVARCHAR(40)),
                              CAST(ISNULL(a.longitude, 0) AS NVARCHAR(40)),
                              COALESCE(sc.block_AB, N''), COALESCE(sc.region, N''),
                              CAST(COALESCE(sc.is_store_flag, 0) AS NCHAR(1)),
                              CAST(COALESCE(sm.society_id, 0) AS NVARCHAR(20)))) AS h
            FROM dbo.almacen a
            LEFT JOIN gold.dim_store_classification sc
                   ON sc.tenant_id = a.id_empresa AND sc.store_id = a.id
            LEFT JOIN gold.dim_society_mapping sm
                   ON sm.tenant_id = a.id_empresa
            WHERE a.id_empresa = @tenant_id AND a.[delete] = 0
        )
        MERGE gold.dim_store WITH (HOLDLOCK) AS tgt
        USING src
           ON tgt.tenant_id = src.tenant_id AND tgt.store_id = src.store_id
        WHEN MATCHED AND (tgt.etl_source_hash IS NULL OR tgt.etl_source_hash <> src.h OR tgt.is_active = 0) THEN
            UPDATE SET
                store_code          = src.store_code,
                store_name           = src.store_name,
                is_main              = src.is_main,
                address              = src.address,
                latitude             = src.latitude,
                longitude            = src.longitude,
                valuation_method_id  = src.valuation_method_id,
                is_store_flag        = src.is_store_flag,
                block_AB             = src.block_AB,
                region               = src.region,
                society_id           = src.society_id,
                is_active            = 1,
                etl_loaded_at        = SYSUTCDATETIME(),
                etl_batch_id         = @batch_id,
                etl_source_hash      = src.h
        WHEN NOT MATCHED BY TARGET THEN
            INSERT (tenant_id, store_id, store_code, store_name, is_main, address, latitude, longitude,
                    valuation_method_id, is_store_flag, block_AB, region, society_id,
                    is_active, etl_loaded_at, etl_batch_id, etl_source_hash)
            VALUES (src.tenant_id, src.store_id, src.store_code, src.store_name, src.is_main, src.address,
                    src.latitude, src.longitude, src.valuation_method_id,
                    src.is_store_flag, src.block_AB, src.region, src.society_id,
                    1, SYSUTCDATETIME(), @batch_id, src.h)
        WHEN NOT MATCHED BY SOURCE AND tgt.tenant_id = @tenant_id AND tgt.is_active = 1 THEN
            UPDATE SET is_active = 0, etl_loaded_at = SYSUTCDATETIME(), etl_batch_id = @batch_id;

        SET @rows = @@ROWCOUNT;
        UPDATE gold.etl_batch_log
           SET finished_at = SYSUTCDATETIME(), status = N'SUCCESS', rows_processed = @rows
         WHERE id = @log_id;
    END TRY
    BEGIN CATCH
        UPDATE gold.etl_batch_log
           SET finished_at = SYSUTCDATETIME(), status = N'FAILED', error_msg = ERROR_MESSAGE()
         WHERE id = @log_id;
        THROW;
    END CATCH
END;
GO

------------------------------------------------------------------
-- dim_sku : producto + enrichment from dim_brand_mapping / dim_season_mapping
--   Active season picked via OUTER APPLY (today between start/end, most
--   recent end_date if multiple).
------------------------------------------------------------------
IF OBJECT_ID('gold.dim_sku','U') IS NOT NULL DROP TABLE gold.dim_sku;
GO
CREATE TABLE gold.dim_sku (
    tenant_id            BIGINT          NOT NULL,
    sku_id               BIGINT          NOT NULL,
    sku_code             NVARCHAR(255)   NOT NULL,
    sku_barcode          NVARCHAR(255)   NULL,
    sku_name             NVARCHAR(255)   NOT NULL,
    is_service           BIT             NOT NULL,
    category_id          BIGINT          NULL,
    subcategory_id       BIGINT          NULL,
    unit_of_measure_id   BIGINT          NULL,
    product_type_id      BIGINT          NULL,
    list_price           DECIMAL(18,4)   NULL,
    reorder_point        DECIMAL(18,4)   NULL,
    variant_parent_sku_id BIGINT         NULL,
    brand_id             BIGINT          NOT NULL CONSTRAINT df_dimsku_brand   DEFAULT 0,
    brand_name           NVARCHAR(120)   NOT NULL CONSTRAINT df_dimsku_bname   DEFAULT N'SIN MARCA',
    season_id            INT             NOT NULL CONSTRAINT df_dimsku_season  DEFAULT 0,
    season_name          NVARCHAR(50)    NOT NULL CONSTRAINT df_dimsku_sname   DEFAULT N'SIN TEMPORADA',
    season_month         TINYINT         NULL,
    is_active            BIT             NOT NULL CONSTRAINT df_dimsku_active  DEFAULT 1,
    etl_loaded_at        DATETIME2(3)    NOT NULL CONSTRAINT df_dimsku_loaded  DEFAULT SYSUTCDATETIME(),
    etl_batch_id         UNIQUEIDENTIFIER NULL,
    etl_source_hash      VARBINARY(32)   NULL,
    CONSTRAINT pk_dim_sku PRIMARY KEY CLUSTERED (tenant_id, sku_id)
);
CREATE INDEX ix_dim_sku_code     ON gold.dim_sku (tenant_id, sku_code);
CREATE INDEX ix_dim_sku_brand    ON gold.dim_sku (tenant_id, brand_id);
CREATE INDEX ix_dim_sku_category ON gold.dim_sku (tenant_id, category_id);
GO

IF OBJECT_ID('gold.sp_refresh_dim_sku','P') IS NOT NULL DROP PROCEDURE gold.sp_refresh_dim_sku;
GO
CREATE PROCEDURE gold.sp_refresh_dim_sku
    @tenant_id BIGINT,
    @batch_id  UNIQUEIDENTIFIER = NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @batch_id IS NULL SET @batch_id = NEWID();

    DECLARE @log_id BIGINT, @rows BIGINT = 0;
    INSERT INTO gold.etl_batch_log (batch_id, tenant_id, step_name) VALUES (@batch_id, @tenant_id, N'sp_refresh_dim_sku');
    SET @log_id = SCOPE_IDENTITY();

    BEGIN TRY
        DECLARE @today DATE = CAST(SYSUTCDATETIME() AS DATE);

        ;WITH src AS (
            SELECT
                p.id_empresa                                       AS tenant_id,
                p.id                                               AS sku_id,
                p.codigo                                           AS sku_code,
                p.codigo_barras                                    AS sku_barcode,
                p.denominacion                                     AS sku_name,
                p.es_servicio                                      AS is_service,
                p.id_categoria                                     AS category_id,
                p.id_subcategoria                                  AS subcategory_id,
                p.id_unidad_medida                                 AS unit_of_measure_id,
                p.id_tipo_producto                                 AS product_type_id,
                p.precio_venta                                     AS list_price,
                p.punto_reorden                                    AS reorder_point,
                p.id_producto                                      AS variant_parent_sku_id,
                COALESCE(bm.brand_id, 0)                           AS brand_id,
                COALESCE(bm.brand_name, N'SIN MARCA')              AS brand_name,
                COALESCE(sm.season_id, 0)                          AS season_id,
                COALESCE(sm.season_name, N'SIN TEMPORADA')         AS season_name,
                sm.season_month                                    AS season_month,
                HASHBYTES('SHA2_256',
                    CONCAT_WS(N'|', p.codigo, p.codigo_barras, p.denominacion,
                              CAST(p.es_servicio AS NCHAR(1)),
                              CAST(ISNULL(p.id_categoria,-1) AS NVARCHAR(20)),
                              CAST(ISNULL(p.id_subcategoria,-1) AS NVARCHAR(20)),
                              CAST(ISNULL(p.precio_venta,0) AS NVARCHAR(40)),
                              CAST(ISNULL(p.punto_reorden,0) AS NVARCHAR(40)),
                              CAST(COALESCE(bm.brand_id,0) AS NVARCHAR(20)),
                              CAST(COALESCE(sm.season_id,0) AS NVARCHAR(20)))) AS h
            FROM dbo.producto p
            LEFT JOIN gold.dim_brand_mapping bm
                   ON bm.tenant_id = p.id_empresa AND bm.sku_code = p.codigo
            OUTER APPLY (
                SELECT TOP 1 s.season_id, s.season_name, s.season_month
                FROM gold.dim_season_mapping s
                WHERE s.tenant_id = p.id_empresa
                  AND s.sku_code  = p.codigo
                  AND s.season_id > 0
                  AND @today BETWEEN s.season_start_date AND s.season_end_date
                ORDER BY s.season_end_date DESC
            ) sm
            WHERE p.id_empresa = @tenant_id AND p.[delete] = 0
        )
        MERGE gold.dim_sku WITH (HOLDLOCK) AS tgt
        USING src
           ON tgt.tenant_id = src.tenant_id AND tgt.sku_id = src.sku_id
        WHEN MATCHED AND (tgt.etl_source_hash IS NULL OR tgt.etl_source_hash <> src.h OR tgt.is_active = 0) THEN
            UPDATE SET
                sku_code              = src.sku_code,
                sku_barcode           = src.sku_barcode,
                sku_name              = src.sku_name,
                is_service            = src.is_service,
                category_id           = src.category_id,
                subcategory_id        = src.subcategory_id,
                unit_of_measure_id    = src.unit_of_measure_id,
                product_type_id       = src.product_type_id,
                list_price            = src.list_price,
                reorder_point         = src.reorder_point,
                variant_parent_sku_id = src.variant_parent_sku_id,
                brand_id              = src.brand_id,
                brand_name            = src.brand_name,
                season_id             = src.season_id,
                season_name           = src.season_name,
                season_month          = src.season_month,
                is_active             = 1,
                etl_loaded_at         = SYSUTCDATETIME(),
                etl_batch_id          = @batch_id,
                etl_source_hash       = src.h
        WHEN NOT MATCHED BY TARGET THEN
            INSERT (tenant_id, sku_id, sku_code, sku_barcode, sku_name, is_service, category_id, subcategory_id,
                    unit_of_measure_id, product_type_id, list_price, reorder_point, variant_parent_sku_id,
                    brand_id, brand_name, season_id, season_name, season_month,
                    is_active, etl_loaded_at, etl_batch_id, etl_source_hash)
            VALUES (src.tenant_id, src.sku_id, src.sku_code, src.sku_barcode, src.sku_name, src.is_service,
                    src.category_id, src.subcategory_id, src.unit_of_measure_id, src.product_type_id,
                    src.list_price, src.reorder_point, src.variant_parent_sku_id,
                    src.brand_id, src.brand_name, src.season_id, src.season_name, src.season_month,
                    1, SYSUTCDATETIME(), @batch_id, src.h)
        WHEN NOT MATCHED BY SOURCE AND tgt.tenant_id = @tenant_id AND tgt.is_active = 1 THEN
            UPDATE SET is_active = 0, etl_loaded_at = SYSUTCDATETIME(), etl_batch_id = @batch_id;

        SET @rows = @@ROWCOUNT;
        UPDATE gold.etl_batch_log
           SET finished_at = SYSUTCDATETIME(), status = N'SUCCESS', rows_processed = @rows
         WHERE id = @log_id;
    END TRY
    BEGIN CATCH
        UPDATE gold.etl_batch_log
           SET finished_at = SYSUTCDATETIME(), status = N'FAILED', error_msg = ERROR_MESSAGE()
         WHERE id = @log_id;
        THROW;
    END CATCH
END;
GO
