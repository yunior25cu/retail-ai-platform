"""20-question eval catalog covering all 4 roles and all major tool paths.

Each question defines:
  - expected_tools: at least one of these should appear in tools_invoked.
    A question may list multiple valid tool paths (the LLM chooses).
  - expected_concepts: Spanish keywords that should appear in the response.
    Used to compute concept_coverage without an LLM-as-judge.

Designed to run against tenant_id=9001 (synthetic dataset, Phase 5.5).
Can also run against tenant_id=7 (POC tenant) for smoke testing.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalQuestion:
    id: str
    role: str
    question: str
    expected_tools: list[str]
    expected_concepts: list[str]
    hint: str = ""


CATALOG: list[EvalQuestion] = [
    # ── DIRECCION (Q01–Q05) ──────────────────────────────────────────────────
    EvalQuestion(
        id="Q01",
        role="direccion",
        question="Dame el briefing ejecutivo de esta semana.",
        expected_tools=["get_executive_weekly_briefing", "get_executive_summary"],
        expected_concepts=["facturación", "margen", "semana"],
        hint="Should prefer the composite briefing tool.",
    ),
    EvalQuestion(
        id="Q02",
        role="direccion",
        question="¿Cuánto facturamos en abril comparado con marzo?",
        expected_tools=["compare_periods"],
        expected_concepts=["abril", "marzo", "facturación"],
        hint="Monthly period comparison.",
    ),
    EvalQuestion(
        id="Q03",
        role="direccion",
        question="¿Cuáles son las alertas de mayor impacto económico?",
        expected_tools=["get_active_alerts", "get_executive_weekly_briefing", "get_executive_summary"],
        expected_concepts=["alerta", "impacto"],
        hint="Alert ranking by dollar impact.",
    ),
    EvalQuestion(
        id="Q04",
        role="direccion",
        question="Dame el informe ejecutivo mensual del último mes.",
        expected_tools=["get_monthly_executive_briefing"],
        expected_concepts=["facturación", "margen", "mes"],
        hint="Monthly executive briefing.",
    ),
    EvalQuestion(
        id="Q05",
        role="direccion",
        question="¿Qué acciones tenemos pendientes con mayor impacto esta semana?",
        expected_tools=["get_action_recommendations", "get_executive_weekly_briefing"],
        expected_concepts=["acción", "impacto", "semana"],
        hint="Action recommendations by priority.",
    ),

    # ── MARCA (Q06–Q10) ──────────────────────────────────────────────────────
    EvalQuestion(
        id="Q06",
        role="marca",
        question="¿Cómo fue la semana para mi marca?",
        expected_tools=["get_brand_weekly_review", "get_brand_performance"],
        expected_concepts=["semana", "facturación", "marca"],
        hint="Brand weekly review — composite tool preferred.",
    ),
    EvalQuestion(
        id="Q07",
        role="marca",
        question="¿Qué SKUs de mi marca están en crítico o sin stock?",
        expected_tools=["get_sku_coverage_status", "get_brand_weekly_review"],
        expected_concepts=["stock", "cobertura"],
        hint="SKU coverage filtered to RED/YELLOW.",
    ),
    EvalQuestion(
        id="Q08",
        role="marca",
        question="¿Cómo están rotando los productos de mi marca?",
        expected_tools=["get_velocity_segmentation", "get_brand_weekly_review"],
        expected_concepts=["rotación", "segmento"],
        hint="ABCD velocity segmentation for the brand.",
    ),
    EvalQuestion(
        id="Q09",
        role="marca",
        question="Mostrá el rendimiento de mi marca en el mes pasado.",
        expected_tools=["get_monthly_summary", "get_brand_performance"],
        expected_concepts=["mes", "facturación"],
        hint="Monthly summary for the brand.",
    ),
    EvalQuestion(
        id="Q10",
        role="marca",
        question="¿Estoy por encima o por debajo del plan esta semana?",
        expected_tools=["get_brand_weekly_review", "get_brand_performance"],
        expected_concepts=["plan", "semana"],
        hint="Plan vs actual for the brand.",
    ),

    # ── TIENDA (Q11–Q15) ─────────────────────────────────────────────────────
    EvalQuestion(
        id="Q11",
        role="tienda",
        question="Dame el resumen de la tienda de esta semana.",
        expected_tools=["get_store_daily_briefing", "get_store_dashboard"],
        expected_concepts=["tienda", "semana", "ventas"],
        hint="Store briefing — composite tool preferred.",
    ),
    EvalQuestion(
        id="Q12",
        role="tienda",
        question="¿Qué productos tengo en crítico o sin stock en la tienda?",
        expected_tools=["get_sku_coverage_status", "get_store_daily_briefing"],
        expected_concepts=["stock", "cobertura"],
        hint="Critical SKUs for this store.",
    ),
    EvalQuestion(
        id="Q13",
        role="tienda",
        question="¿Qué tengo que hacer hoy en la tienda?",
        expected_tools=["get_action_recommendations", "get_store_daily_briefing"],
        expected_concepts=["acción"],
        hint="Prioritised action list for the store.",
    ),
    EvalQuestion(
        id="Q14",
        role="tienda",
        question="¿Cómo van las ventas de esta semana respecto a la semana pasada?",
        expected_tools=["compare_periods", "get_store_daily_briefing", "get_store_dashboard"],
        expected_concepts=["semana", "ventas"],
        hint="WoW sales comparison for the store.",
    ),
    EvalQuestion(
        id="Q15",
        role="tienda",
        question="¿Cuántas unidades vendí y cuántos tickets tuve esta semana?",
        expected_tools=["get_store_daily_briefing", "get_store_dashboard"],
        expected_concepts=["unidades", "tickets", "semana"],
        hint="Units and ticket count for the store.",
    ),

    # ── SKU (Q16–Q20) ────────────────────────────────────────────────────────
    EvalQuestion(
        id="Q16",
        role="sku",
        question="¿Cómo está el desempeño del SKU con mayor cobertura crítica?",
        expected_tools=["get_sku_coverage_status", "get_sku_detail"],
        expected_concepts=["cobertura", "días"],
        hint="SKU coverage status → drill into top critical SKU.",
    ),
    EvalQuestion(
        id="Q17",
        role="sku",
        question="¿Qué productos están sin stock en este momento?",
        expected_tools=["get_sku_coverage_status", "get_active_alerts"],
        expected_concepts=["stock", "stockout"],
        hint="Zero-stock SKUs (RED coverage).",
    ),
    EvalQuestion(
        id="Q18",
        role="sku",
        question="Dame los productos de mayor rotación (segmento A).",
        expected_tools=["get_velocity_segmentation"],
        expected_concepts=["segmento", "rotación"],
        hint="Fast-movers velocity segmentation.",
    ),
    EvalQuestion(
        id="Q19",
        role="sku",
        question="¿Qué acciones de reposición o liquidación tengo pendientes?",
        expected_tools=["get_action_recommendations", "get_sku_coverage_status"],
        expected_concepts=["reposición", "liquidación"],
        hint="Action recommendations focused on stock.",
    ),
    EvalQuestion(
        id="Q20",
        role="sku",
        question="¿Cuáles son los productos lentos (segmento C o D) con stock alto?",
        expected_tools=["get_velocity_segmentation", "get_sku_coverage_status"],
        expected_concepts=["lento", "segmento", "stock"],
        hint="Slow-movers with excess stock — liquidation candidates.",
    ),
]

# Sanity-check at import time: IDs must be unique.
_ids = [q.id for q in CATALOG]
assert len(_ids) == len(set(_ids)), "Duplicate question IDs in CATALOG"
assert len(CATALOG) == 20, f"Catalog must have 20 questions, found {len(CATALOG)}"
