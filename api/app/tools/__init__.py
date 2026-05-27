"""Tool registry.

Each entry maps a public tool name to:
    - ``fn`` :         async callable executing the tool
    - ``input_model``: Pydantic v2 model for input validation
    - ``description``: human / LLM-facing description
    - ``anthropic``:   pre-built Anthropic tool definition
                       (``{"name", "description", "input_schema"}``)
    - ``required_roles`` (optional): list of role names allowed to call this
      tool. Enforced by the dispatcher.

The orchestrator (sub-phase 4.3) iterates this dict to build the tool list
sent to Claude on each ``messages.create`` call.
"""

from __future__ import annotations

from typing import Any, Callable

from app.tools.alerts import (
    GetActiveAlertsInput,
    get_active_alerts,
)
from app.tools.alerts import TOOL_DESCRIPTION as ALERTS_DESC
from app.tools.alerts import TOOL_NAME as ALERTS_NAME
from app.tools.audit import (
    REQUIRED_ROLES as AUDIT_ROLES,
)
from app.tools.audit import (
    GetAuditTrailInput,
    get_audit_trail,
)
from app.tools.audit import TOOL_DESCRIPTION as AUDIT_DESC
from app.tools.audit import TOOL_NAME as AUDIT_NAME
from app.tools.brand import (
    GetBrandPerformanceInput,
    get_brand_performance,
)
from app.tools.brand import TOOL_DESCRIPTION as BRAND_DESC
from app.tools.brand import TOOL_NAME as BRAND_NAME
from app.tools.compare import (
    GetComparePeriodsInput,
    compare_periods,
)
from app.tools.compare import TOOL_DESCRIPTION as COMPARE_DESC
from app.tools.compare import TOOL_NAME as COMPARE_NAME
from app.tools.composite import (
    REQUIRED_ROLES as BRIEFING_ROLES,
)
from app.tools.composite import (
    GetMonthlyExecutiveBriefingInput,
    get_monthly_executive_briefing,
)
from app.tools.composite import TOOL_DESCRIPTION as BRIEFING_DESC
from app.tools.composite import TOOL_NAME as BRIEFING_NAME
from app.tools.monthly import (
    REQUIRED_ROLES as MONTHLY_ROLES,
)
from app.tools.monthly import (
    GetMonthlySummaryInput,
    get_monthly_summary,
)
from app.tools.monthly import TOOL_DESCRIPTION as MONTHLY_DESC
from app.tools.monthly import TOOL_NAME as MONTHLY_NAME
from app.tools.executive import (
    GetExecutiveSummaryInput,
    get_executive_summary,
)
from app.tools.executive import TOOL_DESCRIPTION as EXEC_DESC
from app.tools.executive import TOOL_NAME as EXEC_NAME
from app.tools.recommendations import (
    GetActionRecommendationsInput,
    get_action_recommendations,
)
from app.tools.recommendations import TOOL_DESCRIPTION as REC_DESC
from app.tools.recommendations import TOOL_NAME as REC_NAME
from app.tools.schemas import pydantic_to_anthropic_tool
from app.tools.sku import (
    GetSkuCoverageStatusInput,
    GetSkuDetailInput,
    get_sku_coverage_status,
    get_sku_detail,
)
from app.tools.sku import SKU_COVERAGE_DESCRIPTION, SKU_COVERAGE_NAME
from app.tools.sku import SKU_DETAIL_DESCRIPTION, SKU_DETAIL_NAME
from app.tools.store import (
    GetStoreDashboardInput,
    get_store_dashboard,
)
from app.tools.store import TOOL_DESCRIPTION as STORE_DESC
from app.tools.store import TOOL_NAME as STORE_NAME
from app.tools.velocity import (
    GetVelocitySegmentationInput,
    get_velocity_segmentation,
)
from app.tools.velocity import TOOL_DESCRIPTION as VEL_DESC
from app.tools.velocity import TOOL_NAME as VEL_NAME


def _entry(
    name: str,
    description: str,
    fn: Callable[..., Any],
    input_model: type,
    required_roles: list[str] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "fn": fn,
        "input_model": input_model,
        "description": description,
        "anthropic": pydantic_to_anthropic_tool(name, description, input_model),
    }
    if required_roles:
        entry["required_roles"] = required_roles
    return entry


TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    ALERTS_NAME:        _entry(ALERTS_NAME,        ALERTS_DESC,                get_active_alerts,           GetActiveAlertsInput),
    STORE_NAME:         _entry(STORE_NAME,         STORE_DESC,                 get_store_dashboard,         GetStoreDashboardInput),
    BRAND_NAME:         _entry(BRAND_NAME,         BRAND_DESC,                 get_brand_performance,       GetBrandPerformanceInput),
    EXEC_NAME:          _entry(EXEC_NAME,          EXEC_DESC,                  get_executive_summary,       GetExecutiveSummaryInput),
    SKU_DETAIL_NAME:    _entry(SKU_DETAIL_NAME,    SKU_DETAIL_DESCRIPTION,     get_sku_detail,              GetSkuDetailInput),
    SKU_COVERAGE_NAME:  _entry(SKU_COVERAGE_NAME,  SKU_COVERAGE_DESCRIPTION,   get_sku_coverage_status,     GetSkuCoverageStatusInput),
    VEL_NAME:           _entry(VEL_NAME,           VEL_DESC,                   get_velocity_segmentation,   GetVelocitySegmentationInput),
    REC_NAME:           _entry(REC_NAME,           REC_DESC,                   get_action_recommendations,  GetActionRecommendationsInput),
    COMPARE_NAME:       _entry(COMPARE_NAME,       COMPARE_DESC,               compare_periods,             GetComparePeriodsInput),
    AUDIT_NAME:         _entry(AUDIT_NAME,         AUDIT_DESC,                 get_audit_trail,             GetAuditTrailInput, required_roles=AUDIT_ROLES),
    MONTHLY_NAME:       _entry(MONTHLY_NAME,       MONTHLY_DESC,               get_monthly_summary,         GetMonthlySummaryInput, required_roles=MONTHLY_ROLES),
    BRIEFING_NAME:      _entry(BRIEFING_NAME,      BRIEFING_DESC,              get_monthly_executive_briefing, GetMonthlyExecutiveBriefingInput, required_roles=BRIEFING_ROLES),
}


def anthropic_tools(role: str | None = None) -> list[dict[str, Any]]:
    """List of Anthropic tool definitions, filtered by role when provided.

    If ``role`` is None all tools (including role-restricted) are returned —
    intended for testing / introspection only. The orchestrator passes the
    real role so the LLM never sees tools it cannot call.
    """
    out: list[dict[str, Any]] = []
    norm = (role or "").lower()
    for entry in TOOL_REGISTRY.values():
        required = entry.get("required_roles")
        if required and role is not None and norm not in {r.lower() for r in required}:
            continue
        out.append(entry["anthropic"])
    return out
