/* BLOQUE 6.1 — fact_sales_weekly + sp_refresh */

IF OBJECT_ID('gold.fact_sales_weekly','U') IS NOT NULL DROP TABLE gold.fact_sales_weekly;
GO
CREATE TABLE gold.fact_sales_weekly (
    tenant_id          BIGINT           NOT NULL,
    iso_year_week      CHAR(8)          NOT NULL,
    store_id           BIGINT           NOT NULL,
    sku_id             BIGINT           NOT NULL,
    brand_id           BIGINT           NOT NULL,
    category_id        BIGINT           NOT NULL,
    units_sold_gross   DECIMAL(18,4)    NOT NULL,
    units_returned     DECIMAL(18,4)    NOT NULL,
    units_sold_net     DECIMAL(18,4)    NOT NULL,
    revenue_gross      DECIMAL(18,4)    NOT NULL,
    revenue_returned   DECIMAL(18,4)    NOT NULL,
    revenue_net        DECIMAL(18,4)    NOT NULL,
    cogs               DECIMAL(18,4)    NOT NULL,
    gross_margin       DECIMAL(18,4)    NOT NULL,
    gross_margin_pct   DECIMAL(9,4)     NULL,
    tickets            INT              NOT NULL,
    avg_ticket         DECIMAL(18,4)    NULL,
    discount_amount    DECIMAL(18,4)    NOT NULL,
    currency_code      NVARCHAR(3)      NOT NULL,
    etl_loaded_at      DATETIME2(3)     NOT NULL CONSTRAINT df_fsw_loaded DEFAULT SYSUTCDATETIME(),
    etl_batch_id       UNIQUEIDENTIFIER NULL,
    CONSTRAINT pk_fact_sales_weekly PRIMARY KEY CLUSTERED
        (tenant_id, iso_year_week, store_id, sku_id, brand_id)
);
CREATE INDEX ix_fsw_brand_week    ON gold.fact_sales_weekly (tenant_id, brand_id,    iso_year_week);
CREATE INDEX ix_fsw_store_week    ON gold.fact_sales_weekly (tenant_id, store_id,    iso_year_week);
CREATE INDEX ix_fsw_sku_week      ON gold.fact_sales_weekly (tenant_id, sku_id,      iso_year_week);
CREATE INDEX ix_fsw_category_week ON gold.fact_sales_weekly (tenant_id, category_id, iso_year_week);
GO

IF OBJECT_ID('gold.sp_refresh_fact_sales_weekly','P') IS NOT NULL DROP PROCEDURE gold.sp_refresh_fact_sales_weekly;
GO
CREATE PROCEDURE gold.sp_refresh_fact_sales_weekly
    @tenant_id BIGINT,
    @from_week CHAR(8)         = NULL,
    @to_week   CHAR(8)         = NULL,
    @batch_id  UNIQUEIDENTIFIER = NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @batch_id IS NULL SET @batch_id = NEWID();

    DECLARE @log_id BIGINT, @deleted INT = 0, @inserted INT = 0;

    INSERT INTO gold.etl_batch_log (batch_id, tenant_id, step_name)
    VALUES (@batch_id, @tenant_id, N'sp_refresh_fact_sales_weekly');
    SET @log_id = SCOPE_IDENTITY();

    BEGIN TRY
        IF @from_week IS NULL OR @to_week IS NULL
        BEGIN
            DECLARE @today DATE = CAST(SYSUTCDATETIME() AS DATE);
            DECLARE @current_week CHAR(8) =
                (SELECT iso_year_week FROM gold.dim_date WHERE [date] = @today);
            DECLARE @four_weeks_ago_week CHAR(8) =
                (SELECT iso_year_week FROM gold.dim_date WHERE [date] = DATEADD(DAY, -28, @today));
            IF @from_week IS NULL SET @from_week = @four_weeks_ago_week;
            IF @to_week   IS NULL SET @to_week   = @current_week;
        END;

        IF @from_week IS NULL OR @to_week IS NULL
            RAISERROR(N'No se pudo resolver la ventana iso_year_week. Verificar dim_date.', 16, 1);

        DECLARE @currency_code NVARCHAR(3) =
            (SELECT TOP 1 CAST(LEFT(m.codigo, 3) AS NVARCHAR(3))
               FROM dbo.empresa e
               JOIN dbo.moneda  m ON m.id = e.id_moneda
              WHERE e.id = @tenant_id
              ORDER BY e.id);
        SET @currency_code = ISNULL(@currency_code, N'UYU');

        DELETE FROM gold.fact_sales_weekly
         WHERE tenant_id = @tenant_id
           AND iso_year_week BETWEEN @from_week AND @to_week;
        SET @deleted = @@ROWCOUNT;

        ;WITH line_facts AS (
            SELECT
                dd.iso_year_week                                          AS iso_year_week,
                COALESCE(d.id_almacen, 0)                                 AS store_id,
                dp.id_producto                                            AS sku_id,
                d.id                                                      AS doc_id,
                COALESCE(ds.brand_id,    0)                               AS brand_id,
                COALESCE(ds.category_id, 0)                               AS category_id,
                CAST(dp.cantidad                                AS DECIMAL(18,4)) AS qty_gross,
                CAST(ISNULL(dp.devuelto, 0)                     AS DECIMAL(18,4)) AS qty_returned,
                CAST(dp.cantidad - ISNULL(dp.devuelto, 0)       AS DECIMAL(18,4)) AS qty_net,
                CAST(dp.importe_base                            AS DECIMAL(18,4)) AS rev_gross,
                CAST(CASE WHEN dp.cantidad > 0
                          THEN dp.importe_base * ISNULL(dp.devuelto, 0) / dp.cantidad
                          ELSE 0
                     END                                        AS DECIMAL(18,4)) AS rev_returned,
                CAST(dp.importe_base
                     * (1 - ISNULL(dp.devuelto, 0) / NULLIF(dp.cantidad, 0))
                                                                AS DECIMAL(18,4)) AS rev_net,
                CAST(COALESCE(si.salida * si.costo, 0)          AS DECIMAL(18,4)) AS line_cogs,
                CAST(ISNULL(dp.descuento, 0)                    AS DECIMAL(18,4)) AS line_discount
            FROM dbo.documento d
            JOIN dbo.documento_producto dp ON dp.id_documento = d.id
            JOIN gold.dim_date dd          ON dd.[date] = d.fecha_emision
            LEFT JOIN gold.dim_sku ds
                   ON ds.tenant_id = d.id_empresa AND ds.sku_id = dp.id_producto
            LEFT JOIN dbo.almacen_producto ap
                   ON ap.id_almacen  = d.id_almacen
                  AND ap.id_producto = dp.id_producto
            LEFT JOIN dbo.submayor_inventario si
                   ON si.id_documento        = d.id
                  AND si.id_almacen_producto = ap.id
            WHERE d.id_empresa     = @tenant_id
              AND d.[delete]       = 0
              AND d.estado         IN (1, 2)
              AND d.tipo_documento = 3
              AND dd.iso_year_week BETWEEN @from_week AND @to_week
              AND dp.cantidad      > 0
        ),
        agg AS (
            SELECT
                iso_year_week, store_id, sku_id, brand_id, category_id,
                SUM(qty_gross)                                            AS units_sold_gross,
                SUM(qty_returned)                                         AS units_returned,
                SUM(qty_net)                                              AS units_sold_net,
                SUM(rev_gross)                                            AS revenue_gross,
                SUM(rev_returned)                                         AS revenue_returned,
                SUM(rev_net)                                              AS revenue_net,
                SUM(line_cogs)                                            AS cogs,
                SUM(rev_net) - SUM(line_cogs)                             AS gross_margin,
                COUNT(DISTINCT doc_id)                                    AS tickets,
                SUM(line_discount)                                        AS discount_amount
            FROM line_facts
            GROUP BY iso_year_week, store_id, sku_id, brand_id, category_id
        )
        INSERT INTO gold.fact_sales_weekly
            (tenant_id, iso_year_week, store_id, sku_id, brand_id, category_id,
             units_sold_gross, units_returned, units_sold_net,
             revenue_gross,    revenue_returned, revenue_net,
             cogs, gross_margin, gross_margin_pct,
             tickets, avg_ticket, discount_amount,
             currency_code, etl_loaded_at, etl_batch_id)
        SELECT
            @tenant_id, iso_year_week, store_id, sku_id, brand_id, category_id,
            units_sold_gross, units_returned, units_sold_net,
            revenue_gross,    revenue_returned, revenue_net,
            cogs, gross_margin,
            CASE WHEN revenue_net > 0
                 THEN CAST(gross_margin / revenue_net AS DECIMAL(9,4))
                 ELSE NULL
            END                                                           AS gross_margin_pct,
            tickets,
            CASE WHEN tickets > 0
                 THEN CAST(revenue_net / tickets AS DECIMAL(18,4))
                 ELSE NULL
            END                                                           AS avg_ticket,
            discount_amount,
            @currency_code, SYSUTCDATETIME(), @batch_id
        FROM agg;

        SET @inserted = @@ROWCOUNT;

        UPDATE gold.etl_batch_log
           SET finished_at    = SYSUTCDATETIME(),
               status         = N'SUCCESS',
               rows_processed = @inserted,
               error_msg      = CONCAT(N'window=[', @from_week, N'..', @to_week,
                                       N'] deleted=', @deleted,
                                       N' inserted=', @inserted,
                                       N' currency=', @currency_code)
         WHERE id = @log_id;
    END TRY
    BEGIN CATCH
        UPDATE gold.etl_batch_log
           SET finished_at = SYSUTCDATETIME(),
               status      = N'FAILED',
               error_msg   = ERROR_MESSAGE()
         WHERE id = @log_id;
        THROW;
    END CATCH
END;
GO
