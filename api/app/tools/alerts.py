"""Tool: get_active_alerts.

Returns rows from ``gold.vw_active_alerts`` for the caller's tenant, optionally
filtered by level/severity, ordered by ``estimated_impact_usd`` DESC.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.queries import fetch_active_alerts
from app.tools.schemas import AlertLevel, AlertSeverity

TOOL_NAME = "get_active_alerts"
TOOL_DESCRIPTION = (
    "List currently active operational alerts (stockout / obsolete / overstock / understock) "
    "for the authenticated tenant. Each alert carries severity, suggested action and "
    "estimated dollar impact. Use this to surface what needs attention right now."
)


class GetActiveAlertsInput(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    level: AlertLevel | None = Field(
        default=None,
        description="Optional filter by alert level (SKU / STORE / BRAND / EXECUTIVE).",
    )
    severity: AlertSeverity | None = Field(
        default=None,
        description="Optional filter by severity (HIGH / MEDIUM / LOW).",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=200,
        description="Maximum number of alerts to return. Default 20, max 200.",
    )


class ActiveAlertItem(BaseModel):
    alert_id: str
    iso_year_week: str
    level: str
    alert_type: str
    severity: str
    store_id: int | None
    sku_id: int | None
    brand_id: int | None
    metric_value: float | None
    threshold: float | None
    suggested_action: str | None
    estimated_impact_usd: float | None


async def get_active_alerts(
    tenant_id: int,
    *,
    level: str | None = None,
    severity: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Execute the tool and return JSON-serialisable dict rows."""
    rows = await fetch_active_alerts(
        tenant_id, level=level, severity=severity, limit=limit
    )
    return [ActiveAlertItem.model_validate(r).model_dump(mode="json") for r in rows]
