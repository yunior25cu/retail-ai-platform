"""Tool dispatcher.

Single entry point that the orchestrator uses to execute a tool call from the
LLM. Encapsulates:

    - Tool name validation (against ``TOOL_REGISTRY``)
    - Pydantic validation of tool input
    - Tenant-id injection from the auth context (NEVER from the LLM input)
    - Error normalisation into a JSON-serialisable dict suitable to be sent
      back to Claude as a ``tool_result``.

Returns the tuple ``(payload, is_error, duration_ms)``. The orchestrator then
wraps ``payload`` in a tool_result block.
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from pydantic import ValidationError

from app.tools import TOOL_REGISTRY

log = structlog.get_logger(__name__)


async def dispatch_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    tenant_id: int,
) -> tuple[Any, bool, int]:
    """Execute a tool. Returns (payload, is_error, duration_ms).

    SECURITY INVARIANT: tenant_id arrives from the trusted auth context. The
    LLM's ``tool_input`` is parsed by the tool's Pydantic model which does NOT
    declare ``tenant_id``; any 'tenant_id' Claude tries to inject is silently
    dropped during validation.
    """
    t0 = time.perf_counter()

    entry = TOOL_REGISTRY.get(tool_name)
    if entry is None:
        log.warning("dispatch.unknown_tool", tool=tool_name, tenant=tenant_id)
        return ({"error": "unknown_tool", "tool": tool_name}, True, _elapsed_ms(t0))

    try:
        validated = entry["input_model"](**(tool_input or {})).model_dump()
    except ValidationError as e:
        log.warning(
            "dispatch.invalid_input",
            tool=tool_name,
            tenant=tenant_id,
            errors=e.errors(),
        )
        return ({"error": "invalid_input", "details": e.errors()}, True, _elapsed_ms(t0))

    try:
        result = await entry["fn"](tenant_id=tenant_id, **validated)
        log.info(
            "dispatch.success",
            tool=tool_name,
            tenant=tenant_id,
            rows=_row_count(result),
            ms=_elapsed_ms(t0),
        )
        return (result, False, _elapsed_ms(t0))
    except Exception as e:  # noqa: BLE001
        log.exception("dispatch.failed", tool=tool_name, tenant=tenant_id)
        return (
            {"error": "tool_execution_failed", "message": str(e)},
            True,
            _elapsed_ms(t0),
        )


def _elapsed_ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _row_count(result: Any) -> int | None:
    return len(result) if isinstance(result, list) else None
