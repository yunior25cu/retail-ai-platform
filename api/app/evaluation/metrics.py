"""Aggregate metrics over an EvalRun."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.evaluation.runner import EvalRun, QuestionResult


@dataclass
class EvalMetrics:
    total_questions: int
    success_rate: float          # % without errors
    tool_hit_rate: float         # % where at least one expected tool was called
    concept_coverage: float      # % of expected concepts found across all questions
    avg_latency_ms: float
    avg_tokens_input: float
    avg_tokens_output: float
    avg_tokens_total: float
    by_role: dict[str, dict[str, Any]]  # per-role breakdown

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_questions": self.total_questions,
            "success_rate": round(self.success_rate, 4),
            "tool_hit_rate": round(self.tool_hit_rate, 4),
            "concept_coverage": round(self.concept_coverage, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "avg_tokens_input": round(self.avg_tokens_input, 1),
            "avg_tokens_output": round(self.avg_tokens_output, 1),
            "avg_tokens_total": round(self.avg_tokens_total, 1),
            "by_role": self.by_role,
        }


def compute_metrics(run: EvalRun) -> EvalMetrics:
    """Compute aggregate metrics from a completed EvalRun."""
    results = run.results
    if not results:
        return EvalMetrics(
            total_questions=0,
            success_rate=0.0,
            tool_hit_rate=0.0,
            concept_coverage=0.0,
            avg_latency_ms=0.0,
            avg_tokens_input=0.0,
            avg_tokens_output=0.0,
            avg_tokens_total=0.0,
            by_role={},
        )

    n = len(results)
    successful = [r for r in results if r.error is None]
    hits = [r for r in results if r.tool_hit]

    # concept_coverage = (sum of concept_hit_rate per question) / n
    concept_rates = [
        _concept_hit_rate(r)
        for r in results
    ]
    concept_coverage = sum(concept_rates) / n if n else 0.0

    avg_latency = sum(r.duration_ms for r in results) / n
    avg_in = sum(r.tokens_input for r in results) / n
    avg_out = sum(r.tokens_output for r in results) / n

    by_role = _by_role(results)

    return EvalMetrics(
        total_questions=n,
        success_rate=len(successful) / n,
        tool_hit_rate=len(hits) / n,
        concept_coverage=concept_coverage,
        avg_latency_ms=avg_latency,
        avg_tokens_input=avg_in,
        avg_tokens_output=avg_out,
        avg_tokens_total=avg_in + avg_out,
        by_role=by_role,
    )


def _concept_hit_rate(r: QuestionResult) -> float:
    from app.evaluation.catalog import CATALOG
    q = next((q for q in CATALOG if q.id == r.question_id), None)
    if q is None or not q.expected_concepts:
        return 1.0
    return len(r.concept_hits) / len(q.expected_concepts)


def _by_role(results: list[QuestionResult]) -> dict[str, dict[str, Any]]:
    roles: dict[str, list[QuestionResult]] = {}
    for r in results:
        roles.setdefault(r.role, []).append(r)

    out: dict[str, dict[str, Any]] = {}
    for role, rs in roles.items():
        nr = len(rs)
        out[role] = {
            "total": nr,
            "success_rate": round(sum(1 for r in rs if r.error is None) / nr, 4),
            "tool_hit_rate": round(sum(1 for r in rs if r.tool_hit) / nr, 4),
            "avg_latency_ms": round(sum(r.duration_ms for r in rs) / nr, 1),
        }
    return out
