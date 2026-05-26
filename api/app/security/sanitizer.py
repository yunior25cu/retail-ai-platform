"""Bi-directional sanitiser for tool outputs and final responses.

For non-DIRECCION roles, internal numeric ids (sku_id / store_id / brand_id)
are replaced by short opaque tokens before being shown to the LLM. The
mapping is persisted to ``api_audit.conversation_token_map`` so it survives
across turns within the same conversation. After Claude returns its final
text, every token in the text is replaced by the entity's display name so
the user sees friendly labels instead of raw IDs.

For the DIRECCION role the sanitiser is a no-op: Dirección needs to see
technical IDs to ask precise follow-up questions.

Token format:
    <entity>_<8 hex chars>           e.g. sku_a1b2c3d4
    where entity ∈ {sku, store, brand}
"""

from __future__ import annotations

import re
import secrets
from typing import Any

from app.db.conversation import (
    fetch_display_names,
    find_token_for_entity,
    insert_token_mapping,
)

SENSITIVE_KEYS = {
    "sku_id": "sku",
    "store_id": "store",
    "brand_id": "brand",
}

TOKEN_RE = re.compile(r"\b(sku|store|brand)_[0-9a-f]{8}\b")


class Sanitizer:
    """Stateless façade — all state lives in the DB. One instance per request
    is fine (it caches token lookups within the request to avoid re-reading)."""

    def __init__(self) -> None:
        # cache: (entity_type, entity_id) -> token, only valid for this request
        self._cache: dict[tuple[str, int], str] = {}

    # ----------------------------------------------------------------------
    # Outbound: payload destined for the LLM
    # ----------------------------------------------------------------------
    async def tokenize_payload(
        self,
        payload: Any,
        *,
        conversation_id: str,
        tenant_id: int,
        role: str,
    ) -> Any:
        """Return a sanitised copy of ``payload`` for non-DIRECCION roles.

        DIRECCION pass-through. Other roles get sku/store/brand IDs replaced
        by opaque tokens. The structure of the payload is preserved.
        """
        if role.lower() == "direccion":
            return payload

        # 1. Collect every (entity_type, entity_id) referenced in the payload.
        refs: dict[str, set[int]] = {"sku": set(), "store": set(), "brand": set()}
        _collect_refs(payload, refs)

        # 2. Resolve / mint tokens for each referenced id.
        await self._ensure_tokens(
            refs, conversation_id=conversation_id, tenant_id=tenant_id
        )

        # 3. Walk the payload again, substituting ids with tokens (deep copy).
        return _substitute(payload, self._cache)

    # ----------------------------------------------------------------------
    # Inbound: replace tokens in Claude's final text with display names.
    # ----------------------------------------------------------------------
    async def detokenize_text(
        self,
        text: str,
        *,
        conversation_id: str,
        role: str,
    ) -> str:
        if role.lower() == "direccion" or not text:
            return text

        from app.db.conversation import load_token_map  # local import to avoid cycle

        mappings = await load_token_map(conversation_id)
        if not mappings:
            return text

        by_token: dict[str, str] = {}
        for m in mappings:
            label = m.get("display_name") or f"{m['entity_type']} {m['entity_id']}"
            by_token[str(m["token"])] = str(label)

        def _replace(match: re.Match[str]) -> str:
            tok = match.group(0)
            return by_token.get(tok, tok)

        return TOKEN_RE.sub(_replace, text)

    # ----------------------------------------------------------------------
    # internals
    # ----------------------------------------------------------------------
    async def _ensure_tokens(
        self,
        refs: dict[str, set[int]],
        *,
        conversation_id: str,
        tenant_id: int,
    ) -> None:
        # Cheap path: every reference already in the local cache.
        missing: dict[str, set[int]] = {"sku": set(), "store": set(), "brand": set()}
        for etype, ids in refs.items():
            for eid in ids:
                if (etype, eid) not in self._cache:
                    missing[etype].add(eid)
        if not any(missing.values()):
            return

        # Query DB for tokens that already exist in this conversation.
        for etype, ids in missing.items():
            for eid in list(ids):
                tok = await find_token_for_entity(
                    conversation_id=conversation_id, entity_type=etype, entity_id=eid
                )
                if tok is not None:
                    self._cache[(etype, eid)] = tok
                    missing[etype].discard(eid)

        if not any(missing.values()):
            return

        # Whatever is still missing is new: fetch display names + persist new tokens.
        names = await fetch_display_names(
            tenant_id,
            sku_ids=list(missing["sku"]),
            store_ids=list(missing["store"]),
            brand_ids=list(missing["brand"]),
        )
        for etype, ids in missing.items():
            for eid in ids:
                token = f"{etype}_{secrets.token_hex(4)}"
                display = names.get((etype, eid))
                await insert_token_mapping(
                    conversation_id=conversation_id,
                    token=token,
                    entity_type=etype,
                    entity_id=eid,
                    display_name=display,
                )
                self._cache[(etype, eid)] = token


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------
def _collect_refs(value: Any, acc: dict[str, set[int]]) -> None:
    """Walk JSON-like structure collecting sensitive ids."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k in SENSITIVE_KEYS and isinstance(v, int):
                acc[SENSITIVE_KEYS[k]].add(v)
            else:
                _collect_refs(v, acc)
    elif isinstance(value, list):
        for item in value:
            _collect_refs(item, acc)


def _substitute(value: Any, cache: dict[tuple[str, int], str]) -> Any:
    """Return a deep-copied version of value with ids replaced by tokens."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k in SENSITIVE_KEYS and isinstance(v, int):
                etype = SENSITIVE_KEYS[k]
                tok = cache.get((etype, v))
                out[k] = tok if tok else v
            else:
                out[k] = _substitute(v, cache)
        return out
    if isinstance(value, list):
        return [_substitute(item, cache) for item in value]
    return value
