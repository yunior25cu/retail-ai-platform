IF OBJECT_ID('gold.sp_run_validations','P') IS NOT NULL DROP PROCEDURE gold.sp_run_validations;
GO
CREATE PROCEDURE gold.sp_run_validations
    @tenant_id BIGINT
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @results TABLE (
        validation_id    NVARCHAR(10)   NOT NULL,
        category         NVARCHAR(20)   NOT NULL,
        validation_name  NVARCHAR(140)  NOT NULL,
        severity_if_fail NVARCHAR(10)   NOT NULL,
        actual_value     DECIMAL(18,4)  NULL,
        threshold        DECIMAL(18,4)  NOT NULL,
        status           NVARCHAR(10)   NOT NULL,
        notes            NVARCHAR(500)  NULL
    );

    DECLARE @v DECIMAL(18,4);

    SELECT @v = COUNT(*) FROM (
        SELECT 1 AS one FROM gold.fact_sales_weekly WHERE tenant_id = @tenant_id
        GROUP BY tenant_id, iso_year_week, store_id, sku_id, brand_id HAVING COUNT(*) > 1
    ) x;
    INSERT @results VALUES ('9.1.a', N'PK', N'fact_sales_weekly: PK duplicates', N'ERROR',
        @v, 0, CASE WHEN @v=0 THEN N'PASS' ELSE N'FAIL' END, NULL);

    SELECT @v = COUNT(*) FROM (
        SELECT 1 AS one FROM gold.fact_stock_weekly WHERE tenant_id = @tenant_id
        GROUP BY tenant_id, iso_year_week, store_id, sku_id HAVING COUNT(*) > 1
    ) x;
    INSERT @results VALUES ('9.1.b', N'PK', N'fact_stock_weekly: PK duplicates', N'ERROR',
        @v, 0, CASE WHEN @v=0 THEN N'PASS' ELSE N'FAIL' END, NULL);

    SELECT @v = COUNT(*) FROM (
        SELECT 1 AS one FROM gold.fact_stock_movements WHERE tenant_id = @tenant_id
        GROUP BY tenant_id, movement_id HAVING COUNT(*) > 1
    ) x;
    INSERT @results VALUES ('9.1.c', N'PK', N'fact_stock_movements: PK duplicates', N'ERROR',
        @v, 0, CASE WHEN @v=0 THEN N'PASS' ELSE N'FAIL' END, NULL);

    SELECT @v = COUNT(*) FROM (
        SELECT 1 AS one FROM gold.fact_transfers WHERE tenant_id = @tenant_id
        GROUP BY tenant_id, transfer_line_id HAVING COUNT(*) > 1
    ) x;
    INSERT @results VALUES ('9.1.d', N'PK', N'fact_transfers: PK duplicates', N'ERROR',
        @v, 0, CASE WHEN @v=0 THEN N'PASS' ELSE N'FAIL' END, NULL);

    SELECT @v = COUNT(*) FROM gold.fact_sales_weekly f
     WHERE f.tenant_id = @tenant_id
       AND NOT EXISTS (SELECT 1 FROM gold.dim_sku ds WHERE ds.tenant_id=f.tenant_id AND ds.sku_id=f.sku_id);
    INSERT @results VALUES ('9.2.a', N'FK', N'fact_sales_weekly -> dim_sku orphans', N'ERROR',
        @v, 0, CASE WHEN @v=0 THEN N'PASS' ELSE N'FAIL' END, NULL);

    SELECT @v = COUNT(*) FROM gold.fact_sales_weekly f
     WHERE f.tenant_id = @tenant_id AND f.store_id > 0
       AND NOT EXISTS (SELECT 1 FROM gold.dim_store ds WHERE ds.tenant_id=f.tenant_id AND ds.store_id=f.store_id);
    INSERT @results VALUES ('9.2.b', N'FK', N'fact_sales_weekly -> dim_store orphans', N'ERROR',
        @v, 0, CASE WHEN @v=0 THEN N'PASS' ELSE N'FAIL' END, NULL);

    SELECT @v = COUNT(*) FROM gold.fact_stock_weekly f
     WHERE f.tenant_id = @tenant_id
       AND NOT EXISTS (SELECT 1 FROM gold.dim_sku ds WHERE ds.tenant_id=f.tenant_id AND ds.sku_id=f.sku_id);
    INSERT @results VALUES ('9.2.c', N'FK', N'fact_stock_weekly -> dim_sku orphans', N'ERROR',
        @v, 0, CASE WHEN @v=0 THEN N'PASS' ELSE N'FAIL' END, NULL);

    SELECT @v = COUNT(*) FROM gold.fact_stock_weekly f
     WHERE f.tenant_id = @tenant_id
       AND NOT EXISTS (SELECT 1 FROM gold.dim_store ds WHERE ds.tenant_id=f.tenant_id AND ds.store_id=f.store_id);
    INSERT @results VALUES ('9.2.d', N'FK', N'fact_stock_weekly -> dim_store orphans', N'ERROR',
        @v, 0, CASE WHEN @v=0 THEN N'PASS' ELSE N'FAIL' END, NULL);

    SELECT @v = COUNT(*) FROM gold.fact_stock_movements f
     WHERE f.tenant_id = @tenant_id
       AND NOT EXISTS (SELECT 1 FROM gold.dim_sku ds WHERE ds.tenant_id=f.tenant_id AND ds.sku_id=f.sku_id);
    INSERT @results VALUES ('9.2.e', N'FK', N'fact_stock_movements -> dim_sku orphans', N'WARN',
        @v, 0, CASE WHEN @v=0 THEN N'PASS' ELSE N'WARN' END,
        N'movs carga independiente; producto borrado puede generar orphans');

    SELECT @v = COUNT(*) FROM gold.fact_transfers f
     WHERE f.tenant_id = @tenant_id
       AND NOT EXISTS (SELECT 1 FROM gold.dim_sku ds WHERE ds.tenant_id=f.tenant_id AND ds.sku_id=f.sku_id);
    INSERT @results VALUES ('9.2.f', N'FK', N'fact_transfers -> dim_sku orphans', N'ERROR',
        @v, 0, CASE WHEN @v=0 THEN N'PASS' ELSE N'FAIL' END, NULL);

    SELECT @v = COUNT(*) FROM gold.fact_sales_weekly
     WHERE tenant_id = @tenant_id AND (gross_margin_pct < -0.5 OR gross_margin_pct > 0.95);
    INSERT @results VALUES ('9.3.a', N'RANGE', N'fact_sales_weekly: margin_pct fuera de [-50%, 95%]', N'WARN',
        @v, 0, CASE WHEN @v=0 THEN N'PASS' ELSE N'WARN' END, NULL);

    SELECT @v = COUNT(*) FROM gold.fact_sales_weekly
     WHERE tenant_id = @tenant_id AND units_sold_net < 0;
    INSERT @results VALUES ('9.3.b', N'RANGE', N'fact_sales_weekly: units_sold_net < 0', N'WARN',
        @v, 0, CASE WHEN @v=0 THEN N'PASS' ELSE N'WARN' END, NULL);

    SELECT @v = COUNT(*) FROM gold.vw_sku_coverage_status
     WHERE tenant_id = @tenant_id AND days_coverage > 365;
    INSERT @results VALUES ('9.3.c', N'RANGE', N'vw_sku_coverage_status: days_coverage > 365', N'WARN',
        @v, 0, CASE WHEN @v=0 THEN N'PASS' ELSE N'WARN' END, NULL);

    SELECT @v = COUNT(*) FROM gold.dim_sku
     WHERE tenant_id = @tenant_id AND is_active = 1 AND brand_id = 0;
    INSERT @results VALUES ('9.4', N'ENRICH', N'dim_sku: SKUs activos sin marca asignada', N'WARN',
        @v, 0, CASE WHEN @v=0 THEN N'PASS' ELSE N'WARN' END, NULL);

    SELECT @v = COUNT(*) FROM gold.dim_store
     WHERE tenant_id = @tenant_id AND is_active = 1 AND block_AB = N'NO CLASIFICADO';
    INSERT @results VALUES ('9.5', N'ENRICH', N'dim_store: tiendas activas sin clasificacion', N'WARN',
        @v, 0, CASE WHEN @v=0 THEN N'PASS' ELSE N'WARN' END, NULL);

    DECLARE @gu DECIMAL(18,4), @du DECIMAL(18,4), @gr DECIMAL(18,4), @dr DECIMAL(18,4);
    SELECT @gu = ISNULL(SUM(units_sold_net), 0),
           @gr = ISNULL(SUM(revenue_net), 0)
      FROM gold.fact_sales_weekly WHERE tenant_id = @tenant_id;

    SELECT @du = ISNULL(SUM(dp.cantidad - ISNULL(dp.devuelto, 0)), 0),
           @dr = ISNULL(SUM(dp.importe_base * (1 - ISNULL(dp.devuelto,0)/NULLIF(dp.cantidad,0))), 0)
      FROM dbo.documento d
      JOIN dbo.documento_producto dp ON dp.id_documento = d.id
     WHERE d.id_empresa = @tenant_id
       AND d.tipo_documento = 3 AND d.estado IN (1,2) AND d.[delete] = 0 AND dp.cantidad > 0;

    SET @v = ABS(@gu - @du);
    INSERT @results VALUES ('9.6.a', N'CROSS', N'sales: SUM(units_sold_net) gold vs direct', N'ERROR',
        @v, 0.01, CASE WHEN @v <= 0.01 THEN N'PASS' ELSE N'FAIL' END,
        CONCAT(N'gold=', @gu, N' direct=', @du));

    SET @v = ABS(@gr - @dr);
    INSERT @results VALUES ('9.6.b', N'CROSS', N'sales: SUM(revenue_net) gold vs direct', N'ERROR',
        @v, 0.01, CASE WHEN @v <= 0.01 THEN N'PASS' ELSE N'FAIL' END,
        CONCAT(N'gold=', @gr, N' direct=', @dr));

    DECLARE @lw CHAR(8) = (SELECT MAX(iso_year_week) FROM gold.fact_stock_weekly WHERE tenant_id = @tenant_id);
    DECLARE @lwe DATE   = (SELECT MAX(week_end_date) FROM gold.dim_date WHERE iso_year_week = @lw);

    DECLARE @gs DECIMAL(18,4), @ds_ DECIMAL(18,4);
    SELECT @gs = ISNULL(SUM(stock_units), 0)
      FROM gold.fact_stock_weekly
     WHERE tenant_id = @tenant_id AND iso_year_week = @lw;

    ;WITH last_per_pair AS (
        SELECT si.id_almacen_producto, si.saldo,
               d.fecha_emision AS last_mov_date,
               ROW_NUMBER() OVER (PARTITION BY si.id_almacen_producto
                                  ORDER BY d.fecha_emision DESC, si.id DESC) AS rn
        FROM dbo.submayor_inventario si
        JOIN dbo.documento d ON d.id = si.id_documento
        WHERE d.id_empresa = @tenant_id AND d.estado IN (1,2) AND d.[delete] = 0
          AND d.fecha_emision <= @lwe
    )
    SELECT @ds_ = ISNULL(SUM(saldo), 0)
      FROM last_per_pair
     WHERE rn = 1
       AND NOT (saldo = 0 AND DATEDIFF(DAY, last_mov_date, @lwe) > 84);

    SET @v = ABS(@gs - ISNULL(@ds_, 0));
    INSERT @results VALUES ('9.7', N'CROSS',
        CONCAT(N'stock: SUM(stock_units) gold vs direct para ', @lw), N'ERROR',
        @v, 0.01, CASE WHEN @v <= 0.01 THEN N'PASS' ELSE N'FAIL' END,
        CONCAT(N'gold=', @gs, N' direct=', ISNULL(@ds_, 0)));

    SELECT validation_id, category, validation_name, severity_if_fail,
           actual_value, threshold, status, notes
      FROM @results
     ORDER BY validation_id;
END;
GO
