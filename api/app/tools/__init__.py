"""Tool registry.

Each entry maps a public tool name to:
    - ``fn`` :         async callable executing the tool
    - ``input_model``: Pydantic v2 model for input validation
    - ``description``: human / LLM-facing description
    - ``anthropic``:   pre-built Anthropic tool definition
                       (``{"name", "description", "input_schema"}``)

The orchestrator (sub-phase 4.3) will iterate this dict to build the tool list
sent to Claude on each ``messages.create`` call.
"""

from __future__ import annotations

from typing import Any, Callable

from app.tools.alerts import (
    TOOL_DESCRIPTION as ALERTS_DESC,
)
from app.tools.alerts import (
    TOOL_NAME as ALERTS_NAME,
)
from app.tools.alerts import (
    GetActiveAlertsInput,
    get_active_alerts,
)
from app.tools.brand import (
    TOOL_DESCRIPTION as BRAND_DESC,
)
from app.tools.brand import (
    TOOL_NAME as BRAND_NAME,
)
from app.tools.brand import (
    GetBrandPerformanceInput,
    get_brand_performance,
)
from app.tools.schemas import pydantic_to_anthropic_tool
from app.tools.store import (
    TOOL_DESCRIPTION as STORE_DESC,
)
from app.tools.store import (
    TOOL_NAME as STORE_NAME,
)
from app.tools.store import (
    GetStoreDashboardInput,
    get_store_dashboard,
)


def _entry(
    name: str,
    description: str,
    fn: Callable[..., Any],
    input_model: type,
) -> dict[str, Any]:
    return {
        "fn": fn,
        "input_model": input_model,
        "description": description,
        "anthropic": pydantic_to_anthropic_tool(name, description, input_model),
    }


TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    ALERTS_NAME: _entry(ALERTS_NAME, ALERTS_DESC, get_active_alerts, GetActiveAlertsInput),
    STORE_NAME: _entry(STORE_NAME, STORE_DESC, get_store_dashboard, GetStoreDashboardInput),
    BRAND_NAME: _entry(BRAND_NAME, BRAND_DESC, get_brand_performance, GetBrandPerformanceInput),
}


def anthropic_tools() -> list[dict[str, Any]]:
    """Convenience: list of Anthropic tool definitions for ``client.messages.create``."""
    return [entry["anthropic"] for entry in TOOL_REGISTRY.values()]
