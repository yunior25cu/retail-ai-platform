"""Tools de producción — módulo Prolimpio.

6 tools para el jefe de producción:
  get_production_forecast       → plan semanal de qué producir
  get_component_requirements    → MP y envases necesarios para una corrida
  get_reactor_schedule          → cómo distribuir litros entre reactores
  get_coverage_alert            → urgencia por cobertura de stock
  get_component_stock           → stock actual de insumos y componentes
  get_production_history        → producción real vs. predicción
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field

from app.db.connection import execute_query

# ── Constantes de herramienta ─────────────────────────────────────────────────

TOOL_NAME_FORECAST          = "get_production_forecast"
TOOL_NAME_REQUIREMENTS      = "get_component_requirements"
TOOL_NAME_REACTOR           = "get_reactor_schedule"
TOOL_NAME_COVERAGE          = "get_coverage_alert"
TOOL_NAME_COMP_STOCK        = "get_component_stock"
TOOL_NAME_HISTORY           = "get_production_history"

TOOL_DESC_FORECAST = (
    "Retorna el plan de producción para las próximas semanas. "
    "Para cada producto muestra: predicción de demanda, stock actual, "
    "unidades a producir, litros a producir y días de cobertura. "
    "Incluye alertas de productos críticos (cobertura < 7 días). "
    "Usar cuando el jefe pregunta qué producir esta semana o en un período."
)
TOOL_DESC_REQUIREMENTS = (
    "Calcula los componentes y materia prima necesarios para producir "
    "una cantidad dada de un producto. Cruza las recetas nivel 1 (granel) "
    "y nivel 2 (envasado) con el stock actual de componentes. "
    "Indica qué está disponible, qué falta y cuánto falta. "
    "Usar cuando preguntan qué necesitan para producir X unidades de Y producto."
)
TOOL_DESC_REACTOR = (
    "Calcula cómo distribuir la producción entre los reactores disponibles. "
    "Dado un total de litros a producir, sugiere cuántos lotes hacer en cada "
    "reactor (pequeño 200 L o grande 5000 L) y en qué orden. "
    "Minimiza lotes incompletos. "
    "Usar cuando preguntan cómo organizar la producción del día o semana."
)
TOOL_DESC_COVERAGE = (
    "Lista productos ordenados por urgencia de producción. "
    "Calcula días de cobertura = stock actual / demanda diaria promedio. "
    "Agrupa en: CRÍTICO (< 7 días), ALERTA (7-15 días), NORMAL (> 15 días). "
    "También muestra si hay componentes bloqueantes para producir. "
    "Usar cuando preguntan qué es más urgente producir."
)
TOOL_DESC_COMP_STOCK = (
    "Muestra el stock actual de todos los componentes y materia prima. "
    "Separa en: quimico (LEES, ácidos, soda…), granel (F1, F2…), "
    "envase (botellas, tapas, gatillos), etiqueta, fragancia. "
    "Incluye órdenes de compra pendientes de recibir. "
    "Usar cuando preguntan por stock de insumos o qué falta comprar."
)
TOOL_DESC_HISTORY = (
    "Muestra lo que se produjo realmente en un período, "
    "comparado con la predicción del modelo. "
    "Útil para evaluar precisión del modelo y detectar sobre/sub-producción. "
    "También muestra órdenes de compra de componentes del período. "
    "Usar cuando preguntan qué se produjo, cuánto se compró o "
    "cómo estuvo la precisión del modelo."
)


# ── Modelos de entrada ─────────────────────────────────────────────────────────

class GetProductionForecastInput(BaseModel):
    semanas: int = Field(
        default=2, ge=1, le=8,
        description="Semanas a incluir (1-8, default 2)",
    )
    solo_criticos: bool = Field(
        default=False,
        description="Si true, solo productos con cobertura < 7 días",
    )
    familia: str | None = Field(
        default=None,
        description="Filtrar por familia/categoría (ej: 'Desengrasantes')",
    )


class GetComponentRequirementsInput(BaseModel):
    sku_code: str = Field(..., description="Código del producto terminado a producir")
    units_to_produce: int = Field(..., gt=0, description="Cantidad de unidades a producir")


class GetReactorScheduleInput(BaseModel):
    litros_total: float = Field(..., gt=0, description="Total de litros a producir")
    tipo_reactor: str = Field(
        default="ambos",
        description="Tipo de reactor: 'pequeno' (200 L), 'grande' (5000 L) o 'ambos'",
    )


class GetCoverageAlertInput(BaseModel):
    umbral_critico: int = Field(
        default=7, ge=1,
        description="Días bajo los cuales se considera crítico (default 7)",
    )
    umbral_alerta: int = Field(
        default=15, ge=1,
        description="Días bajo los cuales se genera alerta (default 15)",
    )


class GetComponentStockInput(BaseModel):
    tipo: str = Field(
        default="todos",
        description=(
            "Filtro: 'todos', 'quimico', 'envase', 'etiqueta', "
            "'fragancia', 'granel', 'criticos'"
        ),
    )


class GetProductionHistoryInput(BaseModel):
    semanas: int = Field(
        default=4, ge=1, le=26,
        description="Semanas hacia atrás a revisar (default 4)",
    )
    sku_code: str | None = Field(
        default=None,
        description="Filtrar por producto específico",
    )


# ── Implementaciones ──────────────────────────────────────────────────────────

async def get_production_forecast(
    tenant_id: int,
    *,
    semanas: int = 2,
    solo_criticos: bool = False,
    familia: str | None = None,
    db: Any = None,
) -> dict[str, Any]:
    critico_filter = "AND ppw.is_critical = 1" if solo_criticos else ""
    familia_filter = "AND cat.category_name = ?" if familia else ""
    params: list[Any] = [tenant_id, semanas * 50]
    if familia:
        params.append(familia)

    sql = f"""
        SELECT TOP (?)
            sk.sku_code,
            sk.sku_name,
            sk.liters_per_unit,
            cat.category_name,
            ppw.iso_year_week,
            ppw.predicted_units_week,
            ppw.predicted_units_30d,
            ppw.stock_current,
            ppw.stock_final,
            ppw.units_to_produce,
            ppw.liters_to_produce,
            ppw.days_of_coverage,
            ppw.is_critical,
            ppw.has_component_shortage,
            ppw.blocking_components
        FROM gold.fact_production_plan_weekly ppw
        JOIN gold.dim_sku sk
            ON  sk.tenant_id   = ppw.tenant_id
            AND sk.sku_code    = ppw.sku_code
            AND sk.family_code = '1.1'
            AND sk.is_finished = 1
        LEFT JOIN gold.dim_category cat
            ON  cat.tenant_id = ppw.tenant_id
            AND cat.id        = sk.category_id
        WHERE ppw.tenant_id   = ?
          AND ppw.iso_year_week >= (
              SELECT iso_year_week FROM gold.dim_date
              WHERE date = CAST(GETDATE() AS DATE)
          )
          {critico_filter}
          {familia_filter}
        ORDER BY ppw.is_critical DESC,
                 ppw.days_of_coverage ASC,
                 ppw.iso_year_week,
                 ppw.units_to_produce DESC;
    """
    # params: TOP n, tenant_id[, familia]
    ordered_params = tuple([params[1], params[0]] + params[2:])
    rows = await execute_query(sql, ordered_params)
    return {"plan": rows}


async def get_component_requirements(
    tenant_id: int,
    *,
    sku_code: str,
    units_to_produce: int,
    db: Any = None,
) -> dict[str, Any]:
    # Nivel 2: envases + granel por unidad de producto
    sql_n2 = """
        SELECT
            rp.component_sku,
            rp.component_name,
            rp.component_type,
            rp.qty_per_unit * ?              AS qty_needed,
            rp.unit_of_measure,
            ISNULL(cs.stock_units, 0)        AS stock_available,
            ISNULL(cs.units_on_order, 0)     AS on_order,
            ISNULL(cs.stock_effective, 0)    AS stock_effective,
            CASE WHEN rp.qty_per_unit * ? > ISNULL(cs.stock_effective, 0)
                 THEN rp.qty_per_unit * ? - ISNULL(cs.stock_effective, 0)
                 ELSE 0 END                  AS qty_missing,
            rp.granel_sku,
            rp.liters_per_unit * ?           AS liters_needed
        FROM gold.dim_recipe_product rp
        LEFT JOIN gold.fact_component_stock cs
            ON  cs.tenant_id     = ?
            AND cs.component_sku = rp.component_sku
            AND cs.snapshot_date = CAST(GETDATE() AS DATE)
        WHERE rp.tenant_id   = ?
          AND rp.product_sku = ?
          AND rp.is_active   = 1
        ORDER BY rp.component_type, rp.component_sku;
    """
    n2_rows = await execute_query(
        sql_n2,
        (units_to_produce, units_to_produce, units_to_produce,
         units_to_produce, tenant_id, tenant_id, sku_code),
    )

    # Nivel 1: MP necesaria para el granel (calculada desde liters_needed del nivel 2)
    sql_n1 = """
        SELECT
            rg.component_sku,
            rg.component_name,
            rg.component_type,
            rg.unit_of_measure,
            rg.qty_per_liter * rp_agg.liters_needed AS qty_needed,
            ISNULL(cs.stock_units, 0)                AS stock_available,
            ISNULL(cs.stock_effective, 0)            AS stock_effective,
            CASE WHEN rg.qty_per_liter * rp_agg.liters_needed
                      > ISNULL(cs.stock_effective, 0)
                 THEN rg.qty_per_liter * rp_agg.liters_needed
                      - ISNULL(cs.stock_effective, 0)
                 ELSE 0 END                          AS qty_missing
        FROM gold.dim_recipe_granel rg
        JOIN (
            SELECT granel_sku,
                   SUM(liters_per_unit) * ? AS liters_needed
            FROM gold.dim_recipe_product
            WHERE tenant_id   = ?
              AND product_sku = ?
              AND is_active   = 1
            GROUP BY granel_sku
        ) rp_agg ON rp_agg.granel_sku = rg.granel_sku
        LEFT JOIN gold.fact_component_stock cs
            ON  cs.tenant_id     = ?
            AND cs.component_sku = rg.component_sku
            AND cs.snapshot_date = CAST(GETDATE() AS DATE)
        WHERE rg.tenant_id = ?
          AND rg.is_active  = 1
        ORDER BY rg.component_type, rg.component_sku;
    """
    n1_rows = await execute_query(
        sql_n1,
        (units_to_produce, tenant_id, sku_code, tenant_id, tenant_id),
    )

    missing_n2 = [r for r in n2_rows if (r.get("qty_missing") or 0) > 0]
    missing_n1 = [r for r in n1_rows if (r.get("qty_missing") or 0) > 0]
    can_produce = not missing_n2 and not missing_n1

    return {
        "sku_code": sku_code,
        "units_to_produce": units_to_produce,
        "can_produce": can_produce,
        "envases_y_granel": n2_rows,
        "quimico": n1_rows,
        "faltantes_envases": missing_n2,
        "faltantes_mp": missing_n1,
    }


async def get_reactor_schedule(
    tenant_id: int,
    *,
    litros_total: float,
    tipo_reactor: str = "ambos",
    db: Any = None,
) -> dict[str, Any]:
    # Tipos válidos (enum-validated by Pydantic antes de llegar aquí)
    VALID_TYPES = {"pequeno", "grande", "ambos"}
    if tipo_reactor not in VALID_TYPES:
        tipo_reactor = "ambos"

    type_filter = "" if tipo_reactor == "ambos" else "AND reactor_type = ?"
    params: tuple[Any, ...] = (tenant_id,)
    if tipo_reactor != "ambos":
        params = (tenant_id, tipo_reactor)

    sql = f"""
        SELECT reactor_code, reactor_name, capacity_liters, reactor_type
        FROM gold.dim_reactor
        WHERE tenant_id = ?
          AND is_active  = 1
          {type_filter}
        ORDER BY capacity_liters DESC;
    """
    reactors = await execute_query(sql, params)

    if not reactors:
        return {"error": "No hay reactores activos configurados para este tenant."}

    # Algoritmo greedy: llena con reactores grandes primero, luego pequeños
    grandes = [r for r in reactors if r["reactor_type"] == "grande"]
    pequenos = [r for r in reactors if r["reactor_type"] == "pequeno"]

    schedule: list[dict[str, Any]] = []
    restante = litros_total

    def _assign(reactor_list: list[dict], litros_restantes: float) -> float:
        for reactor in reactor_list:
            cap = float(reactor["capacity_liters"])
            if litros_restantes <= 0:
                break
            if litros_restantes >= cap:
                lotes = math.floor(litros_restantes / cap)
                for i in range(lotes):
                    schedule.append({
                        "reactor_code":    reactor["reactor_code"],
                        "reactor_name":    reactor["reactor_name"],
                        "capacity_liters": cap,
                        "lote":            i + 1,
                        "litros_asignados": cap,
                        "porcentaje_uso":  100,
                        "completo":        True,
                    })
                litros_restantes -= lotes * cap
            # Lote parcial (último lote)
            if litros_restantes > 0 and litros_restantes < cap:
                schedule.append({
                    "reactor_code":    reactor["reactor_code"],
                    "reactor_name":    reactor["reactor_name"],
                    "capacity_liters": cap,
                    "lote":            1,
                    "litros_asignados": round(litros_restantes, 2),
                    "porcentaje_uso":  round(litros_restantes / cap * 100, 1),
                    "completo":        False,
                })
                litros_restantes = 0
        return litros_restantes

    if tipo_reactor in ("ambos", "grande"):
        restante = _assign(grandes, restante)
    if tipo_reactor in ("ambos", "pequeno"):
        restante = _assign(pequenos, restante)

    total_lotes = len(schedule)
    lotes_completos = sum(1 for s in schedule if s["completo"])

    return {
        "litros_total": litros_total,
        "total_lotes": total_lotes,
        "lotes_completos": lotes_completos,
        "lotes_parciales": total_lotes - lotes_completos,
        "litros_sin_asignar": round(restante, 2),
        "schedule": schedule,
    }


async def get_coverage_alert(
    tenant_id: int,
    *,
    umbral_critico: int = 7,
    umbral_alerta: int = 15,
    db: Any = None,
) -> dict[str, Any]:
    sql = """
        SELECT
            ppw.sku_code,
            sk.sku_name,
            cat.category_name,
            ppw.iso_year_week,
            ppw.predicted_units_week,
            ppw.stock_current,
            ppw.units_to_produce,
            ppw.liters_to_produce,
            ppw.days_of_coverage,
            ppw.is_critical,
            ppw.has_component_shortage,
            ppw.blocking_components
        FROM gold.fact_production_plan_weekly ppw
        JOIN gold.dim_sku sk
            ON  sk.tenant_id   = ppw.tenant_id
            AND sk.sku_code    = ppw.sku_code
            AND sk.family_code = '1.1'
            AND sk.is_finished = 1
        LEFT JOIN gold.dim_category cat
            ON  cat.tenant_id = ppw.tenant_id
            AND cat.id        = sk.category_id
        WHERE ppw.tenant_id    = ?
          AND ppw.iso_year_week = (
              SELECT iso_year_week FROM gold.dim_date
              WHERE date = CAST(GETDATE() AS DATE)
          )
        ORDER BY ppw.days_of_coverage ASC,
                 ppw.units_to_produce DESC;
    """
    rows = await execute_query(sql, (tenant_id,))

    criticos, alertas, normales = [], [], []
    for r in rows:
        cov = r.get("days_of_coverage")
        if cov is None or cov < umbral_critico:
            criticos.append(r)
        elif cov < umbral_alerta:
            alertas.append(r)
        else:
            normales.append(r)

    return {
        "umbral_critico_dias": umbral_critico,
        "umbral_alerta_dias": umbral_alerta,
        "critico": criticos,
        "alerta": alertas,
        "normal": normales,
        "resumen": {
            "total_skus": len(rows),
            "criticos": len(criticos),
            "alertas": len(alertas),
            "con_componentes_bloqueantes": sum(
                1 for r in rows if r.get("has_component_shortage")
            ),
        },
    }


async def get_component_stock(
    tenant_id: int,
    *,
    tipo: str = "todos",
    db: Any = None,
) -> dict[str, Any]:
    TIPO_MAP = {
        "quimico":        ("quimico",),
        "envase":        ("envase",),
        "etiqueta":      ("etiqueta",),
        "fragancia":     ("fragancia",),
        "granel":        ("granel",),
        "criticos":      None,  # se filtra por is_critical
        "todos":         None,
    }
    tipo_norm = tipo if tipo in TIPO_MAP else "todos"

    if tipo_norm == "criticos":
        where_extra = "AND cs.is_critical = 1"
        extra_params: tuple[Any, ...] = ()
    elif TIPO_MAP.get(tipo_norm) is not None:
        tipos = TIPO_MAP[tipo_norm]
        placeholders = ",".join(["?" for _ in tipos])
        where_extra = f"AND cs.component_type IN ({placeholders})"
        extra_params = tuple(tipos)
    else:
        where_extra = ""
        extra_params = ()

    sql = f"""
        SELECT
            cs.component_sku,
            cs.component_name,
            cs.component_type,
            cs.stock_units,
            cs.units_on_order,
            cs.stock_effective,
            cs.unit_of_measure,
            cs.is_critical,
            cs.is_low,
            cs.stock_min,
            cs.snapshot_date,
            po.proximas_llegadas
        FROM gold.fact_component_stock cs
        OUTER APPLY (
            SELECT STRING_AGG(
                CONVERT(NVARCHAR(10), po2.order_date) + ': ' +
                CAST(po2.units_pending AS NVARCHAR(20)) + ' u',
                ' | '
            ) AS proximas_llegadas
            FROM gold.fact_purchase_orders po2
            WHERE po2.tenant_id     = cs.tenant_id
              AND po2.component_sku = cs.component_sku
              AND po2.status        = 'Pendiente'
        ) po
        WHERE cs.tenant_id     = ?
          AND cs.snapshot_date = CAST(GETDATE() AS DATE)
          {where_extra}
        ORDER BY cs.is_critical DESC,
                 cs.is_low     DESC,
                 cs.component_type,
                 cs.component_sku;
    """
    params = (tenant_id,) + extra_params
    rows = await execute_query(sql, params)

    return {
        "tipo_filtro": tipo_norm,
        "total": len(rows),
        "criticos": sum(1 for r in rows if r.get("is_critical")),
        "bajos":    sum(1 for r in rows if r.get("is_low")),
        "componentes": rows,
    }


async def get_production_history(
    tenant_id: int,
    *,
    semanas: int = 4,
    sku_code: str | None = None,
    db: Any = None,
) -> dict[str, Any]:
    sku_filter = "AND po.sku_code = ?" if sku_code else ""
    sku_params = (sku_code,) if sku_code else ()

    sql_prod = f"""
        SELECT
            po.iso_year_week,
            po.sku_code,
            sk.sku_name,
            SUM(po.units_produced)   AS units_produced,
            SUM(po.liters_produced)  AS liters_produced,
            COUNT(*)                 AS lotes,
            MAX(po.operator)         AS operador
        FROM gold.fact_production_orders po
        JOIN gold.dim_sku sk
            ON  sk.tenant_id   = po.tenant_id
            AND sk.sku_code    = po.sku_code
            AND sk.family_code = '1.1'
        WHERE po.tenant_id       = ?
          AND po.production_date >= DATEADD(WEEK, -?, CAST(GETDATE() AS DATE))
          {sku_filter}
        GROUP BY po.iso_year_week, po.sku_code, sk.sku_name
        ORDER BY po.iso_year_week DESC, po.sku_code;
    """
    prod_rows = await execute_query(
        sql_prod, (tenant_id, semanas) + sku_params
    )

    # Predicciones del mismo período para comparar
    sql_fc = f"""
        SELECT
            iso_year_week,
            sku_code,
            SUM(predicted_units) AS predicted_units
        FROM gold.fact_demand_forecast
        WHERE tenant_id    = ?
          AND is_active     = 1
          AND forecast_date >= DATEADD(WEEK, -?, CAST(GETDATE() AS DATE))
          AND forecast_date <  CAST(GETDATE() AS DATE)
          {sku_filter}
        GROUP BY iso_year_week, sku_code
        ORDER BY iso_year_week DESC, sku_code;
    """
    fc_rows = await execute_query(
        sql_fc, (tenant_id, semanas) + sku_params
    )

    # Órdenes de compra del período
    sql_oc = """
        SELECT
            component_sku,
            component_name,
            SUM(units_ordered)  AS units_ordered,
            SUM(units_pending)  AS units_pending,
            COUNT(*)            AS nro_ordenes,
            SUM(total_cost)     AS total_cost
        FROM gold.fact_purchase_orders
        WHERE tenant_id   = ?
          AND order_date  >= DATEADD(WEEK, -?, CAST(GETDATE() AS DATE))
        GROUP BY component_sku, component_name
        ORDER BY total_cost DESC;
    """
    oc_rows = await execute_query(sql_oc, (tenant_id, semanas))

    # Comparación real vs. predicho
    fc_map = {(r["iso_year_week"], r["sku_code"]): r["predicted_units"] for r in fc_rows}
    for r in prod_rows:
        pred = fc_map.get((r["iso_year_week"], r["sku_code"]), None)
        r["predicted_units"] = pred
        if pred and pred > 0:
            r["accuracy_pct"] = round(
                100 - abs(r["units_produced"] - pred) / pred * 100, 1
            )
        else:
            r["accuracy_pct"] = None

    return {
        "semanas": semanas,
        "produccion": prod_rows,
        "ordenes_compra": oc_rows,
        "resumen": {
            "total_lotes": sum(r.get("lotes", 0) for r in prod_rows),
            "total_unidades": sum(r.get("units_produced") or 0 for r in prod_rows),
            "total_litros":   sum(r.get("liters_produced") or 0 for r in prod_rows),
        },
    }
