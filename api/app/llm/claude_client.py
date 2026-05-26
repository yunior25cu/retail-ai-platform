"""Factory for the AsyncAnthropic client.

Single point of construction so tests can monkeypatch / replace at one place,
and so we centralise the "is the API key configured?" check.
"""

from __future__ import annotations

import anthropic

from app.config import settings

_PLACEHOLDER_KEYS = {"", "sk-ant-replace-me", "sk-ant-xxx"}


def get_client() -> anthropic.AsyncAnthropic:
    if settings.anthropic_api_key in _PLACEHOLDER_KEYS:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not configured. Set it in api/.env before calling Claude."
        )
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
