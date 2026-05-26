IF OBJECT_ID('gold.fact_transfers','U') IS NOT NULL DROP TABLE gold.fact_transfers;
GO
CREATE TABLE gold.fact_transfers (
    tenant_id           BIGINT           NOT NULL,
    transfer_line_id    BIGINT           NOT NULL,
    transfer_header_id  BIGINT           NOT NULL,
    transfer_date       DATE             NOT NULL,
    origin_store_id     BIGINT           NOT NULL,
    dest_store_id       BIGINT           NOT NULL,
    sku_id              BIGINT           NOT NULL,
    brand_id            BIGINT           NOT NULL,
    category_id         BIGINT           NOT NULL,
    units               DECIMAL(18,4)    NOT NULL,
    [value]             DECIMAL(18,4)    NOT NULL,
    currency_code       NVARCHAR(3)      NOT NULL,
    etl_loaded_at       DATETIME2(3)     NOT NULL CONSTRAINT df_ftr_loaded DEFAULT SYSUTCDATETIME(),
    etl_batch_id        UNIQUEIDENTIFIER NULL,
    CONSTRAINT pk_fact_transfers PRIMARY KEY CLUSTERED (tenant_id, transfer_line_id)
);
CREATE INDEX ix_ftr_header   ON gold.fact_transfers (tenant_id, transfer_header_id);
CREATE INDEX ix_ftr_date     ON gold.fact_transfers (tenant_id, transfer_date);
CREATE INDEX ix_ftr_origin   ON gold.fact_transfers (tenant_id, origin_store_id, transfer_date);
CREATE INDEX ix_ftr_dest     ON gold.fact_transfers (tenant_id, dest_store_id, transfer_date);
CREATE INDEX ix_ftr_sku      ON gold.fact_transfers (tenant_id, sku_id, transfer_date);
GO

IF OBJECT_ID('gold.sp_refresh_fact_transfers','P') IS NOT NULL DROP PROCEDURE gold.sp_refresh_fact_transfers;
GO
CREATE PROCEDURE gold.sp_refresh_fact_transfers
    @tenant_id      BIGINT,
    @full_refresh   BIT              = 0,
    @batch_id       UNIQUEIDENTIFIER = NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @batch_id IS NULL SET @batch_id = NEWID();

    DECLARE @log_id BIGINT, @deleted INT = 0, @inserted INT = 0, @watermark BIGINT;

    INSERT INTO gold.etl_batch_log (batch_id, tenant_id, step_name)
    VALUES (@batch_id, @tenant_id, N'sp_refresh_fact_transfers');
    SET @log_id = SCOPE_IDENTITY();

    BEGIN TRY
        DECLARE @currency_code NVARCHAR(3) =
            (SELECT TOP 1 CAST(LEFT(m.codigo, 3) AS NVARCHAR(3))
               FROM dbo.empresa e JOIN dbo.moneda m ON m.id = e.id_moneda
              WHERE e.id = @tenant_id ORDER BY e.id);
        SET @currency_code = ISNULL(@currency_code, N'UYU');

        IF @full_refresh = 1
        BEGIN
            DELETE FROM gold.fact_transfers WHERE tenant_id = @tenant_id;
            SET @deleted = @@ROWCOUNT;
            SET @watermark = 0;
        END
        ELSE
        BEGIN
            SET @watermark = ISNULL(
                (SELECT MAX(transfer_line_id) FROM gold.fact_transfers WHERE tenant_id = @tenant_id),
                0
            );
        END

        INSERT INTO gold.fact_transfers
            (tenant_id, transfer_line_id, transfer_header_id, transfer_date,
             origin_store_id, dest_store_id, sku_id, brand_id, category_id,
             units, [value], currency_code, etl_loaded_at, etl_batch_id)
        SELECT
            @tenant_id,
            dp.id,
            d.id,
            d.fecha_emision,
            COALESCE(d.id_almacen, 0),
            vs.id_almacen_destino,
            dp.id_producto,
            COALESCE(ds.brand_id,    0),
            COALESCE(ds.category_id, 0),
            CAST(dp.cantidad     AS DECIMAL(18,4)),
            CAST(dp.importe_base AS DECIMAL(18,4)),
            @currency_code, SYSUTCDATETIME(), @batch_id
        FROM dbo.documento d
        JOIN dbo.vale_salida vs        ON vs.id = d.id
        JOIN dbo.documento_producto dp ON dp.id_documento = d.id
        LEFT JOIN gold.dim_sku ds
               ON ds.tenant_id = d.id_empresa AND ds.sku_id = dp.id_producto
        WHERE d.id_empresa     = @tenant_id
          AND d.[delete]       = 0
          AND d.estado         IN (1, 2)
          AND d.tipo_documento = 6
          AND vs.destino       = 4
          AND dp.cantidad      > 0
          AND dp.id            > @watermark;

        SET @inserted = @@ROWCOUNT;

        DECLARE @self_transfers INT = (
            SELECT COUNT(*) FROM gold.fact_transfers
             WHERE tenant_id = @tenant_id AND etl_batch_id = @batch_id
               AND origin_store_id = dest_store_id
               AND origin_store_id > 0
        );
        IF @self_transfers > 0
            INSERT INTO gold.etl_data_quality_metrics
                (batch_id, tenant_id, table_name, metric_name, metric_value, severity, notes)
            VALUES (@batch_id, @tenant_id, N'gold.fact_transfers',
                    N'self_transfers', @self_transfers, N'WARN',
                    N'transferencias con origin = dest');

        UPDATE gold.etl_batch_log
           SET finished_at    = SYSUTCDATETIME(),
               status         = N'SUCCESS',
               rows_processed = @inserted,
               error_msg      = CONCAT(N'mode=', CASE WHEN @full_refresh=1 THEN N'FULL' ELSE N'INCR' END,
                                       N' watermark=', @watermark,
                                       N' deleted=', @deleted,
                                       N' inserted=', @inserted,
                                       N' self=', @self_transfers,
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
