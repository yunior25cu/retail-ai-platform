-- ============================================================
-- PASO 0 — FORENSE PREVIO (solo lectura)
-- Ejecutar en: GestionProlimpio (192.168.20.42)
-- Compartir TODOS los resultados antes de proceder con FASE 1
-- ============================================================

-- 0a. Confirmar estructura de Recetas
SELECT * FROM dbo.Recetas;

-- 0b. Confirmar estructura de RecetasLineas
SELECT * FROM dbo.RecetasLineas ORDER BY RECETA, LINEA;

-- 0c. Confirmar tablas de pre-producción (Lineas2 / Cabezal2)
SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME IN ('Lineas2', 'Cabezal2')
ORDER BY TABLE_NAME, ORDINAL_POSITION;

-- 0d. Muestra de pre-producción fabricado (Documento = '112')
SELECT TOP 5
    L.Fecha, L.CodArt, L.CantidadDebe, L.CantidadHaber,
    C.Documento, C.NroDoc, C.Facturado, C.Usuario
FROM dbo.Lineas2 L
JOIN dbo.Cabezal2 C
    ON L.Documento = C.Documento
   AND L.NroFact   = C.NroFact
   AND L.NroDoc    = C.NroDoc
WHERE L.Documento = '112'
ORDER BY L.Fecha DESC;

-- 0e. Muestra de órdenes de compra pendientes (Documento = '26')
SELECT TOP 5
    L.Fecha, L.CodArt, L.CantidadDebe, L.CantidadHaber,
    C.Documento, C.NroDoc, C.Facturado
FROM dbo.Lineas2 L
JOIN dbo.Cabezal2 C
    ON L.Documento = C.Documento
   AND L.NroFact   = C.NroFact
   AND L.NroDoc    = C.NroDoc
WHERE L.Documento = '26'
  AND C.Facturado  = 0
ORDER BY L.Fecha DESC;

-- 0f. Stock de componentes clave (verificar que DOYSTOCKDP acepta estos parámetros)
SELECT
    CodArticulo,
    Descripcion,
    dbo.DOYSTOCKDP(GETDATE(), CodArticulo, 'F') AS stock_fabrica
FROM dbo.Articulos
WHERE CodArticulo IN (
    'F1','F2','F20','F15','F119',
    '220005','220011','220084','220104','220126',
    '220128','220139','220140','220144','220200',
    '220024','220026','220032','220105','220109',
    '220115','220131','220132'
)
ORDER BY CodArticulo;

-- 0g. Verificar columnas disponibles en Recetas (por si difieren del spec)
SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'Recetas'
ORDER BY ORDINAL_POSITION;

-- 0h. Verificar columnas disponibles en RecetasLineas
SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'RecetasLineas'
ORDER BY ORDINAL_POSITION;

-- 0i. Confirmar campo Facturado en Cabezal2 y join keys
SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'Cabezal2'
  AND COLUMN_NAME IN ('Documento','NroFact','NroDoc','Facturado','Usuario','DebeHaber')
ORDER BY ORDINAL_POSITION;

-- 0j. Confirmar campo TotalLinea en Lineas2 (usado en SP de OC)
SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'Lineas2'
  AND COLUMN_NAME IN ('Documento','NroFact','NroDoc','CodArt','Fecha',
                      'CantidadDebe','CantidadHaber','TotalLinea','Deposito')
ORDER BY ORDINAL_POSITION;

-- 0k. Confirmar campos CodStock y StockMin en Articulos
SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'Articulos'
  AND COLUMN_NAME IN ('CodArticulo','Descripcion','CodStock','LlevaStock',
                      'NoDisponible','StockMin')
ORDER BY ORDINAL_POSITION;
