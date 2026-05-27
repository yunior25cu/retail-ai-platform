"""Compare two EvalRun results to surface regressions and improvements.

Usage:
    diff = compare_runs(run_a, run_b)
    # diff.improved / diff.regressed / diff.unchanged
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.evaluation.metrics import EvalMetrics, compute_metrics
from app.evaluation.runner import EvalRun, QuestionResult


@dataclass
class QuestionDiff:
    question_id: str
    role: str
    question: str
    tool_hit_a: bool
    tool_hit_b: bool
    concept_coverage_a: float
    concept_coverage_b: float
    latency_ms_a: int
    latency_ms_b: int
    tools_a: list[str]
    tools_b: list[str]

    @property
    def tool_hit_changed(self) -> bool:
        return self.tool_hit_a != self.tool_hit_b

    @property
    def is_improvement(self) -> bool:
        if self.tool_hit_b and not self.tool_hit_a:
            return True
        if self.concept_coverage_b > self.concept_coverage_a + 0.1:
            return True
        return False

    @property
    def is_regression(self) -> bool:
        if self.tool_hit_a and not self.tool_hit_b:
            return True
        if self.concept_coverage_a > self.concept_coverage_b + 0.1:
            return True
        return False


@dataclass
class RunComparison:
    run_id_a: str
    run_id_b: str
    metrics_a: EvalMetrics
    metrics_b: EvalMetrics
    question_diffs: list[QuestionDiff]

    @property
    def improved(self) -> list[QuestionDiff]:
        return [d for d in self.question_diffs if d.is_improvement]

    @property
    def regressed(self) -> list[QuestionDiff]:
        return [d for d in self.question_diffs if d.is_regression]

    @property
    def unchanged(self) -> list[QuestionDiff]:
        return [d for d in self.question_diffs if not d.is_improvement and not d.is_regression]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id_a": self.run_id_a,
            "run_id_b": self.run_id_b,
            "summary": {
                "tool_hit_rate_delta": round(
                    self.metrics_b.tool_hit_rate - self.metrics_a.tool_hit_rate, 4
                ),
                "concept_coverage_delta": round(
                    self.metrics_b.concept_coverage - self.metrics_a.concept_coverage, 4
                ),
                "latency_delta_ms": round(
                    self.metrics_b.avg_latency_ms - self.metrics_a.avg_latency_ms, 1
                ),
                "improved_count": len(self.improved),
                "regressed_count": len(self.regressed),
                "unchanged_count": len(self.unchanged),
            },
            "improvements": [_diff_to_dict(d) for d in self.improved],
            "regressions": [_diff_to_dict(d) for d in self.regressed],
        }


def compare_runs(run_a: EvalRun, run_b: EvalRun) -> RunComparison:
    """Produce a RunComparison between two EvalRuns."""
    metrics_a = compute_metrics(run_a)
    metrics_b = compute_metrics(run_b)

    # Index run_b results by question_id for O(1) lookup.
    b_by_id = {r.question_id: r for r in run_b.results}

    diffs: list[QuestionDiff] = []
    for ra in run_a.results:
        rb = b_by_id.get(ra.question_id)
        if rb is None:
            continue
        cov_a = _concept_coverage(ra)
        cov_b = _concept_coverage(rb)
        diffs.append(
            QuestionDiff(
                question_id=ra.question_id,
                role=ra.role,
                question=ra.question,
                tool_hit_a=ra.tool_hit,
                tool_hit_b=rb.tool_hit,
                concept_coverage_a=cov_a,
                concept_coverage_b=cov_b,
                latency_ms_a=ra.duration_ms,
                latency_ms_b=rb.duration_ms,
                tools_a=ra.tools_invoked,
                tools_b=rb.tools_invoked,
            )
        )

    return RunComparison(
        run_id_a=run_a.run_id,
        run_id_b=run_b.run_id,
        metrics_a=metrics_a,
        metrics_b=metrics_b,
        question_diffs=diffs,
    )


def _concept_coverage(r: QuestionResult) -> float:
    from app.evaluation.catalog import CATALOG
    q = next((q for q in CATALOG if q.id == r.question_id), None)
    if q is None or not q.expected_concepts:
        return 1.0
    return len(r.concept_hits) / len(q.expected_concepts)


def _diff_to_dict(d: QuestionDiff) -> dict[str, Any]:
    return {
        "question_id": d.question_id,
        "role": d.role,
        "question": d.question,
        "tool_hit_a": d.tool_hit_a,
        "tool_hit_b": d.tool_hit_b,
        "concept_coverage_a": round(d.concept_coverage_a, 4),
        "concept_coverage_b": round(d.concept_coverage_b, 4),
        "tools_a": d.tools_a,
        "tools_b": d.tools_b,
    }
