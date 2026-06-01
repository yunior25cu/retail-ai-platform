"""Temporary token-breakdown logger for production cost analysis.

Logs the next TOKEN_LOG_LIMIT queries for TARGET_TENANT_ID with a
per-component token breakdown. Reads and auto-stops after the limit.

Usage: imported once at startup; log_token_breakdown() is called from
internal_chat after a successful run_conversation().

Output goes to structlog (same as the rest of the API).
Set TOKEN_LOG_LIMIT=0 to disable without code changes.
"""

from __future__ import annotations

import os
from typing import Any

import structlog

log = structlog.get_logger("token_logger")

# ── Config ────────────────────────────────────────────────────────────────────
TARGET_TENANT_ID: int = int(os.getenv("TOKEN_LOG_TENANT", "24"))
TOKEN_LOG_LIMIT:  int = int(os.getenv("TOKEN_LOG_LIMIT",  "20"))

# Approximate cost for claude-sonnet-4-6 (USD per token)
_COST_INPUT_PER_TOKEN  = 3.0  / 1_000_000   # $3 / 1M input
_COST_OUTPUT_PER_TOKEN = 15.0 / 1_000_000   # $15 / 1M output

# In-memory counter — resets on API restart
_log_count: int = 0


# ── Token estimation ──────────────────────────────────────────────────────────

def _est(text: str | Any) -> int:
    """Rough token estimate: ~4 chars per token (English/Spanish mix)."""
    if not text:
        return 0
    s = text if isinstance(text, str) else str(text)
    return max(1, len(s) // 4)


def _history_tokens(history: list[dict]) -> int:
    """Estimate tokens for the conversation history messages."""
    total = 0
    for msg in history:
        content = msg.get("content", "")
        if isinstance(content, list):
            for block in content:
                total += _est(block.get("text", "") if isinstance(block, dict) else str(block))
        else:
            total += _est(content)
    return total


# ── Main logging function ─────────────────────────────────────────────────────

def log_token_breakdown(
    *,
    tenant_id: int,
    query: str,
    system_prompt: str,
    history: list[dict],
    total_input_tokens: int,
    total_output_tokens: int,
    tools_invoked: list[str],
    response_text: str,
    tool_cache_hits: list[str] | None = None,
) -> None:
    """Log a per-component token breakdown. Auto-stops after TOKEN_LOG_LIMIT."""
    global _log_count

    if tenant_id != TARGET_TENANT_ID:
        return
    if TOKEN_LOG_LIMIT <= 0 or _log_count >= TOKEN_LOG_LIMIT:
        return

    _log_count += 1

    # Component estimates
    sp_tokens   = _est(system_prompt)
    hist_tokens = _history_tokens(history)
    usr_tokens  = _est(query)
    resp_tokens = total_output_tokens  # exact from Anthropic API

    # Tool results = what's left after known components
    # (total_input includes system + history + user + all tool results across iterations)
    tool_tokens = max(0, total_input_tokens - sp_tokens - hist_tokens - usr_tokens)

    cost_usd = (
        total_input_tokens  * _COST_INPUT_PER_TOKEN +
        total_output_tokens * _COST_OUTPUT_PER_TOKEN
    )

    cache_hits = tool_cache_hits or []
    log.info(
        "token_breakdown",
        log_n=f"{_log_count}/{TOKEN_LOG_LIMIT}",
        tenant_id=tenant_id,
        query=query[:120] + ("…" if len(query) > 120 else ""),
        system_prompt_tokens=sp_tokens,
        history_tokens=hist_tokens,
        user_message_tokens=usr_tokens,
        tool_results_tokens_est=tool_tokens,
        response_tokens=resp_tokens,
        tool_calls=tools_invoked,
        tool_call_count=len(tools_invoked),
        cache_hits=cache_hits,
        cache_hit_count=len(cache_hits),
        total_input=total_input_tokens,
        total_output=total_output_tokens,
        estimated_cost_usd=round(cost_usd, 6),
        note="system/history/user/tool are estimates (~4 chars/token); "
             "total_input/output are exact from Anthropic API",
    )

    if _log_count >= TOKEN_LOG_LIMIT:
        log.info(
            "token_logger.complete",
            message=f"Reached {TOKEN_LOG_LIMIT} logged queries for tenant {tenant_id}. "
                    "Set TOKEN_LOG_LIMIT=0 in .env to disable.",
        )
