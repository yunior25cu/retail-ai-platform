IF OBJECT_ID('gold.fact_stock_movements','U') IS NOT NULL DROP TABLE gold.fact_stock_movements;
GO
CREATE TABLE gold.fact_stock_movements (
    tenant_id          BIGINT           NOT NULL,
    movement_id        BIGINT           NOT NULL,
    movement_date      DATE             NOT NULL,
    document_id        BIGINT           NOT NULL,
    document_type      INT              NOT NULL,
    store_id           BIGINT           NOT NULL,
    sku_id             BIGINT           NOT NULL,
    qty_in             DECIMAL(18,4)    NOT NULL,
    qty_out            DECIMAL(18,4)    NOT NULL,
    qty_net            DECIMAL(18,4)    NOT NULL,
    direction          NVARCHAR(10)     NOT NULL,
    running_balance    DECIMAL(18,4)    NOT NULL,
    unit_cost          DECIMAL(18,4)    NOT NULL,
    [value]            DECIMAL(18,4)    NOT NULL,
    accumulated_value  DECIMAL(18,4)    NOT NULL,
    currency_code      NVARCHAR(3)      NOT NULL,
    etl_loaded_at      DATETIME2(3)     NOT NULL CONSTRAINT df_fsm_loaded DEFAULT SYSUTCDATETIME(),
    etl_batch_id       UNIQUEIDENTIFIER NULL,
    CONSTRAINT pk_fact_stock_movements PRIMARY KEY CLUSTERED (tenant_id, movement_id),
    CONSTRAINT ck_fsm_direction CHECK (direction IN (N'ENTRADA', N'SALIDA', N'AJUSTE', N'NEUTRO'))
);
CREATE INDEX ix_fsm_doc       ON gold.fact_stock_movements (tenant_id, document_id);
CREATE INDEX ix_fsm_date      ON gold.fact_stock_movements (tenant_id, movement_date);
CREATE INDEX ix_fsm_sku_store ON gold.fact_stock_movements (tenant_id, sku_id, store_id, movement_date);
CREATE INDEX ix_fsm_doctype   ON gold.fact_stock_movements (tenant_id, document_type);
GO

IF OBJECT_ID('gold.sp_refresh_fact_stock_movements','P') IS NOT NULL DROP PROCEDURE gold.sp_refresh_fact_stock_movements;
GO
CREATE PROCEDURE gold.sp_refresh_fact_stock_movements
    @tenant_id     BIGINT,
    @full_refresh  BIT              = 0,
    @batch_id      UNIQUEIDENTIFIER = NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @batch_id IS NULL SET @batch_id = NEWID();

    DECLARE @log_id BIGINT, @deleted INT = 0, @inserted INT = 0, @watermark BIGINT;

    INSERT INTO gold.etl_batch_log (batch_id, tenant_id, step_name)
    VALUES (@batch_id, @tenant_id, N'sp_refresh_fact_stock_movements');
    SET @log_id = SCOPE_IDENTITY();

    BEGIN TRY
        DECLARE @currency_code NVARCHAR(3) =
            (SELECT TOP 1 CAST(LEFT(m.codigo, 3) AS NVARCHAR(3))
               FROM dbo.empresa e JOIN dbo.moneda m ON m.id = e.id_moneda
              WHERE e.id = @tenant_id ORDER BY e.id);
        SET @currency_code = ISNULL(@currency_code, N'UYU');

        IF @full_refresh = 1
        BEGIN
            DELETE FROM gold.fact_stock_movements WHERE tenant_id = @tenant_id;
            SET @deleted = @@ROWCOUNT;
            SET @watermark = 0;
        END
        ELSE
        BEGIN
            SET @watermark = ISNULL(
                (SELECT MAX(movement_id) FROM gold.fact_stock_movements WHERE tenant_id = @tenant_id),
                0
            );
        END

        INSERT INTO gold.fact_stock_movements
            (tenant_id, movement_id, movement_date, document_id, document_type,
             store_id, sku_id, qty_in, qty_out, qty_net, direction,
             running_balance, unit_cost, [value], accumulated_value,
             currency_code, etl_loaded_at, etl_batch_id)
        SELECT
            @tenant_id,
            si.id,
            d.fecha_emision,
            d.id,
            d.tipo_documento,
            ap.id_almacen,
            ap.id_producto,
            CAST(si.entrada                  AS DECIMAL(18,4)),
            CAST(si.salida                   AS DECIMAL(18,4)),
            CAST(si.entrada - si.salida      AS DECIMAL(18,4)),
            CASE
                WHEN si.entrada > 0 AND si.salida = 0 THEN N'ENTRADA'
                WHEN si.salida  > 0 AND si.entrada = 0 THEN N'SALIDA'
                WHEN si.entrada > 0 AND si.salida > 0 THEN N'AJUSTE'
                ELSE                                       N'NEUTRO'
            END,
            CAST(si.saldo        AS DECIMAL(18,4)),
            CAST(si.costo        AS DECIMAL(18,4)),
            CAST(si.importe      AS DECIMAL(18,4)),
            CAST(si.costo_final  AS DECIMAL(18,4)),
            @currency_code, SYSUTCDATETIME(), @batch_id
        FROM dbo.submayor_inventario si
        JOIN dbo.documento d        ON d.id  = si.id_documento
        JOIN dbo.almacen_producto ap ON ap.id = si.id_almacen_producto
        WHERE d.id_empresa = @tenant_id
          AND d.estado     IN (1, 2)
          AND d.[delete]   = 0
          AND si.id        > @watermark;

        SET @inserted = @@ROWCOUNT;

        DECLARE @neutral_movs INT = (
            SELECT COUNT(*) FROM gold.fact_stock_movements
             WHERE tenant_id = @tenant_id AND etl_batch_id = @batch_id AND direction = N'NEUTRO'
        );
        IF @neutral_movs > 0
            INSERT INTO gold.etl_data_quality_metrics
                (batch_id, tenant_id, table_name, metric_name, metric_value, severity, notes)
            VALUES (@batch_id, @tenant_id, N'gold.fact_stock_movements',
                    N'rows_with_neutral_direction', @neutral_movs, N'WARN',
                    N'submayor con entrada=0 y salida=0');

        UPDATE gold.etl_batch_log
           SET finished_at    = SYSUTCDATETIME(),
               status         = N'SUCCESS',
               rows_processed = @inserted,
               error_msg      = CONCAT(N'mode=', CASE WHEN @full_refresh=1 THEN N'FULL' ELSE N'INCR' END,
                                       N' watermark=', @watermark,
                                       N' deleted=', @deleted,
                                       N' inserted=', @inserted,
                                       N' neutral=', @neutral_movs,
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
