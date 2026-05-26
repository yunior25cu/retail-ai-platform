# Data contract — source ERP tables consumed

The Gold layer reads from **eight `dbo` tables** in the source ERP. We do
not write to any of them. We do not depend on any specific tenant value
or business semantics beyond what is documented below.

If the source ERP changes any of these contracts (column names, types,
filter conventions), the affected refresh procedure(s) need an update.

## Conventions assumed across all tables

- `id_empresa BIGINT` is the tenant key. Every refresh proc filters by it.
- `[delete] BIT` is a soft-delete flag (`1` = logically deleted, ignore).
- `created_at`, `updated_at` are `DATETIME2` audit columns where present.
- Monetary fields ending in `_base` are already converted to the tenant's
  base currency. `_original` variants exist but we do not consume them.
- Foreign keys are by `BIGINT` ids that match the target's primary `id`
  column.

## The eight tables

### 1. `dbo.documento`
Document header for all transactional records (invoices, receipts,
returns, transfers, payments, adjustments — TPT root).

Columns we read: `id`, `id_empresa`, `tipo_documento`, `estado`,
`fecha_emision`, `id_almacen`, `id_moneda`, `tasa_cambio`,
`importe_base`, `importe_total_base`, `[delete]`.

Filters we always apply: `[delete] = 0`. Most facts also filter
`estado IN (1,2)` (1 = draft, 2 = confirmed; 3 = voided, 4 = cancelled).

`tipo_documento` semantics (decoded from the source's kardex stored
procedure):
| Value | Meaning | Stock direction |
|---|---|---|
| 1 | Inventory opening | IN |
| 2 | Goods receipt | IN |
| 3 | Sales invoice | OUT |
| 4 | Return (direction depends on sub-fields) | IN or OUT |
| 5 | Adjustment | depends on sub-type |
| 6 | Issue voucher / transfer | OUT (or IN when destination=4) |
| 7 | Payment | none |
| 8 | Collection | none |

### 2. `dbo.documento_producto`
Document lines. Granularity: 1 row per line of `documento`.

Columns we read: `id`, `id_documento`, `id_producto`, `cantidad`,
`devuelto`, `importe_base`, `descuento`.

Returns are tracked at the line level via `devuelto` — we use this as
the canonical return source (we do **not** also subtract `tipo_documento=4`
documents to avoid double-counting).

### 3. `dbo.producto`
SKU master.

Columns we read: `id`, `id_empresa`, `codigo`, `codigo_barras`,
`denominacion`, `es_servicio`, `id_categoria`, `id_subcategoria`,
`id_unidad_medida`, `id_tipo_producto`, `precio_venta`,
`punto_reorden`, `id_producto` (self-reference for variants),
`[delete]`, `updated_at`.

**Known data-quality issue**: `codigo` can be duplicated within the same
`id_empresa`. The brand-seed procedure dedupes by `codigo`, keeping the
most recently updated row. Any downstream JOIN that uses `codigo` as a
key must dedupe first; JOINs by `id` are safe.

### 4. `dbo.categoria`
Category master. Self-referential 2-level hierarchy.

Columns we read: `id`, `id_empresa`, `codigo`, `denominacion`,
`id_categoria` (parent), `[delete]`.

### 5. `dbo.almacen`
Warehouse / store master.

Columns we read: `id`, `id_empresa`, `codigo`, `denominacion`,
`principal`, `direccion`, `latitude`, `longitude`,
`id_metodo_valuacion`, `[delete]`.

### 6. `dbo.almacen_producto`
Bridge table: 1 row per (warehouse, product) with reorder thresholds.

Columns we read: `id`, `id_almacen`, `id_producto`, `min_stock`,
`max_stock`.

This table's `id` is the join key for `submayor_inventario`. We do not
trust this table as a stock-presence indicator — kardex is canonical.

### 7. `dbo.submayor_inventario`
Kardex / inventory ledger. 1 row per stock movement. The source ERP runs
a stored procedure (`SP_U_SUBMAYOR_INVENTARIO`) that maintains
weighted-average cost (`costo`), accumulated value (`costo_final`) and
running balance (`saldo`) per warehouse-product. We read those columns
as-is; we never recompute them.

Columns we read: `id`, `id_documento`, `id_almacen_producto`, `entrada`,
`salida`, `saldo`, `costo`, `costo_final`, `importe`.

This is the source of truth for: stock snapshots (`fact_stock_weekly`),
the kardex fact (`fact_stock_movements`), and COGS attribution to sales
lines.

### 8. `dbo.moneda` (joined via `dbo.empresa`)
Currency master. We read `codigo` (ISO-style code) to populate
`currency_code` on every fact.

Columns we read from `dbo.empresa`: `id`, `nombre`, `rut`, `id_moneda`.
Columns we read from `dbo.moneda`: `id`, `codigo`.

## Subtype tables (TPT) used to filter document types

These are read only in `EXISTS` / `JOIN` patterns to disambiguate
`tipo_documento`:

- `dbo.factura` — sales invoices (subtype of `documento`)
- `dbo.vale_salida` — issue vouchers (subtype). We use
  `vale_salida.destino = 4` to identify inter-store transfers.

## What we do **not** consume

- Fiscal / electronic invoicing tables (`cfe_*`).
- Accounting / journal tables (`comprobante`, `submayor_contable`,
  `asiento_*`).
- Banking and treasury tables.
- User / security / subscription tables.

These are out of scope for retail analytics. The Gold layer is
intentionally narrow.
