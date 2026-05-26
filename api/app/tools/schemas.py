"""Shared enums and helpers for tool schemas."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class AlertLevel(StrEnum):
    SKU = "SKU"
    STORE = "STORE"
    BRAND = "BRAND"
    EXECUTIVE = "EXECUTIVE"


class AlertSeverity(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


def pydantic_to_anthropic_tool(
    name: str, description: str, input_model: type[BaseModel]
) -> dict[str, Any]:
    """Convert a Pydantic v2 input model into an Anthropic tool definition.

    Anthropic's tool format expects a flat JSON Schema under ``input_schema``.
    Pydantic's ``.model_json_schema()`` already produces JSON Schema; we strip
    the top-level ``title`` and ``description`` keys (Anthropic gets those
    separately) to keep the payload minimal.
    """
    schema = input_model.model_json_schema()
    schema.pop("title", None)
    schema.pop("description", None)
    return {
        "name": name,
        "description": description,
        "input_schema": schema,
    }
