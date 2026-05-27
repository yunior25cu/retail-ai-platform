"""CLI entry point for the eval framework.

Usage:
    python -m app.evaluation.cli --tenant 9001
    python -m app.evaluation.cli --tenant 9001 --output eval_run.json
    python -m app.evaluation.cli --tenant 9001 --ids Q01,Q02,Q03
    python -m app.evaluation.cli --tenant 9001 --role direccion
    python -m app.evaluation.cli --compare run_a.json run_b.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.evaluation.catalog import CATALOG, EvalQuestion
from app.evaluation.comparator import compare_runs
from app.evaluation.metrics import compute_metrics
from app.evaluation.report import render_json, render_text
from app.evaluation.runner import EvalRun, EvalRunner


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Retail AI Platform — Eval runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    # ── run ──────────────────────────────────────────────────────────────────
    run_p = sub.add_parser("run", help="Run the eval catalog against a tenant.")
    run_p.add_argument("--tenant", type=int, required=True, help="Tenant ID (use 9001 for synthetic data).")
    run_p.add_argument("--output", default=None, help="Write JSON results to this file.")
    run_p.add_argument("--ids", default=None, help="Comma-separated question IDs to run (default: all 20).")
    run_p.add_argument("--role", default=None, help="Filter questions by role.")
    run_p.add_argument("--text", action="store_true", help="Print text report to stdout.")

    # ── compare ──────────────────────────────────────────────────────────────
    cmp_p = sub.add_parser("compare", help="Compare two eval run JSON files.")
    cmp_p.add_argument("run_a", help="Path to first run JSON.")
    cmp_p.add_argument("run_b", help="Path to second run JSON.")
    cmp_p.add_argument("--output", default=None, help="Write comparison JSON to this file.")

    return p


def _filter_catalog(ids: str | None, role: str | None) -> list[EvalQuestion]:
    catalog = CATALOG
    if ids:
        id_set = {s.strip().upper() for s in ids.split(",")}
        catalog = [q for q in catalog if q.id in id_set]
    if role:
        catalog = [q for q in catalog if q.role == role.lower()]
    return catalog


async def _run(args: argparse.Namespace) -> None:
    catalog = _filter_catalog(args.ids, args.role)
    if not catalog:
        print("No questions matched the given filters.", file=sys.stderr)
        sys.exit(1)

    print(f"Running {len(catalog)} questions against tenant {args.tenant}…", file=sys.stderr)
    run = await EvalRunner(tenant_id=args.tenant).run(catalog)
    metrics = compute_metrics(run)

    if args.text or not args.output:
        print(render_text(run, metrics))

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(render_json(run, metrics))
        print(f"Results written to {args.output}", file=sys.stderr)


def _compare(args: argparse.Namespace) -> None:
    def _load(path: str) -> EvalRun:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        from dataclasses import fields
        from app.evaluation.runner import QuestionResult
        results = [QuestionResult(**r) for r in doc["results"]]
        return EvalRun(
            run_id=doc["run_id"],
            timestamp=doc["timestamp"],
            tenant_id=doc["tenant_id"],
            results=results,
        )

    run_a = _load(args.run_a)
    run_b = _load(args.run_b)
    comparison = compare_runs(run_a, run_b)
    doc = comparison.to_dict()

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print(f"Comparison written to {args.output}", file=sys.stderr)
    else:
        print(json.dumps(doc, ensure_ascii=False, indent=2))

    print(
        f"\nΔ tool_hit_rate   : {doc['summary']['tool_hit_rate_delta']:+.1%}\n"
        f"Δ concept_coverage: {doc['summary']['concept_coverage_delta']:+.1%}\n"
        f"Δ latency_ms      : {doc['summary']['latency_delta_ms']:+.0f} ms\n"
        f"Improved          : {doc['summary']['improved_count']} questions\n"
        f"Regressed         : {doc['summary']['regressed_count']} questions",
        file=sys.stderr,
    )


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "run":
        asyncio.run(_run(args))
    elif args.command == "compare":
        _compare(args)


if __name__ == "__main__":
    main()
