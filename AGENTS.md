# AGENTS.md — reglas para IA que modifica este repo

> **Leer ANTES de tocar código.** Este repo soporta dos motores de base
> de datos en paralelo (SQL Server y PostgreSQL). Casi todos los bugs
> introducidos por agentes IA en los últimos sprints vinieron de cambiar
> una rama y olvidar la otra. Las reglas de abajo no son sugerencias —
> son la única defensa que hay contra ese drift.

---

## 1. Arquitectura dual-DB en una pantalla

```
                ┌──────────────────┐
   /chat ─────► │  internal.py     │
                │  /chat /metrics  │
                └────────┬─────────┘
                         │
                  is_postgres(tenant_id) ?
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
        SQL Server              PostgreSQL
        ─────────────           ─────────────
        execute_query()         _execute_pg() / _execute_pg_write()
        Schemas:                Schemas:
        - gold.*                - gold_t24.*
        - api_audit.*           - audit.* + config.* + auth.*
        Sintaxis:               Sintaxis:
        - MERGE                 - INSERT ... ON CONFLICT
        - TOP N                 - LIMIT N
        - ISNULL                - COALESCE
        - GETDATE(), DATEADD    - CURRENT_DATE, INTERVAL
        - IDENTITY, BIT         - SERIAL/BIGSERIAL, BOOLEAN
        - NVARCHAR, DATETIME2   - VARCHAR, TIMESTAMP
        - ? placeholder         - %s (psycopg2) — convertido por
                                  _convert_placeholders()
        Tenants:                Tenants:
        7, 23, ...              24 (Prolimpio), por env PG_TENANTS
```

Routing real: [api/app/db/connections.py](api/app/db/connections.py) —
`is_postgres(tenant_id)`, `execute_query_tenant(...)`, helpers de dialecto
(`coalesce`, `top_n_expr`, `limit_expr`, `current_date_expr`, etc.).

---

## 2. Reglas críticas — leer antes de cada cambio

### 2.1 Si tocás un archivo con `is_postgres(...)`, tenés que mirror el cambio

Estos son los archivos con branching dual ACTUALMENTE:

```
api/app/db/tenant_config.py
api/app/db/conversation.py
api/app/audit/persister.py
api/app/tools/production_tools.py
api/app/db/connections.py
```

**Regla**: si modificás la rama SS, escribí la PG equivalente en el mismo
commit. Si la rama PG no aplica (ej. una tabla que solo existe en SS),
deja un comentario `# PG: N/A — table is SS-only` con razón.

### 2.2 Si agregás una columna a una tabla dual-routed, escribilá en LOS DOS schemas

Pares dual-routed schema-equivalentes (deben tener las MISMAS columnas):

| SQL Server | PostgreSQL | Definido en | Validado por |
|---|---|---|---|
| `api_audit.ai_tenant_config` | `config.tenant_config` | `sql/gold/13_tenant_config.sql` + `db/migrations/001_create_schemas.sql` | `test_schema_parity.py` ✓ |
| `gold.dim_sku` (tenant 23) | `gold_t23.dim_sku` | `db/migrations/008_create_retail_schemas.sql` | `test_schema_parity.py` ✓ |
| `gold.dim_store` (tenant 23) | `gold_t23.dim_store` | idem | ✓ |
| `gold.dim_category` (tenant 23) | `gold_t23.dim_category` | idem | ✓ |
| `gold.dim_business_rules` (tenant 23) | `gold_t23.dim_business_rules` | idem | ✓ |
| `gold.fact_sales_weekly` (tenant 23) | `gold_t23.fact_sales_weekly` | idem | ✓ |
| `gold.fact_stock_weekly` (tenant 23) | `gold_t23.fact_stock_weekly` | idem | ✓ |
| `gold.fact_sales_plan` (tenant 23) | `gold_t23.fact_sales_plan` | idem | ✓ |
| `gold.dim_reactor` (tenant 24) | `gold_t24.dim_reactor` | `sql/connectors/macrosoft/07_prolimpio_production_schema.sql` + `db/migrations/001_create_schemas.sql` | (agregar al test) |
| `gold.fact_production_orders` (tenant 24) | `gold_t24.fact_production_orders` | idem | (agregar al test) |
| `gold.fact_component_stock` (tenant 24) | `gold_t24.fact_component_stock` | idem | (agregar al test) |
| (otras `gold.*` dim/fact) | (otras `gold_t<N>.*`) | idem | (agregar al test) |

**Cuando un tenant retail se migra de SS a PG** (como tenant 23):
1. Crear `gold_t<N>.*` con las 8 tablas (`008_create_retail_schemas.sql`).
2. Portar las 9 vistas analíticas (`009_create_retail_views.sql`).
3. Ejecutar `010_migrate_data_t<N>.py` (DELETE+INSERT idempotente).
4. Refactor de `queries.py` ya cubre dual-routing via `execute_query_tenant`
   + `_translate_ss_to_pg` (no rehacer).
5. Sembrar `auth.tenants` con `platform_tenant_id=<N>` + `config.tenant_config`
   + usuarios (`011_seed_*_admin.py`).
6. Limpiar SS: `DELETE FROM gold.* WHERE tenant_id=<N>` (`012_cleanup_*.sql`).
7. Agregar los pares al `DUAL_ROUTED_TABLES` del parity test.

**Pares dual-routed estructuralmente distintos** (no validados por
paridad — la divergencia es por diseño):

| SQL Server | PostgreSQL | Por qué difiere |
|---|---|---|
| `api_audit.ai_audit_log` | `audit.conversation_log` | SS: 1 row por chat con hashes; PG: 1 row por mensaje. Funcionalmente equivalentes para el cálculo de gasto, no para parity. |

**Regla**: al agregar un campo a un side, agregalo al otro en el mismo
commit. El test de paridad ([test_schema_parity.py](api/tests/test_schema_parity.py))
falla si te olvidás de uno.

### 2.3 Si agregás un setting nuevo a `tenant_config`, tocá los 5 lugares

Checklist obligatorio para `tenant_config.py`:

- [ ] Campo en el dataclass `TenantConfig` (con default sensato)
- [ ] Clave string en `_VALID_KEYS` (frozenset)
- [ ] Branch en `_apply_row` para coerce string → tipo (silent on error)
- [ ] Default agregado a la CTE `defaults` en
      [sql/gold/13_tenant_config.sql](sql/gold/13_tenant_config.sql)
- [ ] Default agregado al seed de `config.tenant_config` en
      [db/migrations/](db/migrations/) (si aplica)
- [ ] Validación per-key en `_validate_config_value` de
      [api/app/api/v1/internal.py](api/app/api/v1/internal.py)
- [ ] Al menos un test (válido + inválido) en
      [api/tests/test_api/test_internal_config.py](api/tests/test_api/test_internal_config.py)
- [ ] Mapeo a `rate_limit_for_role` si es un nuevo rate-limit por rol

### 2.4 Nunca escribir SQL crudo cuando hay un helper

| En lugar de... | Usar... |
|---|---|
| `ISNULL(x, 0)` / `COALESCE(x, 0)` | `f"{coalesce(tenant_id)}(x, 0)"` |
| `TOP 10 ...` o `... LIMIT 10` | `top_n_expr(tenant_id)` + `limit_expr(tenant_id)` |
| `CAST(GETDATE() AS DATE)` o `CURRENT_DATE` | `current_date_expr(tenant_id)` |
| `DATEADD(WEEK, -N, ...)` | `weeks_ago_expr(tenant_id)` |
| Hardcodear `gold.` o `gold_t24.` | `gold_schema(tenant_id)` |

Si necesitás un helper que no existe, **creálo en `connections.py`** y
documentalo acá — no inlinees el ternario `if is_postgres else`.

### 2.4-bis Toda nueva tabla/columna que el código va a LEER necesita backfill

> **Regla**: si tu PR introduce una tabla o columna que el código **empieza
> a leer** (no solo a escribir), el PR DEBE incluir un script de migration
> que pueble esa tabla/columna desde la fuente anterior. Sin backfill, los
> registros pre-existentes generan 404, null o métricas incorrectas al
> ser consultados.

Diferencia clave:

| Caso | Backfill obligatorio |
|---|---|
| Agregás columna que solo se escribe a futuro (`updated_by`) | **No** (lecturas tolerarán NULL) |
| Agregás columna nullable que algún SELECT consume sin coerce | **Sí** o garantizá que el SELECT use COALESCE |
| Agregás tabla nueva (`audit.conversation`) y un endpoint la consulta como gate | **Sí** — sin backfill, todo conv_id pre-existente devuelve 404 |
| Renombrás tabla o cambiás de schema | **Sí** — migrate the data o un VIEW de compatibilidad |
| Cambiás un campo de NULL a NOT NULL | **Sí** — populate los NULL antes del ALTER |

Checklist para el PR:

- [ ] El nuevo `CREATE TABLE` / `ALTER TABLE` está en
      `db/migrations/NNN_*.sql` (PG) y/o `sql/gold/NNN_*.sql` (SS).
- [ ] **HAY un script `db/migrations/NNN+1_backfill_*.sql`** que pobla
      la nueva tabla/columna desde la fuente previa (otra tabla, log,
      cálculo derivado).
- [ ] El backfill es **idempotente** (`WHERE NOT EXISTS`,
      `ON CONFLICT DO NOTHING`, etc.) — re-ejecutarlo no duplica filas
      ni rompe nada.
- [ ] El backfill se ejecutó en la base local antes del commit
      (incluí el resultado del `RAISE NOTICE` o equivalente en el
      mensaje del PR).
- [ ] Si la fuente previa puede tener datos en LOS DOS motores (SS y PG)
      pero solo migrás uno, documentalo: "backfill aplica solo a PG
      porque la tabla anterior X solo existía en PG".

Pregunta de oro antes de cerrar el PR:
> "Si un cliente usa el sistema hoy con datos pre-existentes,
> ¿alguna query nueva va a devolver 404 / null / cero cuando antes
> daba un resultado válido?" Si la respuesta es "sí", falta backfill.

Ver migration `007_backfill_audit_conversation.sql` como ejemplo: el
commit `662202e` introdujo `audit.conversation` pero olvidó poblarla;
los conv_ids viejos quedaron huérfanos y el primer follow-up rompió.

### 2.5 Tipos SQL — tabla de equivalencias

| Concepto | SQL Server | PostgreSQL |
|---|---|---|
| Auto-increment PK | `BIGINT IDENTITY(1,1) PRIMARY KEY` | `BIGSERIAL PRIMARY KEY` |
| Auto-increment INT | `INT IDENTITY(1,1)` | `SERIAL` |
| Bool | `BIT NOT NULL DEFAULT 1` | `BOOLEAN NOT NULL DEFAULT TRUE` |
| String unicode | `NVARCHAR(N)` | `VARCHAR(N)` |
| Texto largo | `NVARCHAR(MAX)` | `TEXT` |
| Timestamp UTC | `DATETIME2(3)` con `SYSUTCDATETIME()` | `TIMESTAMPTZ` con `NOW()` |
| UUID | `UNIQUEIDENTIFIER` con `NEWID()` | `UUID` con `gen_random_uuid()` |
| Decimal money | `DECIMAL(12,2)` | `NUMERIC(12,2)` |
| JSON | `NVARCHAR(MAX)` (string) | `JSONB` |

### 2.6 Idiomas SQL que rompen al cambiar de motor

| SQL Server | PostgreSQL |
|---|---|
| `MERGE target USING source ON ... WHEN MATCHED THEN UPDATE ... WHEN NOT MATCHED THEN INSERT ...` | `INSERT ... ON CONFLICT (cols) DO UPDATE SET col = EXCLUDED.col` |
| `SELECT TOP N ...` | `SELECT ... LIMIT N` |
| `WITH (NOLOCK)` | (no aplica, ignorar o usar `READ UNCOMMITTED` por sesión) |
| `OFFSET N ROWS FETCH NEXT M ROWS ONLY` | `LIMIT M OFFSET N` |
| `STRING_AGG(x, ',')` con `WITHIN GROUP (ORDER BY ...)` | `STRING_AGG(x, ',' ORDER BY ...)` |
| `FORMAT(x, 'yyyy-MM')` | `TO_CHAR(x, 'YYYY-MM')` |
| `CONVERT(NVARCHAR, x, 23)` | `TO_CHAR(x, 'YYYY-MM-DD')` |
| `IIF(cond, a, b)` | `CASE WHEN cond THEN a ELSE b END` |
| `LEN(s)` | `LENGTH(s)` o `CHAR_LENGTH(s)` |
| `CHARINDEX(needle, hay)` | `POSITION(needle IN hay)` |
| `[brackets]` para identificadores | `"double quotes"` |

### 2.7 Placeholders en queries

- **SS (pyodbc)**: `?` posicional. `execute_query(sql, (a, b))`.
- **PG (psycopg2)**: `%s` posicional. Pero las queries en este repo se
  escriben con `?` y `_convert_placeholders()` las traduce. **Mantené `?`**
  cuando uses `_execute_pg` o `_execute_pg_write` — el conversor lo maneja.
- Si escribís SQL puro con `%s` en una query PG, el conversor no lo toca
  pero psycopg2 lo entiende. Preferí `?` para que el código se vea igual.

---

## 3. Checklist obligatorio antes de cerrar un cambio

Si tu cambio toca cualquier archivo de la lista en 2.1 o tablas de la
lista en 2.2:

```
[ ] ¿Modifiqué la rama SS?
[ ] ¿Modifiqué la rama PG equivalente?
[ ] ¿Agregué/actualicé el schema en LOS DOS archivos de migración?
[ ] ¿Pasa pytest api/tests/test_schema_parity.py?
[ ] ¿Pasan los tests de la feature (test_internal_*.py)?
[ ] ¿Si toqué un endpoint, agregué fixture de tenant SS Y de tenant PG?
[ ] ¿Mi diff usa helpers de connections.py (coalesce, top_n_expr, …)
    en lugar de hardcodear sintaxis de un motor?
```

---

## 4. Cosas que NUNCA hacer

- ❌ Agregar `if is_postgres(...)` adentro de funciones de negocio.
  El branching va en la capa de datos (`connections.py`, helpers).
  Si la lógica de negocio se ramifica por motor, tenés un bug arquitectónico.
- ❌ Copiar un schema SS y pegarlo "casi igual" como PG sin traducir tipos.
- ❌ Asumir que `gold.<tabla>` existe en PG. Para tenant PG es `gold_t<id>.<tabla>`.
- ❌ Hardcodear `tenant_id = 24` o `if tenant_id == 24`. Usá `is_postgres()`.
- ❌ Cambiar `connections.py` sin actualizar este archivo.
- ❌ Pushear sin correr `pytest api/tests/test_schema_parity.py` cuando
  tocaste una tabla dual-routed.

---

## 5. Cómo correr los tests de paridad

```bash
cd D:/PymeConta_dev/retail-ai-platform/api
.venv/Scripts/python.exe -m pytest tests/test_schema_parity.py -v
```

Requiere ambos motores corriendo. Si uno no está disponible, el test
**skipea con un mensaje claro** — no falla silenciosamente.

---

## 6. Memoria histórica de bugs causados por drift

Documentar acá cualquier bug que se haya introducido por no seguir las
reglas de arriba. Eso convierte el AGENTS.md en una memoria viva.

| Fecha | Bug | Causa | Cómo se detectó | Prevención que falló |
|---|---|---|---|---|
| 2026-05-30 | `tenant_config.py` agregó campo `vertical` al dataclass pero no al schema PG → tenant 24 nunca leía el valor | Sub-fase 6.7 no contempló dual-routing | Manual al testear Prolimpio | No existía AGENTS.md ni test de paridad — este archivo lo arregla |
| 2026-06-01 | Conv_id pre-existente devolvía 404 al hacer follow-up. Commit `662202e` agregó `audit.conversation` y la usó como gate en `load_conversation`, pero no migró los conv_ids que ya estaban en `audit.conversation_log` | Migración de schema sin migración de datos | Usuario reportó "POST /chat → 404 conversation_not_found_for_tenant" en BD que tenía 4 mensajes en log para ese UUID | Backfill no era obligatorio. Migration `007_backfill_audit_conversation.sql` rellena los huérfanos. Regla nueva 2.4-bis exige backfill en todo PR que agregue tabla/columna que el código lee |
| 2026-06-01 | Tenant 23 (Demo Retail) migrado de SS a PG. queries.py estaba hardcodeado a `FROM gold.*` (sintaxis TSQL) — sin dual-routing iba a romper apenas hubiera un tenant retail en PG | Capa de datos no preparada para dual-DB; tools de retail eran SS-only | Detectado en el forense del plan de migración (no llegó a producción) | Transformer `_translate_ss_to_pg` en `connections.py` adapta runtime; `queries.py` ahora usa `execute_query_tenant`. Patrón documentado en §2.6 y 7 pares nuevos agregados al parity test |

---

## 7. Reglas para sub-fases nuevas (6.8+)

Cuando armes el spec de una sub-fase nueva, si toca cualquier área dual:

1. En el Paso 0 (forense), buscar todos los `is_postgres(...)` afectados
   y listarlos.
2. En el Paso de schema, generar LOS DOS migration files en el mismo PR.
3. En el Paso de tests, agregar un test que corra con `tenant_id=7` (SS)
   y otro con `tenant_id=24` (PG) — no asumas que pasar el de SS implica
   que pasa el de PG.
4. Antes del commit, correr el test de paridad de schemas.
