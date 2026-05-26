"""CLI for exercising Gold tools without Claude.

Usage:
    cd api
    python -m app.tools.cli get_active_alerts        --tenant 7 --severity HIGH --limit 5
    python -m app.tools.cli get_store_dashboard      --tenant 7
    python -m app.tools.cli get_brand_performance    --tenant 7 --brand-id 1
    python -m app.tools.cli get_executive_summary    --tenant 7
    python -m app.tools.cli get_sku_detail           --tenant 7 --sku-id 7
    python -m app.tools.cli get_sku_coverage_status  --tenant 7 --status RED --limit 5
    python -m app.tools.cli get_velocity_segmentation --tenant 7 --segment A
    python -m app.tools.cli get_action_recommendations --tenant 7 --limit 5
    python -m app.tools.cli compare_periods          --tenant 7 --metric revenue_net \\
        --period-a 2026-W18 --period-b 2026-W19 --scope brand
    python -m app.tools.cli get_audit_trail          --tenant 7 --role direccion \\
        --request-id <uuid>

The CLI validates the input through the tool's Pydantic model (so errors look
exactly like they will when called from the orchestrator), runs the async
function on a fresh event loop, and prints the result as JSON.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from app.tools import TOOL_REGISTRY


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.tools.cli",
        description="Exercise a Gold tool from the command line.",
    )
    parser.add_argument(
        "tool",
        choices=sorted(TOOL_REGISTRY.keys()),
        help="Tool name (must be in the registry).",
    )
    parser.add_argument("--tenant", type=int, required=True, help="Tenant id (BIGINT).")
    parser.add_argument(
        "--role",
        default="direccion",
        help="Caller role (for role-restricted tools). Default: 'direccion'.",
    )
    # Union of optional args across all tools. Each tool ignores what it
    # doesn't need; values that fail the tool's pydantic schema surface as
    # validation errors.
    parser.add_argument("--level", default=None)
    parser.add_argument("--severity", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--store-id", type=int, default=None, dest="store_id")
    parser.add_argument("--brand-id", type=int, default=None, dest="brand_id")
    parser.add_argument("--sku-id", type=int, default=None, dest="sku_id")
    parser.add_argument("--category-id", type=int, default=None, dest="category_id")
    parser.add_argument("--week-id", default=None, dest="week_id")
    parser.add_argument("--status", default=None)
    parser.add_argument("--segment", default=None)
    parser.add_argument("--scope", default=None)
    parser.add_argument("--metric", default=None)
    parser.add_argument("--period-a", default=None, dest="period_a")
    parser.add_argument("--period-b", default=None, dest="period_b")
    parser.add_argument("--request-id", default=None, dest="request_id")
    parser.add_argument(
        "--pretty", action="store_true", help="Pretty-print JSON with indent=2."
    )
    return parser


def _filter_kwargs(args: argparse.Namespace, input_model: type) -> dict[str, Any]:
    """Pick only fields the tool's input model declares; drop None values so
    model defaults take over."""
    model_fields = input_model.model_fields.keys()
    return {k: v for k, v in vars(args).items() if k in model_fields and v is not None}


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    entry = TOOL_REGISTRY[args.tool]

    # Role gating: enforce in CLI too so the user sees the same error the
    # dispatcher would return.
    required_roles = entry.get("required_roles")
    if required_roles and args.role.lower() not in {r.lower() for r in required_roles}:
        msg = {
            "error": "forbidden_for_role",
            "required": list(required_roles),
            "role": args.role,
        }
        print(json.dumps(msg, ensure_ascii=False))
        return 2

    raw_input = _filter_kwargs(args, entry["input_model"])
    validated = entry["input_model"](**raw_input).model_dump()

    result = asyncio.run(entry["fn"](tenant_id=args.tenant, **validated))

    indent = 2 if args.pretty else None
    print(json.dumps(result, default=str, indent=indent, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
