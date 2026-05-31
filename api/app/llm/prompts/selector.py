"""Vertical + role → system prompt selector.

select_prompt(role, vertical) picks the right system prompt.
The vertical (tenant-level) takes precedence: all users of a production
tenant get the production prompt regardless of their role.
Within a retail tenant, the role determines the prompt as before.

Falls back to GENERIC_SYSTEM_PROMPT so existing tests remain unaffected.
"""

from __future__ import annotations

from app.llm.prompts.direccion import DIRECCION_SYSTEM_PROMPT
from app.llm.prompts.generic import GENERIC_SYSTEM_PROMPT
from app.llm.prompts.marca import MARCA_SYSTEM_PROMPT
from app.llm.prompts.produccion import PRODUCCION_SYSTEM_PROMPT
from app.llm.prompts.sku import SKU_SYSTEM_PROMPT
from app.llm.prompts.tienda import TIENDA_SYSTEM_PROMPT

# Retail: role → prompt
_ROLE_MAP: dict[str, str] = {
    "direccion":  DIRECCION_SYSTEM_PROMPT,
    "marca":      MARCA_SYSTEM_PROMPT,
    "tienda":     TIENDA_SYSTEM_PROMPT,
    "sku":        SKU_SYSTEM_PROMPT,
}

# Vertical → prompt (tenant-level override; role ignored within this vertical)
_VERTICAL_MAP: dict[str, str] = {
    "produccion": PRODUCCION_SYSTEM_PROMPT,
}


def select_prompt(role: str | None, vertical: str = "retail") -> str:
    """Return the system prompt for the given vertical + role combination.

    The vertical is the tenant-level attribute. If a vertical-specific prompt
    exists, it is returned for ALL roles within that tenant. Otherwise the
    role-based retail map is used, falling back to the generic prompt.
    """
    vert = (vertical or "retail").lower().strip()
    if vert in _VERTICAL_MAP:
        return _VERTICAL_MAP[vert]
    return _ROLE_MAP.get((role or "").lower().strip(), GENERIC_SYSTEM_PROMPT)
