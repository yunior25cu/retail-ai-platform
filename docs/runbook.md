# Runbook

## Initial deployment

1. Pick a target SQL Server database that contains (or is linked to) the
   source ERP `dbo` tables. The reference name in the scripts is
   `pymeconta_local` — adjust the `USE` statement in `10_e2e_dashboard.sql`
   to match your environment.
2. Connect as a user with `CREATE SCHEMA`, `CREATE TABLE`, `CREATE
   PROCEDURE`, and read access on the `dbo` source tables.
3. From SSMS or `sqlcmd`, run the scripts in numeric order:

   ```
   sqlcmd -S <server> -d <database> -E -i sql/gold/01_schema_and_logging.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/02_dim_date.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/03_enrichment_tables.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/04_seeding_procs_emp7.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/05_dimensions_refresh.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/06_1_fact_sales_weekly.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/06_2_fact_stock_weekly.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/06_3_fact_stock_movements.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/06_4_fact_transfers.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/07_analytical_views.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/08_master_orchestrator.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/09_validations.sql
   ```

4. Open `sql/gold/10_e2e_dashboard.sql` in SSMS and execute it. Confirm
   the validations grid shows **16 PASS / 2 WARN / 0 FAIL** (the two
   WARN are expected for the POC profile).

## Nightly refresh

A single call per tenant rebuilds the whole pipeline:

```sql
DECLARE @bid UNIQUEIDENTIFIER;
EXEC gold.sp_refresh_all @tenant_id = <id>, @batch_id = @bid OUTPUT;
SELECT @bid AS batch_id;
```

Then validate:

```sql
EXEC gold.sp_run_validations @tenant_id = <id>;
```

Any row with `status = 'FAIL'` should block downstream consumers from
trusting the snapshot. Investigate using:

```sql
SELECT step_name, status, error_msg, DATEDIFF(MS, started_at, finished_at) AS ms
  FROM gold.etl_batch_log WHERE batch_id = @bid ORDER BY id;

SELECT * FROM gold.etl_data_quality_metrics WHERE batch_id = @bid;
```

## Adding a new tenant

1. Decide tenant id (must exist in `dbo.empresa`).
2. Write equivalent seed procs to `04_seeding_procs_emp7.sql`:
   - `sp_seed_brand_mapping_<alias>` — brand heuristic for that tenant
   - `sp_seed_store_classification_<alias>` — warehouse → retail/depot
   - `sp_seed_business_rules_<alias>` — coverage / obsolescence rules
   - `sp_seed_society_mapping_<alias>` — legal entity name
3. Update `gold.sp_refresh_all` to call the new seeds inside an
   `IF @tenant_id = <new_id>` branch (or remove the guard if you wire
   self-discovery).
4. Run `EXEC gold.sp_refresh_all @tenant_id = <new id>, @batch_id = NULL OUTPUT;`.
5. Validate with `sp_run_validations`; cross-checks 9.6/9.7 must be 0.

## Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `RAISERROR: No se pudo resolver el rango` in `sp_refresh_fact_*_weekly` | `dim_date` doesn't cover the requested window. | Run `EXEC gold.sp_populate_dim_date '<from>', '<to>'`. The master orchestrator extends automatically. |
| Cross-check 9.6 fails by a small amount | Currency conversion drift — `documento.tasa_cambio` changed retroactively. | Re-run the master refresh; sales are window-based, so a full re-load picks up new rates. |
| Cross-check 9.7 fails | Source kardex was recomputed by `SP_U_SUBMAYOR_INVENTARIO` after our incremental movement load. | `EXEC gold.sp_refresh_fact_stock_movements @tenant_id = <id>, @full_refresh = 1`, then re-validate. |
| `gold.dim_sku` shows 0 SKUs after refresh | Tenant has no rows in `dbo.producto` with `[delete] = 0`. | Check the source ERP; verify tenant id. |
| New tenant: `sp_refresh_all` succeeds but `vw_brand_performance` shows everything as `SIN MARCA` | Seed procs for that tenant haven't been written / executed. | Write `sp_seed_brand_mapping_<alias>` and run it before re-refresh. |
| `vw_active_alerts` empty for a tenant with stock issues | `dim_business_rules` empty for that tenant. | Seed business rules with `sp_seed_business_rules_<alias>`. Defaults: cov_min=30, cov_max=90, obsolete=90 days. |

## Performance notes

- POC tenant: full pipeline runs in **<1 second** (100 SKUs, 4 stores,
  ~2.4k kardex rows, ~38 weeks).
- For a tenant in the 10k SKU × 50 store × 250 week range, expect
  `fact_stock_weekly` to dominate (`OUTER APPLY` against the kardex per
  (week, pair)). Mitigations available before considering partitioning:
  - Tighten the dead-pair threshold (`@dead_threshold_days`).
  - Narrow the refresh window (default is from first ever document).
  - Add a covering index on `submayor_inventario(id_almacen_producto,
    id_documento)` if absent in your source DB.
- Indexed views were considered but rejected: most analytical views need
  `LEFT JOIN`, `MAX`, or window functions that disqualify them. Physical
  materialisation can be added later if a specific view becomes hot.

## Safety

- All Gold tables are scoped by `tenant_id` and every refresh proc
  filters on `@tenant_id`. No tenant-leak in either direction.
- Source tables are **read-only** from this pipeline. We never `INSERT`,
  `UPDATE` or `DELETE` against `dbo.*`.
- Log and DQ tables grow without bound. Trim by `batch_id` age in
  production (not done by these scripts).
