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

from app.db.connection import execute_query  # retail tools — do not change
from app.db.connections import (
    execute_query_tenant,
    get_schema,
    is_postgres,
    current_date_expr,
    current_iso_week_expr,
    weeks_ago_expr,
)

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
    schema = get_schema(tenant_id)
    pg = is_postgres(tenant_id)
    # Max 15 rows by default; 30 hard cap regardless of semanas
    limit = min(semanas * 15, 30)
    top_clause   = "" if pg else f"TOP {limit}"
    limit_clause = f"LIMIT {limit}" if pg else ""
    iso_week = current_iso_week_expr(tenant_id)

    _one = "TRUE" if pg else "1"
    critico_filter = f"AND ppw.is_critical = {_one}" if solo_criticos else ""
    params_list: list[Any] = [tenant_id]

    # 10 columns only — category_name, liters_per_unit, iso_year_week,
    # predicted_units_30d and stock_final removed to cut token usage
    sql = f"""
        SELECT {top_clause}
            sk.sku_code,
            sk.sku_name,
            ppw.predicted_units_week,
            ppw.stock_current,
            ppw.units_to_produce,
            ppw.liters_to_produce,
            ppw.days_of_coverage,
            ppw.is_critical,
            ppw.has_component_shortage,
            ppw.blocking_components
        FROM {schema}.fact_production_plan_weekly ppw
        JOIN {schema}.dim_sku sk
            ON  sk.tenant_id   = ppw.tenant_id
            AND sk.sku_code    = ppw.sku_code
            AND sk.family_code = '1.1'
            AND sk.is_finished = {_one}
        WHERE ppw.tenant_id   = ?
          AND ppw.iso_year_week >= {iso_week}
          {critico_filter}
        ORDER BY ppw.is_critical DESC,
                 ppw.days_of_coverage ASC {'NULLS LAST' if pg else ''},
                 ppw.units_to_produce DESC
        {limit_clause};
    """
    rows = await execute_query_tenant(sql, tuple(params_list), tenant_id=tenant_id)
    return {"plan": rows}


async def get_component_requirements(
    tenant_id: int,
    *,
    sku_code: str,
    units_to_produce: int,
    db: Any = None,
) -> dict[str, Any]:
    schema = get_schema(tenant_id)
    today = current_date_expr(tenant_id)

    sql_n2 = f"""
        SELECT
            rp.component_sku,
            rp.component_name,
            rp.component_type,
            rp.qty_per_unit * ?                  AS qty_needed,
            rp.unit_of_measure,
            COALESCE(cs.stock_units, 0)           AS stock_available,
            COALESCE(cs.units_on_order, 0)        AS on_order,
            COALESCE(cs.stock_effective, 0)       AS stock_effective,
            CASE WHEN rp.qty_per_unit * ? > COALESCE(cs.stock_effective, 0)
                 THEN rp.qty_per_unit * ? - COALESCE(cs.stock_effective, 0)
                 ELSE 0 END                       AS qty_missing,
            rp.granel_sku,
            rp.liters_per_unit * ?               AS liters_needed
        FROM {schema}.dim_recipe_product rp
        LEFT JOIN {schema}.fact_component_stock cs
            ON  cs.tenant_id     = ?
            AND cs.component_sku = rp.component_sku
            AND cs.snapshot_date = {today}
        WHERE rp.tenant_id   = ?
          AND rp.product_sku = ?
          AND rp.is_active   = 1
        ORDER BY qty_missing DESC, rp.component_type, rp.component_sku
        {'LIMIT 30' if pg else ''};
    """
    n2_rows = await execute_query_tenant(
        sql_n2,
        (units_to_produce, units_to_produce, units_to_produce,
         units_to_produce, tenant_id, tenant_id, sku_code),
        tenant_id=tenant_id,
    )

    sql_n1 = f"""
        SELECT
            rg.component_sku,
            rg.component_name,
            rg.component_type,
            rg.unit_of_measure,
            rg.qty_per_liter * rp_agg.liters_needed  AS qty_needed,
            COALESCE(cs.stock_units, 0)               AS stock_available,
            COALESCE(cs.stock_effective, 0)           AS stock_effective,
            CASE WHEN rg.qty_per_liter * rp_agg.liters_needed
                      > COALESCE(cs.stock_effective, 0)
                 THEN rg.qty_per_liter * rp_agg.liters_needed
                      - COALESCE(cs.stock_effective, 0)
                 ELSE 0 END                           AS qty_missing
        FROM {schema}.dim_recipe_granel rg
        JOIN (
            SELECT granel_sku,
                   SUM(liters_per_unit) * ? AS liters_needed
            FROM {schema}.dim_recipe_product
            WHERE tenant_id   = ?
              AND product_sku = ?
              AND is_active   = 1
            GROUP BY granel_sku
        ) rp_agg ON rp_agg.granel_sku = rg.granel_sku
        LEFT JOIN {schema}.fact_component_stock cs
            ON  cs.tenant_id     = ?
            AND cs.component_sku = rg.component_sku
            AND cs.snapshot_date = {today}
        WHERE rg.tenant_id = ?
          AND rg.is_active  = 1
        ORDER BY qty_missing DESC, rg.component_type, rg.component_sku
        {'LIMIT 30' if pg else ''};
    """
    n1_rows = await execute_query_tenant(
        sql_n1,
        (units_to_produce, tenant_id, sku_code, tenant_id, tenant_id),
        tenant_id=tenant_id,
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

    schema = get_schema(tenant_id)
    sql = f"""
        SELECT reactor_code, reactor_name, capacity_liters, reactor_type
        FROM {schema}.dim_reactor
        WHERE tenant_id = ?
          AND is_active  = 1
          {type_filter}
        ORDER BY capacity_liters DESC;
    """
    reactors = await execute_query_tenant(sql, params, tenant_id=tenant_id)

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
    schema = get_schema(tenant_id)
    pg = is_postgres(tenant_id)
    iso_week = current_iso_week_expr(tenant_id)
    _one = "TRUE" if pg else "1"
    limit_clause = "LIMIT 10" if pg else ""
    top_clause   = "" if pg else "TOP 10"
    nulls_last   = "NULLS LAST" if pg else ""

    # 6 columns, LIMIT 10 always — enough for actionable decisions
    sql = f"""
        SELECT {top_clause}
            ppw.sku_code,
            sk.sku_name,
            ppw.days_of_coverage,
            ppw.is_critical,
            ppw.has_component_shortage,
            ppw.blocking_components
        FROM {schema}.fact_production_plan_weekly ppw
        JOIN {schema}.dim_sku sk
            ON  sk.tenant_id   = ppw.tenant_id
            AND sk.sku_code    = ppw.sku_code
            AND sk.family_code = '1.1'
            AND sk.is_finished = {_one}
        WHERE ppw.tenant_id    = ?
          AND ppw.iso_year_week = (
              SELECT MIN(p2.iso_year_week)
              FROM {schema}.fact_production_plan_weekly p2
              WHERE p2.tenant_id    = ?
                AND p2.iso_year_week >= {iso_week}
          )
        ORDER BY ppw.is_critical DESC,
                 ppw.days_of_coverage ASC {nulls_last}
        {limit_clause};
    """
    rows = await execute_query_tenant(sql, (tenant_id, tenant_id), tenant_id=tenant_id)

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

    schema = get_schema(tenant_id)
    pg = is_postgres(tenant_id)
    today = current_date_expr(tenant_id)
    _one = "TRUE" if pg else "1"
    top_clause   = "" if pg else "TOP 20"
    limit_clause = "LIMIT 20" if pg else ""
    nulls_last   = "NULLS LAST" if pg else ""

    if tipo_norm == "criticos":
        where_extra = f"AND cs.is_critical = {_one}"
        extra_params: tuple[Any, ...] = ()
    elif TIPO_MAP.get(tipo_norm) is not None:
        tipos = TIPO_MAP[tipo_norm]
        placeholders = ",".join(["?" for _ in tipos])
        # For specific types, show critical/low first; still max 20
        where_extra = f"AND cs.component_type IN ({placeholders})"
        extra_params = tuple(tipos)
    else:
        # 'todos' default: only show problem components (critical or below min)
        where_extra = f"AND (cs.is_critical = {_one} OR cs.is_low = {_one})"
        extra_params = ()

    # No LATERAL/OUTER APPLY — removed purchase order subquery to cut tokens.
    # The is_low / is_critical flags already reflect OC-adjusted stock_effective.
    sql = f"""
        SELECT {top_clause}
            cs.component_sku,
            cs.component_name,
            cs.component_type,
            cs.stock_units,
            cs.stock_effective,
            cs.unit_of_measure,
            cs.is_critical,
            cs.is_low,
            cs.stock_min
        FROM {schema}.fact_component_stock cs
        WHERE cs.tenant_id     = ?
          AND cs.snapshot_date = {today}
          {where_extra}
        ORDER BY cs.is_critical DESC,
                 cs.is_low     DESC {nulls_last}
        {limit_clause};
    """
    params = (tenant_id,) + extra_params
    rows = await execute_query_tenant(sql, params, tenant_id=tenant_id)

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
    schema = get_schema(tenant_id)
    pg = is_postgres(tenant_id)
    today = current_date_expr(tenant_id)
    weeks_expr = weeks_ago_expr(tenant_id)
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
        FROM {schema}.fact_production_orders po
        JOIN {schema}.dim_sku sk
            ON  sk.tenant_id   = po.tenant_id
            AND sk.sku_code    = po.sku_code
            AND sk.family_code = '1.1'
        WHERE po.tenant_id       = ?
          AND po.production_date >= {weeks_expr}
          {sku_filter}
        GROUP BY po.iso_year_week, po.sku_code, sk.sku_name
        ORDER BY SUM(po.units_produced) DESC, po.iso_year_week DESC
        {'LIMIT 10' if pg else ''};
    """
    prod_rows = await execute_query_tenant(
        sql_prod, (tenant_id, semanas) + sku_params, tenant_id=tenant_id
    )

    sql_fc = f"""
        SELECT
            iso_year_week,
            sku_code,
            SUM(predicted_units) AS predicted_units
        FROM {schema}.fact_demand_forecast
        WHERE tenant_id    = ?
          AND is_active     = {'TRUE' if pg else '1'}
          AND forecast_date >= {weeks_expr}
          AND forecast_date <  {today}
          {sku_filter}
        GROUP BY iso_year_week, sku_code
        ORDER BY iso_year_week DESC, sku_code
        {'LIMIT 10' if pg else ''};
    """
    fc_rows = await execute_query_tenant(
        sql_fc, (tenant_id, semanas) + sku_params, tenant_id=tenant_id
    )

    sql_oc = f"""
        SELECT
            component_sku,
            component_name,
            SUM(units_ordered)  AS units_ordered,
            SUM(units_pending)  AS units_pending,
            COUNT(*)            AS nro_ordenes,
            SUM(total_cost)     AS total_cost
        FROM {schema}.fact_purchase_orders
        WHERE tenant_id   = ?
          AND order_date  >= {weeks_ago_expr(tenant_id)}
        GROUP BY component_sku, component_name
        ORDER BY total_cost DESC
        {'LIMIT 10' if pg else ''};
    """
    oc_rows = await execute_query_tenant(sql_oc, (tenant_id, semanas), tenant_id=tenant_id)

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
