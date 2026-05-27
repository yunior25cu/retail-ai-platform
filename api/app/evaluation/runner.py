"""Eval runner: executes the question catalog and produces an EvalRun.

Usage (CLI):
    python -m app.evaluation.cli --tenant 9001 --output eval_run.json

Usage (programmatic):
    run = await EvalRunner(tenant_id=9001).run(CATALOG)
    run = await EvalRunner(tenant_id=9001, client=mock_client).run(CATALOG[:5])
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import anthropic

from app.auth.dependencies import AuthContext
from app.evaluation.catalog import EvalQuestion
from app.llm.orchestrator import run_conversation
from app.llm.prompts import select_prompt


@dataclass
class QuestionResult:
    question_id: str
    role: str
    question: str
    response: str
    tools_invoked: list[str]
    tokens_input: int
    tokens_output: int
    duration_ms: int
    error: str | None
    tool_hit: bool          # at least one expected_tool was invoked
    concept_hits: list[str]  # expected_concepts found in the response


@dataclass
class EvalRun:
    run_id: str
    timestamp: str
    tenant_id: int
    results: list[QuestionResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvalRunner:
    """Runs an eval catalog against the orchestrator.

    Args:
        tenant_id: tenant to run questions against.
        client:    optional injected Anthropic client; uses get_client() if None.
                   Pass a mock client in tests to avoid real API calls.
    """

    def __init__(
        self,
        tenant_id: int,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self._client = client

    async def run(self, catalog: list[EvalQuestion]) -> EvalRun:
        eval_run = EvalRun(
            run_id=str(uuid4()),
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
            tenant_id=self.tenant_id,
        )
        for question in catalog:
            result = await self._run_one(question)
            eval_run.results.append(result)
        return eval_run

    async def _run_one(self, q: EvalQuestion) -> QuestionResult:
        auth = AuthContext(
            tenant_id=self.tenant_id,
            user_id="eval_runner",
            role=q.role,
        )
        t0 = time.perf_counter()
        error: str | None = None
        response = ""
        tools_invoked: list[str] = []
        tokens_input = 0
        tokens_output = 0

        try:
            result = await run_conversation(
                user_message=q.question,
                auth=auth,
                system_prompt=select_prompt(q.role),
                client=self._client,
            )
            response = result.response_text
            tools_invoked = [t.name for t in result.tools_invoked]
            tokens_input = result.tokens_input
            tokens_output = result.tokens_output
        except Exception as exc:  # noqa: BLE001
            error = str(exc)

        duration_ms = int((time.perf_counter() - t0) * 1000)

        tool_hit = bool(
            set(tools_invoked) & set(q.expected_tools)
        )
        concept_hits = [
            c for c in q.expected_concepts
            if c.lower() in response.lower()
        ]

        return QuestionResult(
            question_id=q.id,
            role=q.role,
            question=q.question,
            response=response,
            tools_invoked=tools_invoked,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            duration_ms=duration_ms,
            error=error,
            tool_hit=tool_hit,
            concept_hits=concept_hits,
        )
