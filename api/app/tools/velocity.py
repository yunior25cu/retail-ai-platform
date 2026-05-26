"""Tool: get_velocity_segmentation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.db.queries import fetch_velocity_segmentation

TOOL_NAME = "get_velocity_segmentation"
TOOL_DESCRIPTION = (
    "ABCD segmentation of active SKUs by units sold over the last 8 weeks: "
    "A = top 25% movers, B = next 25%, C = next 25%, D = slowest 25% (zeros). "
    "Filterable by segment letter and/or brand. Use to answer 'which are my "
    "fast / slow movers'."
)


class GetVelocitySegmentationInput(BaseModel):
    segment: str | None = Field(
        default=None,
        description="Optional segment letter filter: A / B / C / D.",
        pattern=r"^[ABCD]$",
    )
    brand_id: int | None = Field(default=None, description="Optional brand filter.")
    limit: int = Field(default=100, ge=1, le=500)


class VelocityItem(BaseModel):
    sku_id: int
    sku_code: str
    sku_name: str
    brand_id: int
    brand_name: str
    category_id: int | None
    units_8w: float
    revenue_8w: float
    weeks_with_sales: int
    units_per_day_avg: float
    velocity_segment: str


async def get_velocity_segmentation(
    tenant_id: int,
    *,
    segment: str | None = None,
    brand_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = await fetch_velocity_segmentation(
        tenant_id, segment=segment, brand_id=brand_id, limit=limit
    )
    return [VelocityItem.model_validate(r).model_dump(mode="json") for r in rows]
