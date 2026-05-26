# Phase 1 — ERP discovery

## Scope

Reverse-engineer the source ERP schema to understand:
1. What it actually is (vs. what we expected).
2. Which entities we can map directly to a retail analytical model.
3. Which retail concepts are **missing** and must be enriched manually.

## What was inspected

- `INFORMATION_SCHEMA.TABLES` / `COLUMNS` — full column catalogue.
- `sys.foreign_keys` / `sys.foreign_key_columns` — declared relationships.
- `sys.primary_keys` — PK structure.
- A handful of `SELECT TOP N` samples per key table for one tenant.
- The kardex stored procedure (`SP_U_SUBMAYOR_INVENTARIO`) source text,
  to decode the business semantics of `tipo_documento`,
  `tipo_devolucion`, `tipo_ajuste` and the cost-roll-forward algorithm.

## Headline findings

1. **The ERP is a generic multi-tenant invoicing / inventory / accounting
   SaaS**, not a retail-specific platform. 194 tables, 396 declared
   foreign keys.

2. **Multi-tenant model**: every operational table carries `id_empresa`.
   The `empresa` table is the tenant root.

3. **TPT (Table-Per-Type) inheritance on documents.** A single
   `documento` header carries common fields (number, status, dates,
   totals, tenant, warehouse, partner). Subtype tables share the same
   `id` and add type-specific columns:

   | `tipo_documento` | Subtype table | Meaning |
   |---|---|---|
   | 1 | `apertura_inventario` | Inventory opening |
   | 2 | `recepcion` | Goods receipt |
   | 3 | `factura` | Sales invoice |
   | 4 | `devolucion` | Return |
   | 5 | `ajuste` | Inventory adjustment |
   | 6 | `vale_salida` | Issue voucher / transfer |
   | 7 | `pago` | Outgoing payment |
   | 8 | `cobro` | Customer collection |

4. **Document status** (`documento.estado`):
   - `1` — draft (rare)
   - `2` — confirmed (normal)
   - `3` — voided
   - `4` — cancelled

   The Gold layer treats `1` and `2` as valid; `3` and `4` are excluded.

5. **Returns are double-tracked.** Both a separate `documento` of
   `tipo=4` *and* the `devuelto` column on the original invoice line are
   updated. Using both would double-count returns. Gold uses only
   `documento_producto.devuelto`.

6. **Cost is computed by a stored procedure** with weighted-average
   moving cost (PMP). `producto.costo` is frequently zero or stale; the
   trustworthy unit cost lives on every kardex row in
   `submayor_inventario.costo`. The source SP also maintains
   `costo_final` (accumulated value) and `saldo` (running balance) per
   warehouse-product.

7. **`producto.codigo` is not unique** within `id_empresa` — verified
   for the POC tenant. Any join that uses `codigo` as a key must dedupe
   first.

8. **Retail-specific concepts absent from the data model**:

   | Concept | Status in ERP |
   |---|---|
   | Brand | not modelled anywhere (not even as `atributo`) |
   | Season / month-in-season | absent |
   | Store classification (retail / warehouse / outlet) | absent — `almacen` has no type column |
   | Legal entity / society grouping | absent (each `empresa` is treated as one) |
   | Coverage / obsolescence rules | absent |
   | Sales plan / budget | absent |
   | Product variants (size × colour) | partially modelled via `atributo` EAV but unused for the POC tenant |

## Implication for Gold

The Gold layer must:

1. Reuse the eight ERP tables that *do* exist cleanly (`documento`,
   `documento_producto`, `producto`, `categoria`, `almacen`,
   `almacen_producto`, `submayor_inventario`, `moneda`).
2. Create **manual enrichment tables** for the missing retail concepts
   (brand, season, store classification, society, business rules, sales
   plan). These are admin-loaded, not derivable from the ERP.
3. Normalise the cost source to the kardex, never trust
   `producto.costo`.
4. Normalise return handling to the line-level field, never the
   separate return document.
5. Filter on `[delete] = 0` and `estado IN (1, 2)` universally for facts
   (`estado = 1` allowed only for the sales-pipeline view).

## POC tenant profile (for context, not for distribution)

- ~100 active products, ~1,500 invoice lines, ~1,600 kardex movements,
  ~38 weeks of history at discovery time.
- 4 warehouses — all B2B-flavoured (main depot + functional sub-depots),
  no actual retail stores.
- One base currency, no FX activity.
- This profile is intentionally narrow — the goal is to validate the
  pipeline mechanics, not commercial coherence.
