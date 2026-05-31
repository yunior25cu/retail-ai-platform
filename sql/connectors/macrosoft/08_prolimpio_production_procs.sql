-- ============================================================
-- FASE 2 — STORED PROCEDURES DE CARGA — PRODUCCIÓN PROLIMPIO
-- Destino: pymeconta_local (gold schema)
-- Fuente:  GestionProlimpio (192.168.20.42)
--
-- Convenciones de casing confirmadas por forense:
--   Cabezal2  → UPPERCASE: DOCUMENTO, NROFACT, NRODOC, FACTURADO, USUARIO, FECHA
--   Lineas2   → mixedCase: Documento, NroFact, NroDoc, Fecha, CodArt,
--                          CantidadDebe, CantidadHaber, TotalLinea
--   Recetas   → UPPERCASE: RECETA, CODARTICULO, DESCRIPCION, CANTIDAD, COSTO
--   RecetasLineas → UPPERCASE: RECETA, LINEA, CODARTICULO, DESCRIPCION,
--                              CANTIDAD, MEDIDA, COSTO
--   Articulos → mixedCase: CodArticulo, Descripcion, CodStock,
--                          LlevaStock, StockMin, NoDisponible
-- ============================================================

-- ────────────────────────────────────────────────────────────
-- SP 1: sp_load_recipe_granel
--   MODO: CSV Bridge (lee de stg.csv_recetas_granel)
--   Para modo Linked Server: reemplazar FROM stg.csv_recetas_granel
--   por JOIN GestionProlimpio.dbo.RecetasLineas + Recetas + Articulos
-- ────────────────────────────────────────────────────────────
CREATE OR ALTER PROCEDURE gold.sp_load_recipe_granel
    @tenant_id INT
AS
BEGIN
    SET NOCOUNT ON;

    TRUNCATE TABLE gold.dim_recipe_granel;

    INSERT INTO gold.dim_recipe_granel (
        tenant_id, recipe_id, granel_sku, granel_name, batch_liters,
        recipe_line, component_sku, component_name, component_type,
        qty_per_batch, qty_per_liter, unit_of_measure, cost_per_batch
    )
    SELECT
        @tenant_id,
        ISNULL(TRY_CAST(src.recipe_id    AS INT), 0),
        LTRIM(RTRIM(src.granel_sku)),
        LTRIM(RTRIM(src.granel_name)),
        ISNULL(TRY_CAST(src.batch_liters AS DECIMAL(12,2)), 0),
        ISNULL(TRY_CAST(src.recipe_line  AS INT), 0),
        LTRIM(RTRIM(src.component_sku)),
        LTRIM(RTRIM(src.component_name)),
        LTRIM(RTRIM(src.component_type)),
        ISNULL(TRY_CAST(src.qty_per_batch AS DECIMAL(18,6)), 0),
        ISNULL(TRY_CAST(src.qty_per_liter AS DECIMAL(18,8)), 0),   -- suele venir vacío en el CSV
        ISNULL(NULLIF(LTRIM(RTRIM(src.unit_of_measure)), ''), 'Uni'),
        TRY_CAST(src.cost_per_batch AS DECIMAL(18,4))
    FROM stg.csv_recetas_granel src;

    PRINT 'Recetas granel cargadas: ' + CAST(@@ROWCOUNT AS NVARCHAR(20));

    -- stg.csv_recetas_producto tiene sku_code + grupo_code (equivale a csv_articulos)
    UPDATE sk
    SET sk.family_code = LTRIM(RTRIM(sa.grupo_code)),
        sk.is_finished = CASE
            WHEN LTRIM(RTRIM(sa.grupo_code)) = '1.1' THEN 1
            ELSE 0 END
    FROM gold.dim_sku sk
    JOIN stg.csv_recetas_producto sa
        ON LTRIM(RTRIM(sa.sku_code)) = sk.sku_code
    WHERE sk.tenant_id = @tenant_id;
    PRINT 'family_code/is_finished actualizados: ' + CAST(@@ROWCOUNT AS NVARCHAR(20));
END;
GO

-- ────────────────────────────────────────────────────────────
-- SP 2: sp_load_recipe_product
--   MODO: CSV Bridge (lee de stg.csv_recetas_producto)
--   Para modo Linked Server: reemplazar FROM stg.csv_recetas_producto
--   por JOIN GestionProlimpio.dbo.RecetasLineas + Recetas + Articulos
--   NOTA: ejecutar este archivo con sqlcmd -I (QUOTED_IDENTIFIER ON)
--   o poner SET QUOTED_IDENTIFIER ON; GO antes de este bloque en SSMS.
-- ────────────────────────────────────────────────────────────
SET QUOTED_IDENTIFIER ON;
GO
CREATE OR ALTER PROCEDURE gold.sp_load_recipe_product
    @tenant_id INT
AS
BEGIN
    SET NOCOUNT ON;

    DELETE FROM gold.dim_recipe_product WHERE tenant_id = @tenant_id;

    -- granel_sku y liters_per_unit: fila granel por producto (tabla con punto en nombre)
    ;WITH granel_info AS (
        SELECT
            LTRIM(RTRIM(product_sku)) AS product_sku,
            MAX(LTRIM(RTRIM(component_sku))) AS granel_sku,
            MAX(ISNULL(TRY_CAST(qty_per_unit AS DECIMAL(18,6)), 0)) AS liters_per_unit
        FROM stg.[csv.recetas_producto]
        WHERE LTRIM(RTRIM(component_type)) = 'granel'
        GROUP BY LTRIM(RTRIM(product_sku))
    ),
    deduped AS (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY LTRIM(RTRIM(product_sku)), LTRIM(RTRIM(component_sku))
                   ORDER BY (SELECT NULL)
               ) AS rn
        FROM stg.[csv.recetas_producto]
    )
    INSERT INTO gold.dim_recipe_product (
        tenant_id, product_sku, product_name, granel_sku,
        liters_per_unit, component_sku, component_name,
        component_type, qty_per_unit, unit_of_measure, is_active
    )
    SELECT
        @tenant_id,
        LTRIM(RTRIM(src.product_sku)),
        LTRIM(RTRIM(src.product_name)),
        ISNULL(gi.granel_sku, ''),
        ISNULL(gi.liters_per_unit, 0),
        LTRIM(RTRIM(src.component_sku)),
        LTRIM(RTRIM(src.component_name)),
        LTRIM(RTRIM(src.component_type)),
        ISNULL(TRY_CAST(src.qty_per_unit AS DECIMAL(18,6)), 0),
        ISNULL(NULLIF(LTRIM(RTRIM(src.unit_of_measure)), ''), 'Uni'),
        1
    FROM deduped src
    LEFT JOIN granel_info gi ON gi.product_sku = LTRIM(RTRIM(src.product_sku))
    WHERE src.rn = 1;

    PRINT 'Recetas producto cargadas: ' + CAST(@@ROWCOUNT AS NVARCHAR(20));

    -- stg.csv_recetas_producto tiene sku_code + grupo_code (equivale a csv_articulos)
    UPDATE sk
    SET sk.family_code = LTRIM(RTRIM(sa.grupo_code)),
        sk.is_finished = CASE
            WHEN LTRIM(RTRIM(sa.grupo_code)) = '1.1' THEN 1
            ELSE 0 END
    FROM gold.dim_sku sk
    JOIN stg.csv_recetas_producto sa
        ON LTRIM(RTRIM(sa.sku_code)) = sk.sku_code
    WHERE sk.tenant_id = @tenant_id;
    PRINT 'family_code/is_finished actualizados: ' + CAST(@@ROWCOUNT AS NVARCHAR(20));
END;
GO

-- ────────────────────────────────────────────────────────────
-- SP 3: sp_refresh_sku_liters
--   Actualiza liters_per_unit en dim_sku. 3 capas de prioridad:
--   CAPA 1 (mayor): manual — nunca sobreescribir
--   CAPA 2 (media): desde dim_recipe_product (liters_per_unit real de receta)
--   CAPA 3 (menor): patrón sobre descripción (auto)
-- ────────────────────────────────────────────────────────────
CREATE OR ALTER PROCEDURE gold.sp_refresh_sku_liters
    @tenant_id INT
AS
BEGIN
    SET NOCOUNT ON;

    -- CAPA 3: patrón sobre descripción (orden mayor→menor para evitar falsos matches)
    UPDATE gold.dim_sku
    SET liters_per_unit = CASE
        WHEN LOWER(sku_name) LIKE '%17900 l%'  THEN 17900.0
        WHEN LOWER(sku_name) LIKE '%11900 l%'  THEN 11900.0
        WHEN LOWER(sku_name) LIKE '%7900 l%'   THEN 7900.0
        WHEN LOWER(sku_name) LIKE '%4900 l%'   THEN 4900.0
        WHEN LOWER(sku_name) LIKE '%2900 l%'   THEN 2900.0
        WHEN LOWER(sku_name) LIKE '%50 l%'     THEN 50.0
        WHEN LOWER(sku_name) LIKE '%30 l%'     THEN 30.0
        WHEN LOWER(sku_name) LIKE '%10 l%'     THEN 10.0
        WHEN LOWER(sku_name) LIKE '%5 l%'      THEN 5.0
        WHEN LOWER(sku_name) LIKE '%3 l%'      THEN 3.0
        WHEN LOWER(sku_name) LIKE '%2 l%'      THEN 2.0
        WHEN LOWER(sku_name) LIKE '%1.5 l%'    THEN 1.5
        WHEN LOWER(sku_name) LIKE '%1.25 l%'   THEN 1.25
        WHEN LOWER(sku_name) LIKE '%1 l%'      THEN 1.0
        WHEN LOWER(sku_name) LIKE '%1lt%'      THEN 1.0
        WHEN LOWER(sku_name) LIKE '%1l %'      THEN 1.0
        WHEN LOWER(sku_name) LIKE '%500 ml%'   THEN 0.5
        WHEN LOWER(sku_name) LIKE '%500ml%'    THEN 0.5
        WHEN LOWER(sku_name) LIKE '%300 ml%'   THEN 0.3
        WHEN LOWER(sku_name) LIKE '%250 ml%'   THEN 0.25
        WHEN LOWER(sku_name) LIKE '%240 ml%'   THEN 0.24
        WHEN LOWER(sku_name) LIKE '%150 ml%'   THEN 0.15
        WHEN LOWER(sku_name) LIKE '%120 ml%'   THEN 0.12
        WHEN LOWER(sku_name) LIKE '%100 ml%'   THEN 0.1
        WHEN LOWER(sku_name) LIKE '%60 ml%'    THEN 0.06
        WHEN LOWER(sku_name) LIKE '%30 ml%'    THEN 0.03
        ELSE NULL
    END,
    liters_source = CASE
        WHEN LOWER(sku_name) LIKE '%17900 l%' OR LOWER(sku_name) LIKE '%11900 l%'
          OR LOWER(sku_name) LIKE '%7900 l%'  OR LOWER(sku_name) LIKE '%4900 l%'
          OR LOWER(sku_name) LIKE '%2900 l%'  OR LOWER(sku_name) LIKE '%50 l%'
          OR LOWER(sku_name) LIKE '%30 l%'    OR LOWER(sku_name) LIKE '%10 l%'
          OR LOWER(sku_name) LIKE '%5 l%'     OR LOWER(sku_name) LIKE '%3 l%'
          OR LOWER(sku_name) LIKE '%2 l%'     OR LOWER(sku_name) LIKE '%1.5 l%'
          OR LOWER(sku_name) LIKE '%1 l%'     OR LOWER(sku_name) LIKE '%1lt%'
          OR LOWER(sku_name) LIKE '%500 ml%'  OR LOWER(sku_name) LIKE '%500ml%'
          OR LOWER(sku_name) LIKE '%300 ml%'  OR LOWER(sku_name) LIKE '%250 ml%'
          OR LOWER(sku_name) LIKE '%150 ml%'  OR LOWER(sku_name) LIKE '%100 ml%'
          OR LOWER(sku_name) LIKE '%60 ml%'   OR LOWER(sku_name) LIKE '%30 ml%'
            THEN 'auto'
        ELSE 'sin_datos'
    END
    WHERE tenant_id = @tenant_id
      AND ISNULL(liters_source, '') NOT IN ('manual', 'recipe');

    -- CAPA 2: desde receta nivel 2 (sobreescribe 'auto' y 'sin_datos')
    UPDATE s
    SET s.liters_per_unit = r.liters_per_unit,
        s.liters_source   = 'recipe'
    FROM gold.dim_sku s
    JOIN (
        SELECT DISTINCT product_sku, liters_per_unit
        FROM gold.dim_recipe_product
        WHERE tenant_id = @tenant_id
          AND liters_per_unit > 0
    ) r ON s.sku_code  = r.product_sku
       AND s.tenant_id = @tenant_id
    WHERE ISNULL(s.liters_source, '') NOT IN ('manual');

    -- Reporte de casos sin datos (para corrección manual)
    SELECT sku_code, sku_name, 'Sin litros detectados' AS issue
    FROM gold.dim_sku
    WHERE tenant_id       = @tenant_id
      AND liters_per_unit IS NULL
      AND is_active        = 1
      AND LOWER(sku_name) NOT LIKE '%materia prima%'
      AND LOWER(sku_name) NOT LIKE '%granel%'
      AND LOWER(sku_name) NOT LIKE '%(mp)%'
    ORDER BY sku_name;

    PRINT 'liters_per_unit actualizado. Ver tabla arriba para casos sin datos.';
END;
GO

-- ────────────────────────────────────────────────────────────
-- SP 4: sp_refresh_component_stock
--   MODO: CSV Bridge (lee de stg.csv_stock_componentes)
--   Para modo Linked Server: reemplazar por Articulos + Grupos + StockArt
--   + cálculo movimientos Lineas2/Cabezal2
--   Override manual: fact_component_stock_override tiene prioridad
-- ────────────────────────────────────────────────────────────
CREATE OR ALTER PROCEDURE gold.sp_refresh_component_stock
    @tenant_id INT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @today DATE = CAST(GETDATE() AS DATE);

    DELETE FROM gold.fact_component_stock
    WHERE tenant_id = @tenant_id AND snapshot_date = @today;

    INSERT INTO gold.fact_component_stock (
        tenant_id, component_sku, component_name, component_type,
        store_code, stock_units, unit_of_measure,
        snapshot_date, is_critical, is_low, stock_min
    )
    SELECT
        @tenant_id,
        LTRIM(RTRIM(src.component_sku)),
        LTRIM(RTRIM(src.component_name)),
        LTRIM(RTRIM(src.component_type)),
        'F',
        -- Override manual tiene prioridad sobre el valor del CSV
        ISNULL(ov.stock_real,
               ISNULL(TRY_CAST(src.stock_units AS DECIMAL(18,4)), 0)),
        'Uni',
        -- formato 103 = dd/mm/yyyy (exportación Excel español); fallback @today
        ISNULL(TRY_CONVERT(DATE, LTRIM(RTRIM(src.snapshot_date)), 103), @today),
        CASE WHEN ISNULL(ov.stock_real,
                         ISNULL(TRY_CAST(src.stock_units AS DECIMAL(18,4)), 0)) <= 0
             THEN 1 ELSE 0 END,
        CASE WHEN ISNULL(ov.stock_real,
                         ISNULL(TRY_CAST(src.stock_units AS DECIMAL(18,4)), 0))
                  < ISNULL(TRY_CAST(src.stock_min AS DECIMAL(18,4)), 0)
             THEN 1 ELSE 0 END,
        TRY_CAST(src.stock_min AS DECIMAL(18,4))
    FROM stg.csv_stock_componentes src
    LEFT JOIN gold.fact_component_stock_override ov
        ON  ov.tenant_id     = @tenant_id
        AND ov.component_sku = LTRIM(RTRIM(src.component_sku));

    -- Actualizar stock efectivo = stock_units + OC pendientes
    UPDATE cs
    SET cs.units_on_order  = ISNULL(po.units_pending, 0),
        cs.stock_effective = cs.stock_units + ISNULL(po.units_pending, 0)
    FROM gold.fact_component_stock cs
    LEFT JOIN (
        SELECT component_sku, SUM(units_pending) AS units_pending
        FROM gold.fact_purchase_orders
        WHERE tenant_id = @tenant_id AND status = 'Pendiente'
        GROUP BY component_sku
    ) po ON cs.component_sku = po.component_sku
    WHERE cs.tenant_id    = @tenant_id
      AND cs.snapshot_date = @today;

    DECLARE @n INT = @@ROWCOUNT;
    PRINT 'Stock de componentes actualizado: ' + CAST(@n AS NVARCHAR(20)) + ' filas';
END;
GO

-- ────────────────────────────────────────────────────────────
-- SP 5: sp_refresh_production_orders
--   Órdenes de producción ejecutadas (Documento='112', FACTURADO=1)
--   Casing: Lineas2 mixedCase, Cabezal2 UPPERCASE
-- ────────────────────────────────────────────────────────────
CREATE OR ALTER PROCEDURE gold.sp_refresh_production_orders
    @tenant_id INT,
    @desde     DATE = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET @desde = ISNULL(@desde, DATEADD(MONTH, -3, GETDATE()));

    DELETE FROM gold.fact_production_orders
    WHERE tenant_id       = @tenant_id
      AND production_date >= @desde;

    INSERT INTO gold.fact_production_orders (
        tenant_id, production_date, iso_year_week,
        sku_code, nro_doc, units_produced,
        liters_produced, operator
    )
    SELECT
        @tenant_id,
        CAST(L.Fecha AS DATE),
        d.iso_year_week,
        LTRIM(RTRIM(L.CodArt)),
        LTRIM(RTRIM(C.NRODOC)),
        SUM(L.CantidadHaber),
        SUM(L.CantidadHaber * ISNULL(sk.liters_per_unit, 0)),
        MAX(LTRIM(RTRIM(C.USUARIO)))
    FROM [GestionProlimpio].[dbo].[Lineas2] L
    JOIN [GestionProlimpio].[dbo].[Cabezal2] C
        ON  L.Documento = C.DOCUMENTO
        AND L.NroFact   = C.NROFACT
        AND L.NroDoc    = C.NRODOC
    JOIN gold.dim_date d
        ON d.date = CAST(L.Fecha AS DATE)
    LEFT JOIN gold.dim_sku sk
        ON  sk.tenant_id = @tenant_id
        AND sk.sku_code  = LTRIM(RTRIM(L.CodArt))
    WHERE L.Documento  = '112'
      AND C.FACTURADO  = 1
      AND CAST(L.Fecha AS DATE) >= @desde
    GROUP BY CAST(L.Fecha AS DATE),
             d.iso_year_week,
             LTRIM(RTRIM(L.CodArt)),
             LTRIM(RTRIM(C.NRODOC));

    PRINT 'Órdenes de producción cargadas: ' + CAST(@@ROWCOUNT AS NVARCHAR(20));
END;
GO

-- ────────────────────────────────────────────────────────────
-- SP 6: sp_refresh_purchase_orders
--   MODO: CSV Bridge (lee de stg.csv_oc_pendientes)
--   Para modo Linked Server: reemplazar por
--   Lineas2 + Cabezal2 + Articulos (Documento='26')
-- ────────────────────────────────────────────────────────────
CREATE OR ALTER PROCEDURE gold.sp_refresh_purchase_orders
    @tenant_id INT
AS
BEGIN
    SET NOCOUNT ON;

    DELETE FROM gold.fact_purchase_orders WHERE tenant_id = @tenant_id;

    -- Deduplicar por (nro_doc, component_sku): mantener la fila más reciente
    ;WITH deduped AS (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY LTRIM(RTRIM(nro_doc)), LTRIM(RTRIM(component_sku))
                   ORDER BY order_date DESC
               ) AS rn
        FROM stg.csv_oc_pendientes
    )
    INSERT INTO gold.fact_purchase_orders (
        tenant_id, order_date, component_sku, component_name,
        nro_doc, units_ordered, units_pending, status, total_cost
    )
    SELECT
        @tenant_id,
        src.order_date,
        LTRIM(RTRIM(src.component_sku)),
        LTRIM(RTRIM(src.component_name)),
        LTRIM(RTRIM(src.nro_doc)),
        src.units_ordered,
        src.units_pending,
        LTRIM(RTRIM(src.status)),
        src.total_cost
    FROM deduped src
    WHERE src.rn = 1;

    PRINT 'Órdenes de compra cargadas: ' + CAST(@@ROWCOUNT AS NVARCHAR(20));
END;
GO

-- ────────────────────────────────────────────────────────────
-- SP 7: sp_refresh_production_plan_weekly
--   Recalcula el plan de producción para las próximas 8 semanas.
--   Cruza: forecast + stock + recetas + componentes bloqueantes.
--   Nota: GREATEST no disponible en SQL Server < 2022; se usa CASE WHEN.
-- ────────────────────────────────────────────────────────────
CREATE OR ALTER PROCEDURE gold.sp_refresh_production_plan_weekly
    @tenant_id INT
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @current_week NCHAR(8) = (
        SELECT iso_year_week FROM gold.dim_date
        WHERE date = CAST(GETDATE() AS DATE)
    );

    DELETE FROM gold.fact_production_plan_weekly
    WHERE tenant_id   = @tenant_id
      AND iso_year_week >= @current_week;

    WITH forecast_weekly AS (
        SELECT
            sku_code,
            iso_year_week,
            SUM(predicted_units) AS predicted_units_week
        FROM gold.fact_demand_forecast
        WHERE tenant_id    = @tenant_id
          AND is_active     = 1
          AND forecast_date >= CAST(GETDATE() AS DATE)
        GROUP BY sku_code, iso_year_week
    ),
    forecast_30d AS (
        SELECT
            sku_code,
            SUM(predicted_units) AS predicted_units_30d
        FROM gold.fact_demand_forecast
        WHERE tenant_id    = @tenant_id
          AND is_active     = 1
          AND forecast_date BETWEEN CAST(GETDATE() AS DATE)
                                AND DATEADD(DAY, 30, GETDATE())
        GROUP BY sku_code
    ),
    stock_current AS (
        SELECT
            LTRIM(RTRIM(s.sku_code)) AS sku_code,
            ISNULL(
                CAST(s.stock_total AS INT), 0
            ) AS stock_current
        FROM stg.csv_stock_productos s
        WHERE ISNULL(CAST(s.stock_total AS INT), 0) >= 0
    ),
    blocking AS (
        SELECT
            rp.product_sku,
            STRING_AGG(
                cs.component_sku + ' (' + CAST(cs.stock_units AS NVARCHAR(20)) + ')',
                ', '
            ) AS blocking_components
        FROM gold.dim_recipe_product rp
        JOIN gold.fact_component_stock cs
            ON  cs.tenant_id     = @tenant_id
            AND cs.component_sku = rp.component_sku
            AND cs.snapshot_date = CAST(GETDATE() AS DATE)
            AND cs.is_critical   = 1
        WHERE rp.tenant_id = @tenant_id
          AND rp.is_active  = 1
        GROUP BY rp.product_sku
    )
    INSERT INTO gold.fact_production_plan_weekly (
        tenant_id, sku_code, iso_year_week,
        predicted_units_week, predicted_units_30d,
        stock_current, stock_final,
        units_to_produce, liters_to_produce,
        days_of_coverage, is_critical,
        has_component_shortage, blocking_components
    )
    SELECT
        @tenant_id,
        fw.sku_code,
        fw.iso_year_week,
        fw.predicted_units_week,
        ISNULL(f30.predicted_units_30d, 0),
        ISNULL(sc.stock_current, 0),
        ISNULL(sc.stock_current, 0),
        -- units_to_produce: max(0, prediccion - stock)
        CASE WHEN fw.predicted_units_week - ISNULL(sc.stock_current, 0) > 0
             THEN fw.predicted_units_week - ISNULL(sc.stock_current, 0)
             ELSE 0 END,
        -- liters_to_produce: units_to_produce * liters_per_unit
        CASE WHEN fw.predicted_units_week - ISNULL(sc.stock_current, 0) > 0
             THEN (fw.predicted_units_week - ISNULL(sc.stock_current, 0))
                  * ISNULL(sk.liters_per_unit, 0)
             ELSE 0 END,
        -- days_of_coverage: stock / (demanda_semanal / 5 días)
        CASE WHEN fw.predicted_units_week > 0
             THEN CAST(ISNULL(sc.stock_current, 0) AS DECIMAL(18,4))
                  / (CAST(fw.predicted_units_week AS DECIMAL(18,4)) / 5.0)
             ELSE NULL END,
        -- crítico si cobertura < 7 días
        CASE WHEN ISNULL(sc.stock_current, 0)
                  < (CAST(fw.predicted_units_week AS DECIMAL(18,4)) / 5.0 * 7)
             THEN 1 ELSE 0 END,
        CASE WHEN b.blocking_components IS NOT NULL THEN 1 ELSE 0 END,
        b.blocking_components
    FROM forecast_weekly fw
    LEFT JOIN forecast_30d  f30 ON f30.sku_code  = fw.sku_code
    LEFT JOIN stock_current  sc ON sc.sku_code   = fw.sku_code
    LEFT JOIN gold.dim_sku   sk ON sk.sku_code    = fw.sku_code
                                AND sk.tenant_id   = @tenant_id
                                AND sk.family_code  = '1.1'
                                AND sk.is_finished  = 1
    LEFT JOIN blocking        b ON b.product_sku = fw.sku_code;

    PRINT 'Plan semanal recalculado para tenant ' + CAST(@tenant_id AS NVARCHAR(20));
END;
GO

-- ────────────────────────────────────────────────────────────
-- Orquestador diario: ejecuta todos los SPs en orden correcto
-- ────────────────────────────────────────────────────────────
CREATE OR ALTER PROCEDURE gold.sp_refresh_production_all
    @tenant_id INT
AS
BEGIN
    SET NOCOUNT ON;
    EXEC gold.sp_load_recipe_granel            @tenant_id;
    EXEC gold.sp_load_recipe_product           @tenant_id;
    EXEC gold.sp_refresh_component_stock       @tenant_id;
    EXEC gold.sp_refresh_purchase_orders       @tenant_id;
    EXEC gold.sp_refresh_production_orders     @tenant_id;
    EXEC gold.sp_refresh_sku_liters            @tenant_id;
    EXEC gold.sp_refresh_production_plan_weekly @tenant_id;
    PRINT 'Módulo producción actualizado completamente para tenant '
          + CAST(@tenant_id AS NVARCHAR(20));
END;
GO
