"""Render EvalRun + EvalMetrics as text or JSON."""

from __future__ import annotations

import json
from typing import Any

from app.evaluation.metrics import EvalMetrics, compute_metrics
from app.evaluation.runner import EvalRun


def render_json(run: EvalRun, metrics: EvalMetrics | None = None) -> str:
    """Return a JSON string with the full run + computed metrics."""
    if metrics is None:
        metrics = compute_metrics(run)
    doc: dict[str, Any] = {
        "run_id": run.run_id,
        "timestamp": run.timestamp,
        "tenant_id": run.tenant_id,
        "metrics": metrics.to_dict(),
        "results": run.to_dict()["results"],
    }
    return json.dumps(doc, ensure_ascii=False, indent=2)


def render_text(run: EvalRun, metrics: EvalMetrics | None = None) -> str:
    """Return a human-readable text report."""
    if metrics is None:
        metrics = compute_metrics(run)

    lines: list[str] = [
        "=" * 72,
        f"EVAL RUN  {run.run_id}",
        f"Timestamp : {run.timestamp}",
        f"Tenant    : {run.tenant_id}",
        f"Questions : {metrics.total_questions}",
        "=" * 72,
        "",
        "── GLOBAL METRICS ──────────────────────────────────────────────────",
        f"  Success rate      : {metrics.success_rate:.1%}",
        f"  Tool hit rate     : {metrics.tool_hit_rate:.1%}",
        f"  Concept coverage  : {metrics.concept_coverage:.1%}",
        f"  Avg latency       : {metrics.avg_latency_ms:.0f} ms",
        f"  Avg tokens in     : {metrics.avg_tokens_input:.0f}",
        f"  Avg tokens out    : {metrics.avg_tokens_output:.0f}",
        "",
        "── BY ROLE ─────────────────────────────────────────────────────────",
    ]
    for role, stats in sorted(metrics.by_role.items()):
        lines.append(
            f"  {role:<12} "
            f"n={stats['total']}  "
            f"hit={stats['tool_hit_rate']:.0%}  "
            f"ok={stats['success_rate']:.0%}  "
            f"ms={stats['avg_latency_ms']:.0f}"
        )

    lines += [
        "",
        "── PER-QUESTION DETAIL ──────────────────────────────────────────────",
        f"{'ID':<5} {'Role':<10} {'Hit':<5} {'Concepts':<10} {'ms':>6}  Question",
        "-" * 72,
    ]
    for r in run.results:
        from app.evaluation.catalog import CATALOG
        q = next((q for q in CATALOG if q.id == r.question_id), None)
        total_concepts = len(q.expected_concepts) if q else 0
        concept_str = f"{len(r.concept_hits)}/{total_concepts}"
        hit_str = "✓" if r.tool_hit else "✗"
        err_marker = " [ERR]" if r.error else ""
        lines.append(
            f"{r.question_id:<5} {r.role:<10} {hit_str:<5} {concept_str:<10} "
            f"{r.duration_ms:>6}  {r.question[:45]}{err_marker}"
        )

    lines += ["", "=" * 72]
    return "\n".join(lines)
