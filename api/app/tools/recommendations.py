"""Tool: get_action_recommendations."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.queries import fetch_action_recommendations
from app.tools.schemas import AlertLevel, AlertSeverity

TOOL_NAME = "get_action_recommendations"
TOOL_DESCRIPTION = (
    "Top-N recommended actions for the tenant, ranked by priority (severity x "
    "estimated dollar impact). Filterable by scope (alert level) and severity. "
    "Use when the user asks 'what should I do today' or for a prioritised work list."
)


class GetActionRecommendationsInput(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    scope: AlertLevel | None = Field(
        default=None,
        description="Optional filter by alert level: SKU / STORE / BRAND / EXECUTIVE.",
    )
    severity: AlertSeverity | None = Field(
        default=None,
        description="Optional severity filter: HIGH / MEDIUM / LOW.",
    )
    limit: int = Field(default=10, ge=1, le=100)


class RecommendationItem(BaseModel):
    priority_rank: int
    alert_id: str
    iso_year_week: str
    level: str
    alert_type: str
    severity: str
    store_id: int | None
    sku_id: int | None
    brand_id: int | None
    sku_code: str | None = None
    sku_name: str | None = None
    brand_name: str | None = None
    store_name: str | None = None
    metric_value: float | None
    threshold: float | None
    suggested_action: str | None
    estimated_impact_usd: float | None
    priority_score: float | None


async def get_action_recommendations(
    tenant_id: int,
    *,
    scope: str | None = None,
    severity: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    rows = await fetch_action_recommendations(
        tenant_id, scope=scope, severity=severity, limit=limit
    )
    return [RecommendationItem.model_validate(r).model_dump(mode="json") for r in rows]
