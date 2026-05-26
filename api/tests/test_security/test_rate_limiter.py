"""RateLimiter unit tests + endpoint-level 429 behaviour."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.llm.orchestrator import ConversationResult
from app.security.rate_limiter import RateLimiter, RateLimitExceeded


def test_tenant_quota_blocks_after_threshold() -> None:
    rl = RateLimiter(tenant_per_hour=3, user_per_hour=1000, tokens_per_day_per_tenant=100_000)
    for _ in range(3):
        rl.check_and_record_request(tenant_id=1, user_id="u")
    with pytest.raises(RateLimitExceeded) as exc:
        rl.check_and_record_request(tenant_id=1, user_id="u")
    assert exc.value.scope == "tenant"


def test_user_quota_blocks_after_threshold() -> None:
    rl = RateLimiter(tenant_per_hour=1000, user_per_hour=2, tokens_per_day_per_tenant=100_000)
    rl.check_and_record_request(tenant_id=1, user_id="a")
    rl.check_and_record_request(tenant_id=1, user_id="a")
    with pytest.raises(RateLimitExceeded) as exc:
        rl.check_and_record_request(tenant_id=1, user_id="a")
    assert exc.value.scope == "user"
    # Another user under the same tenant is unaffected.
    rl.check_and_record_request(tenant_id=1, user_id="b")


def test_token_budget_blocks_when_exhausted() -> None:
    rl = RateLimiter(tokens_per_day_per_tenant=1000)
    rl.record_tokens(tenant_id=5, tokens=600)
    rl.check_token_budget(tenant_id=5)  # still under
    rl.record_tokens(tenant_id=5, tokens=500)  # now 1100, over
    with pytest.raises(RateLimitExceeded) as exc:
        rl.check_token_budget(tenant_id=5)
    assert exc.value.scope == "tokens"


def test_snapshot_returns_current_usage() -> None:
    rl = RateLimiter()
    rl.check_and_record_request(tenant_id=42, user_id="z")
    rl.record_tokens(tenant_id=42, tokens=123)
    snap = rl.snapshot(42)
    assert snap == {"requests_last_hour": 1, "tokens_last_day": 123}


def test_reset_clears_state() -> None:
    rl = RateLimiter(tenant_per_hour=1)
    rl.check_and_record_request(tenant_id=1, user_id="u")
    rl.reset()
    rl.check_and_record_request(tenant_id=1, user_id="u")  # no longer raises


# ---------------------------------------------------------------------------
# Endpoint-level: 429 after exceeding tenant quota.
# ---------------------------------------------------------------------------

def test_chat_endpoint_returns_429_when_tenant_quota_exceeded(
    client: TestClient, monkeypatch
) -> None:
    # Force a tiny quota at the module-level singleton.
    from app.security import rate_limiter as rl_mod

    monkeypatch.setattr(rl_mod.limiter, "tenant_per_hour", 1)
    rl_mod.limiter.reset()  # also done by the autouse fixture; explicit for clarity

    async def fake_run(**kwargs):  # noqa: ANN001, ARG001
        return ConversationResult(
            request_id="r-rl", response_text="ok", iterations=1, stop_reason="end_turn"
        )

    monkeypatch.setattr("app.api.v1.chat.run_conversation", fake_run)

    # First call: allowed
    resp1 = client.post("/api/v1/chat", json={"message": "first"})
    assert resp1.status_code == 200

    # Second call: 429
    resp2 = client.post("/api/v1/chat", json={"message": "second"})
    assert resp2.status_code == 429
    detail = resp2.json()["detail"]
    assert detail["scope"] == "tenant"
