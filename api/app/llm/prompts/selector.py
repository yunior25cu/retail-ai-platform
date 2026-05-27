"""Role-to-prompt selector for Sub-fase 5.2.

select_prompt(role) returns the system prompt for the authenticated user's role.
Falls back to GENERIC_SYSTEM_PROMPT for unknown or None roles so existing tests
and direct orchestrator calls without a role remain unaffected.
"""

from __future__ import annotations

from app.llm.prompts.direccion import DIRECCION_SYSTEM_PROMPT
from app.llm.prompts.generic import GENERIC_SYSTEM_PROMPT
from app.llm.prompts.marca import MARCA_SYSTEM_PROMPT
from app.llm.prompts.sku import SKU_SYSTEM_PROMPT
from app.llm.prompts.tienda import TIENDA_SYSTEM_PROMPT

_ROLE_MAP: dict[str, str] = {
    "direccion": DIRECCION_SYSTEM_PROMPT,
    "marca":     MARCA_SYSTEM_PROMPT,
    "tienda":    TIENDA_SYSTEM_PROMPT,
    "sku":       SKU_SYSTEM_PROMPT,
}


def select_prompt(role: str | None) -> str:
    """Return the system prompt for *role*, falling back to the generic prompt."""
    return _ROLE_MAP.get((role or "").lower().strip(), GENERIC_SYSTEM_PROMPT)
