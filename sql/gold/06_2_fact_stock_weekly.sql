IF OBJECT_ID('gold.fact_stock_weekly','U') IS NOT NULL DROP TABLE gold.fact_stock_weekly;
GO
CREATE TABLE gold.fact_stock_weekly (
    tenant_id                 BIGINT           NOT NULL,
    iso_year_week             CHAR(8)          NOT NULL,
    store_id                  BIGINT           NOT NULL,
    sku_id                    BIGINT           NOT NULL,
    stock_units               DECIMAL(18,4)    NOT NULL,
    stock_value               DECIMAL(18,4)    NOT NULL,
    unit_cost                 DECIMAL(18,4)    NOT NULL,
    stock_min                 DECIMAL(18,4)    NULL,
    stock_max                 DECIMAL(18,4)    NULL,
    has_zero_stock_flag       BIT              NOT NULL,
    days_since_last_sale      INT              NULL,
    days_since_last_movement  INT              NULL,
    last_sale_date            DATE             NULL,
    last_movement_date        DATE             NULL,
    is_obsolete_flag          BIT              NOT NULL,
    currency_code             NVARCHAR(3)      NOT NULL,
    etl_loaded_at             DATETIME2(3)     NOT NULL CONSTRAINT df_fstw_loaded DEFAULT SYSUTCDATETIME(),
    etl_batch_id              UNIQUEIDENTIFIER NULL,
    CONSTRAINT pk_fact_stock_weekly PRIMARY KEY CLUSTERED
        (tenant_id, iso_year_week, store_id, sku_id)
);
CREATE INDEX ix_fstw_week_sku   ON gold.fact_stock_weekly (tenant_id, iso_year_week, sku_id);
CREATE INDEX ix_fstw_week_store ON gold.fact_stock_weekly (tenant_id, iso_year_week, store_id);
CREATE INDEX ix_fstw_obsolete   ON gold.fact_stock_weekly (tenant_id, is_obsolete_flag)    WHERE is_obsolete_flag = 1;
CREATE INDEX ix_fstw_zerostock  ON gold.fact_stock_weekly (tenant_id, has_zero_stock_flag) WHERE has_zero_stock_flag = 1;
GO

IF OBJECT_ID('gold.sp_refresh_fact_stock_weekly','P') IS NOT NULL DROP PROCEDURE gold.sp_refresh_fact_stock_weekly;
GO
CREATE PROCEDURE gold.sp_refresh_fact_stock_weekly
    @tenant_id            BIGINT,
    @from_week            CHAR(8)          = NULL,
    @to_week              CHAR(8)          = NULL,
    @dead_threshold_days  INT              = 84,
    @batch_id             UNIQUEIDENTIFIER = NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @batch_id IS NULL SET @batch_id = NEWID();

    DECLARE @log_id   BIGINT, @deleted INT = 0, @inserted INT = 0;

    INSERT INTO gold.etl_batch_log (batch_id, tenant_id, step_name)
    VALUES (@batch_id, @tenant_id, N'sp_refresh_fact_stock_weekly');
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

        DECLARE @from_date DATE = (SELECT MIN(week_end_date) FROM gold.dim_date WHERE iso_year_week = @from_week);
        DECLARE @to_date   DATE = (SELECT MAX(week_end_date) FROM gold.dim_date WHERE iso_year_week = @to_week);
        IF @from_date IS NULL OR @to_date IS NULL
            RAISERROR(N'No se pudo resolver el rango. Verificar dim_date y formato YYYY-Www.', 16, 1);

        DECLARE @currency_code NVARCHAR(3) =
            (SELECT TOP 1 CAST(LEFT(m.codigo, 3) AS NVARCHAR(3))
               FROM dbo.empresa e
               JOIN dbo.moneda  m ON m.id = e.id_moneda
              WHERE e.id = @tenant_id
              ORDER BY e.id);
        SET @currency_code = ISNULL(@currency_code, N'UYU');

        DELETE FROM gold.fact_stock_weekly
         WHERE tenant_id = @tenant_id
           AND iso_year_week BETWEEN @from_week AND @to_week;
        SET @deleted = @@ROWCOUNT;

        ;WITH alive_pairs AS (
            SELECT id_almacen_producto, id_almacen, id_producto, min_stock, max_stock
            FROM (
                SELECT
                    ap.id              AS id_almacen_producto,
                    ap.id_almacen, ap.id_producto, ap.min_stock, ap.max_stock,
                    s.last_saldo, s.last_mov_date,
                    ROW_NUMBER() OVER (PARTITION BY ap.id_almacen, ap.id_producto ORDER BY ap.id DESC) AS rn
                FROM dbo.almacen_producto ap
                CROSS APPLY (
                    SELECT TOP 1 si.saldo AS last_saldo, d.fecha_emision AS last_mov_date
                    FROM dbo.submayor_inventario si
                    JOIN dbo.documento d ON d.id = si.id_documento
                    WHERE si.id_almacen_producto = ap.id
                      AND d.id_empresa = @tenant_id
                      AND d.estado     IN (1, 2)
                      AND d.[delete]   = 0
                      AND d.fecha_emision <= @to_date
                    ORDER BY d.fecha_emision DESC, si.id DESC
                ) s
                WHERE NOT (s.last_saldo = 0
                           AND DATEDIFF(DAY, s.last_mov_date, @to_date) > @dead_threshold_days)
            ) x
            WHERE rn = 1
        ),
        weeks AS (
            SELECT DISTINCT iso_year_week, week_end_date, season_month
            FROM gold.dim_date
            WHERE iso_year_week BETWEEN @from_week AND @to_week
        ),
        snapshot AS (
            SELECT
                w.iso_year_week, w.week_end_date, w.season_month,
                p.id_almacen, p.id_producto, p.id_almacen_producto,
                p.min_stock, p.max_stock,
                sm.saldo, sm.costo, sm.costo_final, sm.mov_date,
                sale.last_sale_date
            FROM weeks w
            CROSS JOIN alive_pairs p
            OUTER APPLY (
                SELECT TOP 1 si.saldo, si.costo, si.costo_final, d.fecha_emision AS mov_date
                FROM dbo.submayor_inventario si
                JOIN dbo.documento d ON d.id = si.id_documento
                WHERE si.id_almacen_producto = p.id_almacen_producto
                  AND d.id_empresa = @tenant_id
                  AND d.estado     IN (1, 2)
                  AND d.[delete]   = 0
                  AND d.fecha_emision <= w.week_end_date
                ORDER BY d.fecha_emision DESC, si.id DESC
            ) sm
            OUTER APPLY (
                SELECT TOP 1 d2.fecha_emision AS last_sale_date
                FROM dbo.documento d2
                JOIN dbo.documento_producto dp2 ON dp2.id_documento = d2.id
                WHERE d2.id_empresa     = @tenant_id
                  AND d2.tipo_documento = 3
                  AND d2.estado         IN (1, 2)
                  AND d2.[delete]       = 0
                  AND d2.id_almacen     = p.id_almacen
                  AND dp2.id_producto   = p.id_producto
                  AND dp2.cantidad      > 0
                  AND d2.fecha_emision  <= w.week_end_date
                ORDER BY d2.fecha_emision DESC, d2.id DESC
            ) sale
            WHERE sm.saldo IS NOT NULL
        )
        INSERT INTO gold.fact_stock_weekly
            (tenant_id, iso_year_week, store_id, sku_id,
             stock_units, stock_value, unit_cost,
             stock_min, stock_max, has_zero_stock_flag,
             days_since_last_sale, days_since_last_movement,
             last_sale_date, last_movement_date, is_obsolete_flag,
             currency_code, etl_loaded_at, etl_batch_id)
        SELECT
            @tenant_id,
            s.iso_year_week,
            s.id_almacen,
            s.id_producto,
            CAST(s.saldo        AS DECIMAL(18,4)),
            CAST(s.costo_final  AS DECIMAL(18,4)),
            CAST(s.costo        AS DECIMAL(18,4)),
            CAST(s.min_stock    AS DECIMAL(18,4)),
            CAST(s.max_stock    AS DECIMAL(18,4)),
            CASE WHEN s.saldo = 0 THEN 1 ELSE 0 END,
            CASE WHEN s.last_sale_date IS NULL THEN NULL
                 ELSE DATEDIFF(DAY, s.last_sale_date, s.week_end_date) END,
            DATEDIFF(DAY, s.mov_date, s.week_end_date),
            s.last_sale_date,
            s.mov_date,
            CASE
                WHEN s.last_sale_date IS NULL THEN 1
                WHEN DATEDIFF(DAY, s.last_sale_date, s.week_end_date)
                     > ISNULL(obs_rule.days_no_sale_obsolete, 90)
                THEN 1
                ELSE 0
            END,
            @currency_code, SYSUTCDATETIME(), @batch_id
        FROM snapshot s
        LEFT JOIN gold.dim_sku ds
               ON ds.tenant_id = @tenant_id AND ds.sku_id = s.id_producto
        OUTER APPLY (
            SELECT TOP 1 r.days_no_sale_obsolete
            FROM gold.dim_business_rules r
            WHERE r.tenant_id = @tenant_id
              AND r.is_active = 1
              AND (r.brand_id    = 0    OR r.brand_id    = COALESCE(ds.brand_id, 0))
              AND (r.category_id = 0    OR r.category_id = COALESCE(ds.category_id, 0))
              AND (r.season_month IS NULL OR r.season_month = s.season_month)
            ORDER BY
                CASE WHEN r.brand_id     = 0    THEN 1 ELSE 0 END,
                CASE WHEN r.category_id  = 0    THEN 1 ELSE 0 END,
                CASE WHEN r.season_month IS NULL THEN 1 ELSE 0 END,
                r.priority,
                r.rule_id
        ) obs_rule;

        SET @inserted = @@ROWCOUNT;

        DECLARE @neg_stock INT = (
            SELECT COUNT(*) FROM gold.fact_stock_weekly
             WHERE tenant_id = @tenant_id
               AND iso_year_week BETWEEN @from_week AND @to_week
               AND stock_units < 0
        );
        IF @neg_stock > 0
            INSERT INTO gold.etl_data_quality_metrics
                (batch_id, tenant_id, table_name, metric_name, metric_value, severity, notes)
            VALUES (@batch_id, @tenant_id, N'gold.fact_stock_weekly',
                    N'rows_with_negative_stock', @neg_stock, N'WARN',
                    CONCAT(N'window=[', @from_week, N'..', @to_week, N']'));

        UPDATE gold.etl_batch_log
           SET finished_at    = SYSUTCDATETIME(),
               status         = N'SUCCESS',
               rows_processed = @inserted,
               error_msg      = CONCAT(N'window=[', @from_week, N'..', @to_week,
                                       N'] dead_threshold=', @dead_threshold_days,
                                       N' deleted=', @deleted,
                                       N' inserted=', @inserted,
                                       N' neg_stock=', @neg_stock,
                                       N' currency=', @currency_code)
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
