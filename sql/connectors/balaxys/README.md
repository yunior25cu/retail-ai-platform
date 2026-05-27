# Conector Balaxys ERP

Scripts específicos del ERP Balaxys (PymeConta) para alimentar
las tablas Gold de retail-ai-platform.

## Archivos

| Archivo | Descripción |
|---|---|
| 03_enrichment_tables.sql | Tablas de enriquecimiento manual (brand_mapping, store_classification, etc.) |
| 04_seeding_procs_emp7.sql | SPs de seeding que leen dbo.producto, dbo.almacen, dbo.documento, etc. |

## Orden de ejecución

Estos scripts se ejecutan DESPUÉS de sql/gold/ (bloques 01-02)
y ANTES de sql/gold/ (bloques 05-11).

Orden completo:
1. sql/gold/01_schema_and_logging.sql
2. sql/gold/02_dim_date.sql
3. sql/connectors/balaxys/03_enrichment_tables.sql   ← acá
4. sql/connectors/balaxys/04_seeding_procs_emp7.sql  ← acá
5. sql/gold/05_dimensions_refresh.sql
6. sql/gold/06_*.sql  (facts)
7. sql/gold/07_analytical_views.sql
8. sql/gold/08_master_orchestrator.sql
9. sql/gold/09_validations.sql
10. sql/gold/10_e2e_dashboard.sql
11. sql/gold/11_monthly_views.sql

## Dependencias

Requiere acceso a las siguientes tablas de Balaxys ERP:
- dbo.producto
- dbo.almacen
- dbo.empresa
- dbo.documento
- dbo.documento_detalle
- dbo.submayor_inventario
- dbo.moneda

Para integrar un ERP diferente, crear sql/connectors/<erp_name>/
siguiendo el mismo patrón. Ver docs/integration-contract.md.
