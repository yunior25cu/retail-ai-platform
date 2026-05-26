"""Unit tests for get_velocity_segmentation (tenant 7)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.tools.velocity import (
    GetVelocitySegmentationInput,
    VelocityItem,
    get_velocity_segmentation,
)


@pytest.mark.asyncio
async def test_get_velocity_segmentation_returns_all_segments_for_tenant_7() -> None:
    rows = await get_velocity_segmentation(tenant_id=7, limit=200)
    assert len(rows) > 0
    for r in rows:
        VelocityItem.model_validate(r)
    segments = {r["velocity_segment"] for r in rows}
    # Phase 3 validation showed 16 / 16 / 16 / 15 across A/B/C/D
    assert segments.issubset({"A", "B", "C", "D"})


@pytest.mark.asyncio
async def test_get_velocity_segmentation_filter_by_segment() -> None:
    rows = await get_velocity_segmentation(tenant_id=7, segment="A", limit=50)
    assert all(r["velocity_segment"] == "A" for r in rows)


@pytest.mark.asyncio
async def test_get_velocity_segmentation_unknown_tenant_returns_empty() -> None:
    assert await get_velocity_segmentation(tenant_id=99) == []


def test_input_model_rejects_invalid_segment_letter() -> None:
    with pytest.raises(ValidationError):
        GetVelocitySegmentationInput(segment="Z")
