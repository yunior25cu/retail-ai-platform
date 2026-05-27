"""Tests for the Sub-fase 5.4 eval framework.

Does NOT call the real Anthropic API. Uses the same mock-client pattern as
test_orchestrator.py (SimpleNamespace + AsyncMock) so tests run without
ANTHROPIC_API_KEY and complete deterministically.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.evaluation.catalog import CATALOG, EvalQuestion
from app.evaluation.comparator import compare_runs
from app.evaluation.metrics import compute_metrics
from app.evaluation.report import render_json, render_text
from app.evaluation.runner import EvalRun, EvalRunner, QuestionResult


# ─────────────────────────────────────────────────────────────────────────────
# Catalog structure
# ─────────────────────────────────────────────────────────────────────────────

def test_catalog_has_20_questions() -> None:
    assert len(CATALOG) == 20


def test_catalog_ids_unique() -> None:
    ids = [q.id for q in CATALOG]
    assert len(ids) == len(set(ids))


def test_catalog_roles_valid() -> None:
    valid = {"direccion", "marca", "tienda", "sku"}
    for q in CATALOG:
        assert q.role in valid, f"{q.id}: unknown role '{q.role}'"


def test_catalog_role_distribution() -> None:
    from collections import Counter
    counts = Counter(q.role for q in CATALOG)
    # Each role gets 5 questions.
    assert all(v == 5 for v in counts.values()), f"Uneven distribution: {dict(counts)}"


def test_catalog_all_have_expected_tools() -> None:
    for q in CATALOG:
        assert q.expected_tools, f"{q.id}: expected_tools is empty"


def test_catalog_all_have_expected_concepts() -> None:
    for q in CATALOG:
        assert q.expected_concepts, f"{q.id}: expected_concepts is empty"


def test_catalog_questions_in_spanish() -> None:
    for q in CATALOG:
        assert any(c in q.question for c in "aeiouáéíóú"), (
            f"{q.id}: question doesn't look like Spanish"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Mock client helpers (same pattern as test_orchestrator.py)
# ─────────────────────────────────────────────────────────────────────────────

def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _message(content, stop_reason="end_turn", in_tok=50, out_tok=100):
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
    )


def _mock_client(response_text: str = "Esta semana la facturación fue alta.") -> AsyncMock:
    mock = AsyncMock()
    mock.messages = AsyncMock()
    mock.messages.create = AsyncMock(
        return_value=_message([_text_block(response_text)])
    )
    return mock


# ─────────────────────────────────────────────────────────────────────────────
# EvalRunner
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_runner_produces_one_result_per_question() -> None:
    subset = CATALOG[:3]
    client = _mock_client("Facturación alta. margen positivo. semana buena.")
    run = await EvalRunner(tenant_id=7, client=client).run(subset)
    assert len(run.results) == 3


@pytest.mark.asyncio
async def test_runner_result_fields_populated() -> None:
    q = CATALOG[0]  # Q01 — directed, expected "get_executive_weekly_briefing"
    client = _mock_client("Facturación y margen OK esta semana.")
    run = await EvalRunner(tenant_id=7, client=client).run([q])
    r = run.results[0]

    assert r.question_id == q.id
    assert r.role == q.role
    assert r.question == q.question
    assert isinstance(r.response, str)
    assert isinstance(r.tools_invoked, list)
    assert r.duration_ms >= 0
    assert r.error is None


@pytest.mark.asyncio
async def test_runner_tool_hit_false_when_no_tools_invoked() -> None:
    """Mock client returns end_turn immediately (no tool_use) → tool_hit=False."""
    q = CATALOG[0]
    client = _mock_client("Respuesta directa sin herramientas.")
    run = await EvalRunner(tenant_id=7, client=client).run([q])
    r = run.results[0]
    # No tool_use blocks in the mocked response → tools_invoked == []
    assert r.tools_invoked == []
    assert r.tool_hit is False


@pytest.mark.asyncio
async def test_runner_concept_hits_detected() -> None:
    """Mock response contains two expected concepts."""
    q = CATALOG[0]  # expected_concepts: ["facturación", "margen", "semana"]
    response = "La facturación de la semana fue positiva."
    client = _mock_client(response)
    run = await EvalRunner(tenant_id=7, client=client).run([q])
    r = run.results[0]
    # "facturación" and "semana" should be detected; "margen" is absent.
    assert "facturación" in r.concept_hits
    assert "semana" in r.concept_hits
    assert "margen" not in r.concept_hits


@pytest.mark.asyncio
async def test_runner_captures_error() -> None:
    """If the orchestrator raises, error is captured and result still produced."""
    mock = AsyncMock()
    mock.messages = AsyncMock()
    mock.messages.create = AsyncMock(side_effect=RuntimeError("API failure"))

    q = CATALOG[0]
    run = await EvalRunner(tenant_id=7, client=mock).run([q])
    r = run.results[0]
    assert r.error is not None
    assert "API failure" in r.error


# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────

def _make_run(tool_hits: list[bool], concept_hits_per_q: list[list[str]]) -> EvalRun:
    """Build a synthetic EvalRun for metrics testing."""
    assert len(tool_hits) == len(concept_hits_per_q)
    results = []
    for i, (hit, concepts) in enumerate(zip(tool_hits, concept_hits_per_q)):
        q = CATALOG[i]
        results.append(
            QuestionResult(
                question_id=q.id,
                role=q.role,
                question=q.question,
                response=" ".join(concepts),
                tools_invoked=q.expected_tools[:1] if hit else [],
                tokens_input=100,
                tokens_output=50,
                duration_ms=200,
                error=None,
                tool_hit=hit,
                concept_hits=concepts,
            )
        )
    return EvalRun(run_id="test", timestamp="2026-01-01T00:00:00+00:00", tenant_id=7, results=results)


def test_metrics_tool_hit_rate() -> None:
    run = _make_run(
        tool_hits=[True, True, False, False],
        concept_hits_per_q=[["facturación"], ["abril"], [], []],
    )
    m = compute_metrics(run)
    assert m.tool_hit_rate == 0.5
    assert m.total_questions == 4


def test_metrics_success_rate_all_ok() -> None:
    run = _make_run([True] * 5, [["facturación"]] * 5)
    m = compute_metrics(run)
    assert m.success_rate == 1.0


def test_metrics_empty_run() -> None:
    run = EvalRun(run_id="x", timestamp="", tenant_id=7, results=[])
    m = compute_metrics(run)
    assert m.total_questions == 0
    assert m.tool_hit_rate == 0.0


def test_metrics_by_role_keys() -> None:
    run = _make_run([True] * 5, [["facturación"]] * 5)
    m = compute_metrics(run)
    # First 5 questions are all "direccion"
    assert "direccion" in m.by_role


# ─────────────────────────────────────────────────────────────────────────────
# Comparator
# ─────────────────────────────────────────────────────────────────────────────

def test_comparator_improvement_detected() -> None:
    run_a = _make_run(
        tool_hits=[False, True],
        concept_hits_per_q=[[], ["facturación"]],
    )
    run_b = _make_run(
        tool_hits=[True, True],  # Q01 now hits
        concept_hits_per_q=[["facturación", "margen", "semana"], ["facturación"]],
    )
    cmp = compare_runs(run_a, run_b)
    assert len(cmp.improved) >= 1
    assert len(cmp.regressed) == 0


def test_comparator_regression_detected() -> None:
    run_a = _make_run([True, True], [["facturación"], ["abril"]])
    run_b = _make_run([False, True], [[], ["abril"]])  # Q01 regressed
    cmp = compare_runs(run_a, run_b)
    assert len(cmp.regressed) >= 1


def test_comparator_to_dict_schema() -> None:
    run_a = _make_run([True] * 3, [["facturación"]] * 3)
    run_b = _make_run([True] * 3, [["facturación"]] * 3)
    cmp = compare_runs(run_a, run_b)
    doc = cmp.to_dict()
    assert "summary" in doc
    assert "tool_hit_rate_delta" in doc["summary"]
    assert "improved_count" in doc["summary"]


# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────

def test_render_json_valid() -> None:
    run = _make_run([True, False], [["facturación"], []])
    text = render_json(run)
    doc = json.loads(text)
    assert "run_id" in doc
    assert "metrics" in doc
    assert "results" in doc
    assert doc["metrics"]["total_questions"] == 2


def test_render_text_contains_key_sections() -> None:
    run = _make_run([True, False, True], [["facturación"], [], ["margen"]])
    text = render_text(run)
    assert "GLOBAL METRICS" in text
    assert "BY ROLE" in text
    assert "PER-QUESTION DETAIL" in text
    assert "Tool hit rate" in text


def test_render_text_shows_hit_marker() -> None:
    run = _make_run([True, False], [["facturación"], []])
    text = render_text(run)
    assert "✓" in text
    assert "✗" in text
