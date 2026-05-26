"""Sanitiser unit tests against the real api_audit schema.

Each test creates its own conversation row, exercises the sanitiser, and
cleans up. No DB fixture leakage.
"""

from __future__ import annotations

import re
from uuid import uuid4

import pytest

from app.db.connection import execute_query
from app.db.conversation import create_conversation
from app.security.sanitizer import TOKEN_RE, Sanitizer


async def _cleanup_conv(conversation_id: str) -> None:
    # Delete in FK-safe order
    await execute_query(
        "DELETE FROM api_audit.conversation_token_map WHERE conversation_id = CAST(? AS UNIQUEIDENTIFIER);",
        (conversation_id,),
    )
    await execute_query(
        "DELETE FROM api_audit.conversation_message WHERE conversation_id = CAST(? AS UNIQUEIDENTIFIER);",
        (conversation_id,),
    )
    await execute_query(
        "DELETE FROM api_audit.conversation WHERE conversation_id = CAST(? AS UNIQUEIDENTIFIER);",
        (conversation_id,),
    )


@pytest.mark.asyncio
async def test_sanitizer_direccion_is_noop() -> None:
    conv = await create_conversation(tenant_id=7, user_id="u", user_role="direccion")
    try:
        s = Sanitizer()
        payload = [{"sku_id": 7, "store_id": 7, "brand_id": 1, "units": 100}]
        out = await s.tokenize_payload(
            payload, conversation_id=conv, tenant_id=7, role="direccion"
        )
        # Pass-through (same object identity not required, but values must match)
        assert out == payload
    finally:
        await _cleanup_conv(conv)


@pytest.mark.asyncio
async def test_sanitizer_marca_tokenizes_ids() -> None:
    conv = await create_conversation(tenant_id=7, user_id="u", user_role="marca")
    try:
        s = Sanitizer()
        payload = [
            {"sku_id": 7, "store_id": 7, "brand_id": 1, "units": 100},
            {"sku_id": 44, "units": 50},
        ]
        out = await s.tokenize_payload(
            payload, conversation_id=conv, tenant_id=7, role="marca"
        )
        assert isinstance(out, list)
        # IDs replaced with tokens; non-sensitive fields untouched
        assert isinstance(out[0]["sku_id"], str)
        assert TOKEN_RE.fullmatch(out[0]["sku_id"])
        assert isinstance(out[0]["store_id"], str)
        assert isinstance(out[0]["brand_id"], str)
        assert out[0]["units"] == 100
        # Same sku id gets the same token across rows
        assert out[0]["sku_id"] != out[1]["sku_id"]  # different ids -> different tokens
        # Re-tokenising the same id in the same conversation -> same token (DB hit)
        s2 = Sanitizer()
        out2 = await s2.tokenize_payload(
            [{"sku_id": 7}], conversation_id=conv, tenant_id=7, role="marca"
        )
        assert out2[0]["sku_id"] == out[0]["sku_id"]
    finally:
        await _cleanup_conv(conv)


@pytest.mark.asyncio
async def test_sanitizer_detokenize_replaces_tokens_with_display_names() -> None:
    conv = await create_conversation(tenant_id=7, user_id="u", user_role="marca")
    try:
        s = Sanitizer()
        payload = [{"sku_id": 7, "store_id": 7}]
        out = await s.tokenize_payload(
            payload, conversation_id=conv, tenant_id=7, role="marca"
        )
        sku_token = out[0]["sku_id"]
        store_token = out[0]["store_id"]

        # Build a fake "Claude response" containing both tokens.
        fake_response = (
            f"The product {sku_token} sold poorly in {store_token} this week."
        )
        result = await s.detokenize_text(
            fake_response, conversation_id=conv, role="marca"
        )
        # Tokens replaced; nothing of the form `[a-z]+_[0-9a-f]{8}` left.
        assert not TOKEN_RE.search(result)
        # The display names from dim_sku / dim_store should be present.
        # We don't assert exact strings (they come from the tenant data) but
        # the words shouldn't be the original tokens any more.
        assert sku_token not in result
        assert store_token not in result
    finally:
        await _cleanup_conv(conv)


@pytest.mark.asyncio
async def test_sanitizer_detokenize_direccion_noop() -> None:
    """Direccion sees the text unchanged."""
    s = Sanitizer()
    text = "alert about sku 7 in store 7"
    out = await s.detokenize_text(text, conversation_id=str(uuid4()), role="direccion")
    assert out == text
