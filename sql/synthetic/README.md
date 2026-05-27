# sql/synthetic — Datos sintéticos para tenant_id = 9001

Scripts de población para el tenant de desarrollo y eval. **No contienen datos reales.**

---

## Tenant 9001 — RetailDemo SA

| Atributo | Valor |
|---|---|
| `tenant_id` | `9001` |
| Razón social | RetailDemo SA (Uruguay) |
| Moneda | UYU |
| Marcas | URBAN PRO (1) · SPORT ELITE (2) · BASE LINE (3) |
| Tiendas | 4 retail (T01-T04) + 1 depósito (T05), `store_id` 101-105 |
| SKUs | 200 (80 + 60 + 60 por marca) |
| Semanas | Últimas 52 ISO-semanas desde la fecha de ejecución |

---

## Ejecución

```sql
-- Pre-requisitos: gold schema desplegado (01-11_*.sql) + dim_date poblado
sqlcmd -S <server> -d <database> -U sa -P <password> \
       -i sql/synthetic/01_tenant_9001_seed.sql
```

El script es **idempotente**: borra todos los datos del tenant 9001 y los re-inserta. Se puede ejecutar cuantas veces sea necesario.

---

## Escenarios de alertas generados

| Escenario | SKUs | Descripción |
|---|---|---|
| `OVERSTOCK` | 1-10 | URBAN PRO fast movers con stock excesivo (days_coverage > 75) |
| `UNDERSTOCK` | 11-20 | URBAN PRO fast movers con stock crítico (days_coverage < 21) |
| `OBSOLETE` | 141-155 | BASE LINE sin ventas hace >120 días, con capital inmovilizado |
| `STOCK_ZERO` (HIGH) | 181-190 | BASE LINE con quiebre total + velocidad positiva (impacto alto) |
| `STOCK_ZERO` (MEDIUM) | 191-200 | BASE LINE con quiebre total sin velocidad |
| `GREEN` | resto | Cobertura normal entre target_min y target_max |

---

## Segmentación ABCD de velocidad

| Segmento | SKUs | Descripción |
|---|---|---|
| A | 1-50 | Fast movers (alto volumen 8 semanas) |
| B | 51-100 | Medium movers |
| C | 101-150 | Slow movers |
| D | 151-200 | Dead / sin rotación significativa |

---

## Limitaciones conocidas

- **tickets = 0** en todos los dashboards de tiendas: `vw_store_dashboard` calcula tickets desde `dbo.documento` (ERP). El tenant 9001 no tiene registros en esa tabla, por lo que `tickets` y `avg_ticket` son 0 / NULL. Todos los demás KPIs (revenue, margen, stock) funcionan correctamente.
- Los datos de `fact_sales_weekly` se generan con fórmulas deterministas basadas en `sku_id` e `iso_year_week`, no reflejan estacionalidad real.
- El plan de ventas (`fact_sales_plan`) está fijado en valores constantes por marca; en producción se carga desde el sistema de planificación.

---

## Uso con el eval framework

```bash
# Ejecutar las 20 preguntas del catálogo contra tenant 9001
python -m app.evaluation.cli run --tenant 9001 --text

# Guardar baseline
python -m app.evaluation.cli run --tenant 9001 --output eval_baseline.json

# Después de cambios en prompts: comparar contra baseline
python -m app.evaluation.cli run --tenant 9001 --output eval_after.json
python -m app.evaluation.cli compare eval_baseline.json eval_after.json
```
