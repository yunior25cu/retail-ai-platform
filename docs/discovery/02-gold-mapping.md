# Phase 2 — Gold mapping

## Goal

Map each Gold target column to a source ERP column (or to a manually
enriched table). Lock the transformation rules. Decide what cannot be
derived from the source and must be loaded manually.

## Master table — decoded enums

These mappings drive every refresh and view.

### `documento.tipo_documento`
| Value | Meaning | Subtype | Stock direction |
|---|---|---|---|
| 1 | Inventory opening | `apertura_inventario` | IN |
| 2 | Goods receipt | `recepcion` | IN |
| 3 | Sales invoice | `factura` | OUT |
| 4 | Return | `devolucion` | IN/OUT depending on sub-fields |
| 5 | Adjustment | `ajuste` | depends on `ajuste.tipo_ajuste` |
| 6 | Issue voucher / transfer | `vale_salida` | OUT (or IN if `destino=4`) |
| 7 | Payment | `pago` | none |
| 8 | Collection | `cobro` | none |

### `documento.estado`
| Value | Meaning | Gold filter |
|---|---|---|
| 1 | Draft | Excluded from facts; only `vw_sales_pipeline` |
| 2 | Confirmed | INCLUDED |
| 3 | Voided | EXCLUDED |
| 4 | Cancelled | EXCLUDED |

## Dimension mapping

### `gold.dim_sku`

| Gold column | Source | Notes |
|---|---|---|
| `tenant_id` | `producto.id_empresa` | filter scope |
| `sku_id` | `producto.id` | PK part |
| `sku_code` | `producto.codigo` | NOT unique — never join by this |
| `sku_barcode` | `producto.codigo_barras` | |
| `sku_name` | `producto.denominacion` | |
| `is_service` | `producto.es_servicio` | services don't generate kardex |
| `category_id` | `producto.id_categoria` | |
| `subcategory_id` | `producto.id_subcategoria` | |
| `list_price` | `producto.precio_venta` | base price; pricelist resolution at view time |
| `brand_id`, `brand_name` | `dim_brand_mapping` join by `sku_code` | MANUAL — sentinel `(0, 'SIN MARCA')` |
| `season_id`, `season_name`, `season_month` | `dim_season_mapping` via OUTER APPLY (active season today) | MANUAL — sentinel `(0, 'SIN TEMPORADA')` |
| `is_active` | derived: `producto.[delete] = 0` | soft-delete via MERGE |
| `etl_source_hash` | `HASHBYTES('SHA2_256', ...)` over source columns | change-detection |

### `gold.dim_store`

| Gold column | Source | Notes |
|---|---|---|
| `tenant_id` | `almacen.id_empresa` | |
| `store_id` | `almacen.id` | PK part |
| `store_code` / `store_name` | `almacen.codigo` / `denominacion` | |
| `is_main` | `almacen.principal` | |
| `address`, `latitude`, `longitude` | `almacen.direccion`, `latitude`, `longitude` | |
| `is_store_flag` | `dim_store_classification.is_store_flag` | MANUAL |
| `block_AB`, `region` | `dim_store_classification` | MANUAL — defaults `'NO CLASIFICADO'` |
| `society_id` | `dim_society_mapping` | MANUAL |

### `gold.dim_category`

| Gold column | Source | Notes |
|---|---|---|
| `tenant_id` | `categoria.id_empresa` | |
| `category_id` | `categoria.id` | |
| `category_code` / `category_name` | `categoria.codigo` / `denominacion` | |
| `parent_category_id` | `categoria.id_categoria` | self-ref (2 levels deep) |
| `category_level` | derived: `1` if root else `2` | |

## Fact mapping

### `gold.fact_sales_weekly`

Aggregated to (`tenant_id`, `iso_year_week`, `store_id`, `sku_id`,
`brand_id`).

| Gold column | Source / derivation |
|---|---|
| `units_sold_gross` | `SUM(documento_producto.cantidad)` |
| `units_returned` | `SUM(documento_producto.devuelto)` |
| `units_sold_net` | `units_sold_gross - units_returned` |
| `revenue_gross` | `SUM(documento_producto.importe_base)` |
| `revenue_returned` | proportional: `importe_base * devuelto / cantidad` |
| `revenue_net` | `revenue_gross - revenue_returned` |
| `cogs` | `SUM(submayor_inventario.salida * submayor_inventario.costo)` per line |
| `gross_margin` | `revenue_net - cogs` |
| `gross_margin_pct` | `gross_margin / revenue_net` (ratio; NULL if no revenue) |
| `tickets` | `COUNT(DISTINCT documento.id)` *within bucket* — semi-additive |
| `discount_amount` | `SUM(documento_producto.descuento)` |
| `currency_code` | derived from `empresa.id_moneda → moneda.codigo` |

Universal filters on this fact:
- `documento.tipo_documento = 3` (invoices only)
- `documento.estado IN (1, 2)`
- `documento.[delete] = 0`
- `documento_producto.cantidad > 0`

### `gold.fact_stock_weekly`

Snapshot at end-of-week per (`tenant_id`, `iso_year_week`, `store_id`,
`sku_id`). **Forward-filled**: every alive pair gets a row every week,
even when no movement occurred.

| Gold column | Derivation |
|---|---|
| `stock_units` | `submayor_inventario.saldo` of the latest movement with `fecha_emision <= week_end_date` |
| `stock_value` | `submayor_inventario.costo_final` (already a money value) |
| `unit_cost` | `submayor_inventario.costo` (PMP unit cost) |
| `stock_min`, `stock_max` | `almacen_producto.min_stock`, `max_stock` |
| `last_sale_date` | OUTER APPLY over `documento.tipo_documento=3` per (`store_id`, `sku_id`) |
| `last_movement_date` | from the same OUTER APPLY that resolves the saldo |
| `is_obsolete_flag` | `days_since_last_sale > rule.days_no_sale_obsolete` (default 90) |

**Dead-pair filter**: pairs with last `saldo = 0` and no movement for
more than `@dead_threshold_days` (default 84 = 12 weeks) are excluded.

### `gold.fact_stock_movements`

1 row per kardex movement. Incremental by `submayor_inventario.id`
watermark. Direction (`ENTRADA` / `SALIDA` / `AJUSTE` / `NEUTRO`)
derived from the sign of `entrada` and `salida` (more useful than
re-encoding the full SP logic).

### `gold.fact_transfers`

1 row per line of `vale_salida` with `destino = 4` (the source SP
defines `destino=4` as an inter-warehouse transfer that generates both
an OUT in origin and an IN in destination). Origin = `documento.id_almacen`,
destination = `vale_salida.id_almacen_destino`.

### `gold.fact_sales_plan`

100% manual. POC seeding: `planned_* = historical * 1.10` grouped by
(`iso_year_week`, `brand_id`). For real customers, replace the seed proc
with admin-uploaded data.

## Manual enrichment tables (no source mapping)

| Table | Purpose |
|---|---|
| `dim_brand_mapping` | `tenant_id × sku_code → brand_id, brand_name, business_type` |
| `dim_season_mapping` | `tenant_id × sku_code × season_id → start/end dates, season_month` |
| `dim_store_classification` | `tenant_id × store_id → is_store_flag, block_AB, region` |
| `dim_society_mapping` | `tenant_id → society_id, society_name, rut` |
| `dim_business_rules` | priority-ordered coverage / obsolescence / action rules with `(brand_id, category_id, season_month)` matching |
| `fact_sales_plan` | tenant × week × brand × plan_version → planned units / revenue |

Each table has a sentinel row (`tenant_id = 0`) so downstream queries
can `COALESCE` safely.

## Validation queries used during discovery

These are the gates that locked the mapping:

1. **`tipo_documento` distribution** with TPT subtype joins — confirmed
   which value corresponds to invoices, returns, transfers, etc.
2. **`estado` distribution per `tipo_documento`** — confirmed which
   values are voided / cancelled.
3. **`atributo` catalogue search** — confirmed no brand/season/talle
   attributes are populated for the POC tenant (despite the EAV
   structure existing).
4. **Returns: count of `tipo=4` docs vs. lines with `devuelto > 0`** —
   confirmed the double-tracking, forced the decision to use only
   `devuelto`.
5. **Cost source check** — confirmed `producto.costo = 0` for all 100
   active products, validated that `submayor_inventario.costo` is the
   trustworthy source.
6. **Read the stored procedure source** for the kardex roll-forward —
   confirmed the meaning of each `tipo_documento` and the sub-rules for
   returns and adjustments.
7. **Cross-checks** — `SUM(units_sold_net)`, `SUM(revenue_net)`,
   `SUM(stock_units)` Gold vs. direct queries against the source, exact
   to the cent.

Cross-check results are documented in
[03-validation-results.md](03-validation-results.md).
