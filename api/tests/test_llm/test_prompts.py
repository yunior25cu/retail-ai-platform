"""Tests for the role-based prompt selector (Sub-fase 5.2).

Verifies:
- select_prompt routes each known role to the correct prompt constant.
- Unknown / None role falls back to GENERIC_SYSTEM_PROMPT.
- Each role prompt contains the 7 mandatory sections.
- Each role prompt enforces voseo and Spanish monolingual defaults.
- chat.py passes select_prompt(role) to the orchestrator (integration smoke test).
"""

from __future__ import annotations

import pytest

from app.llm.prompts import select_prompt
from app.llm.prompts.direccion import DIRECCION_SYSTEM_PROMPT
from app.llm.prompts.generic import GENERIC_SYSTEM_PROMPT
from app.llm.prompts.marca import MARCA_SYSTEM_PROMPT
from app.llm.prompts.selector import _ROLE_MAP
from app.llm.prompts.sku import SKU_SYSTEM_PROMPT
from app.llm.prompts.tienda import TIENDA_SYSTEM_PROMPT

_KNOWN_ROLES = ["direccion", "marca", "tienda", "sku"]
_SEVEN_SECTIONS = ["## ROL", "## HERRAMIENTAS", "## WORKFLOW", "## ESTILO", "## IDIOMA", "## TÉRMINOS", "## LÍMITES"]


# ─────────────────────────────────────────────────────────────────────────────
# selector routing
# ─────────────────────────────────────────────────────────────────────────────

def test_select_prompt_direccion() -> None:
    assert select_prompt("direccion") is DIRECCION_SYSTEM_PROMPT


def test_select_prompt_marca() -> None:
    assert select_prompt("marca") is MARCA_SYSTEM_PROMPT


def test_select_prompt_tienda() -> None:
    assert select_prompt("tienda") is TIENDA_SYSTEM_PROMPT


def test_select_prompt_sku() -> None:
    assert select_prompt("sku") is SKU_SYSTEM_PROMPT


def test_select_prompt_case_insensitive() -> None:
    assert select_prompt("DIRECCION") is DIRECCION_SYSTEM_PROMPT
    assert select_prompt("Marca") is MARCA_SYSTEM_PROMPT


def test_select_prompt_none_falls_back_to_generic() -> None:
    assert select_prompt(None) is GENERIC_SYSTEM_PROMPT


def test_select_prompt_unknown_role_falls_back_to_generic() -> None:
    assert select_prompt("admin") is GENERIC_SYSTEM_PROMPT
    assert select_prompt("") is GENERIC_SYSTEM_PROMPT
    assert select_prompt("superuser") is GENERIC_SYSTEM_PROMPT


def test_role_map_covers_all_known_roles() -> None:
    for role in _KNOWN_ROLES:
        assert role in _ROLE_MAP, f"Role '{role}' missing from _ROLE_MAP"


# ─────────────────────────────────────────────────────────────────────────────
# 7-section structure validation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("role,prompt", [
    ("direccion", DIRECCION_SYSTEM_PROMPT),
    ("marca",     MARCA_SYSTEM_PROMPT),
    ("tienda",    TIENDA_SYSTEM_PROMPT),
    ("sku",       SKU_SYSTEM_PROMPT),
])
def test_prompt_has_seven_sections(role: str, prompt: str) -> None:
    for section in _SEVEN_SECTIONS:
        assert section in prompt, (
            f"Role '{role}': prompt is missing section '{section}'"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Language / register requirements
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("role,prompt", [
    ("direccion", DIRECCION_SYSTEM_PROMPT),
    ("marca",     MARCA_SYSTEM_PROMPT),
    ("tienda",    TIENDA_SYSTEM_PROMPT),
    ("sku",       SKU_SYSTEM_PROMPT),
])
def test_prompt_enforces_voseo(role: str, prompt: str) -> None:
    assert "voseo" in prompt.lower() or "vos," in prompt.lower(), (
        f"Role '{role}': prompt does not mention voseo"
    )


@pytest.mark.parametrize("role,prompt", [
    ("direccion", DIRECCION_SYSTEM_PROMPT),
    ("marca",     MARCA_SYSTEM_PROMPT),
    ("tienda",    TIENDA_SYSTEM_PROMPT),
    ("sku",       SKU_SYSTEM_PROMPT),
])
def test_prompt_has_spanish_monolingual_rule(role: str, prompt: str) -> None:
    assert "español" in prompt.lower(), (
        f"Role '{role}': prompt does not enforce Spanish as default language"
    )


@pytest.mark.parametrize("role,prompt", [
    ("direccion", DIRECCION_SYSTEM_PROMPT),
    ("marca",     MARCA_SYSTEM_PROMPT),
    ("tienda",    TIENDA_SYSTEM_PROMPT),
    ("sku",       SKU_SYSTEM_PROMPT),
])
def test_prompt_forbids_invented_numbers(role: str, prompt: str) -> None:
    assert "invent" in prompt.lower(), (
        f"Role '{role}': prompt does not explicitly prohibit inventing numbers"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Role-specific tool mentions
# ─────────────────────────────────────────────────────────────────────────────

def test_direccion_prompt_mentions_audit_trail() -> None:
    assert "get_audit_trail" in DIRECCION_SYSTEM_PROMPT


def test_direccion_prompt_mentions_composite_briefings() -> None:
    assert "get_executive_weekly_briefing" in DIRECCION_SYSTEM_PROMPT
    assert "get_monthly_executive_briefing" in DIRECCION_SYSTEM_PROMPT


def test_marca_prompt_mentions_brand_weekly_review() -> None:
    assert "get_brand_weekly_review" in MARCA_SYSTEM_PROMPT


def test_marca_prompt_does_not_mention_audit_trail() -> None:
    assert "get_audit_trail" not in MARCA_SYSTEM_PROMPT


def test_tienda_prompt_mentions_store_daily_briefing() -> None:
    assert "get_store_daily_briefing" in TIENDA_SYSTEM_PROMPT


def test_tienda_prompt_does_not_mention_audit_trail() -> None:
    assert "get_audit_trail" not in TIENDA_SYSTEM_PROMPT


def test_sku_prompt_mentions_sku_tools() -> None:
    assert "get_sku_detail" in SKU_SYSTEM_PROMPT
    assert "get_sku_coverage_status" in SKU_SYSTEM_PROMPT
    assert "get_velocity_segmentation" in SKU_SYSTEM_PROMPT


# ─────────────────────────────────────────────────────────────────────────────
# chat.py integration — select_prompt is called per role
# ─────────────────────────────────────────────────────────────────────────────

def test_chat_module_imports_select_prompt() -> None:
    """Verify chat.py imports select_prompt (not the old GENERIC_SYSTEM_PROMPT constant)."""
    import importlib
    import ast
    import pathlib

    chat_path = pathlib.Path(__file__).parents[2] / "app" / "api" / "v1" / "chat.py"
    source = chat_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imports.append((node.module, [a.name for a in node.names]))

    found_select_prompt = any(
        "select_prompt" in names
        for _, names in imports
    )
    assert found_select_prompt, "chat.py does not import select_prompt"

    # GENERIC_SYSTEM_PROMPT should no longer be imported directly in chat.py
    has_generic_import = any(
        "GENERIC_SYSTEM_PROMPT" in names
        for _, names in imports
    )
    assert not has_generic_import, (
        "chat.py still imports GENERIC_SYSTEM_PROMPT directly — should use select_prompt"
    )
