"""CLI for exercising Gold tools without Claude.

Usage:
    cd api
    python -m app.tools.cli get_active_alerts --tenant 7 --severity HIGH --limit 5
    python -m app.tools.cli get_store_dashboard --tenant 7
    python -m app.tools.cli get_brand_performance --tenant 7 --brand-id 1

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
    parser.add_argument(
        "--tenant", type=int, required=True, help="Tenant id (BIGINT)."
    )
    # Union of optional args across the 3 sub-phase-4.2 tools. Each tool ignores
    # what it doesn't need.
    parser.add_argument("--level", default=None)
    parser.add_argument("--severity", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--store-id", type=int, default=None, dest="store_id")
    parser.add_argument("--brand-id", type=int, default=None, dest="brand_id")
    parser.add_argument("--week-id", default=None, dest="week_id")
    parser.add_argument(
        "--pretty", action="store_true", help="Pretty-print JSON with indent=2."
    )
    return parser


def _filter_kwargs(args: argparse.Namespace, input_model: type) -> dict[str, Any]:
    """Pick only fields the tool's input model declares; drop None values so
    the model defaults take over."""
    model_fields = input_model.model_fields.keys()
    return {k: v for k, v in vars(args).items() if k in model_fields and v is not None}


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    entry = TOOL_REGISTRY[args.tool]
    raw_input = _filter_kwargs(args, entry["input_model"])

    # Validate input (raises ValidationError if anything is off).
    validated = entry["input_model"](**raw_input).model_dump()

    result = asyncio.run(entry["fn"](tenant_id=args.tenant, **validated))

    indent = 2 if args.pretty else None
    print(json.dumps(result, default=str, indent=indent, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
