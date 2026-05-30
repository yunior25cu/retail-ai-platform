"""POST /api/v1/internal/chat — service-to-service endpoint.

Called exclusively by ERP backends (e.g. .NET AiAssistantController) that
have already authenticated the end-user and forward the resolved identity via
X-Service-Key / X-Tenant-Id / X-User-Id / X-User-Role headers.

This endpoint mirrors the /api/v1/chat flow but uses ServiceAuthContext
instead of the Bearer-JWT / mock path.  The conversation_id may arrive
either from the X-Conversation-Id header (priority) or the request body.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.audit.persister import persist_audit_row
from app.auth.dependencies import AuthContext
from app.auth.service_auth import ServiceAuthContext, get_service_auth_context
from app.config import settings
from app.db.conversation import (
    append_message,
    create_conversation,
    load_conversation,
    load_recent_messages,
    touch_conversation,
)
from app.db.conversation import fetch_conversation_messages_for_history, fetch_conversations
from app.db.feedback import insert_feedback
from app.db.queries import (
    fetch_active_alerts,
    fetch_metrics_aggregates,
    fetch_metrics_by_day,
    fetch_metrics_by_role,
    fetch_metrics_longest_conversation_turns,
    fetch_metrics_tools_invoked,
)
from app.db.tenant_config import (
    get_monthly_spend_usd,
    get_tenant_config,
    update_tenant_config,
)
from app.llm.claude_client import get_client
from app.llm.orchestrator import run_conversation
from app.llm.prompts import select_prompt
from app.security.rate_limiter import RateLimitExceeded, limiter
from app.security.sanitizer import Sanitizer

router = APIRouter(prefix="/internal", tags=["internal"])
log = structlog.get_logger(__name__)


class InternalChatRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=10_000,
        description="Natural-language question. 1–10 000 characters.",
    )
    conversation_id: str | None = Field(
        default=None,
        description=(
            "UUID of an existing conversation. "
            "Overridden by X-Conversation-Id header if both are present."
        ),
    )


class InternalChatResponse(BaseModel):
    response: str = Field(description="Claude's answer in markdown.")
    conversation_id: str = Field(description="Pass back on the next turn.")
    request_id: str = Field(description="Echoes X-Request-Id (or generated UUID).")
    tools_used: list[str] = Field(description="Names of Gold tools invoked.")
    tokens_input: int
    tokens_output: int
    duration_ms: int


@router.post(
    "/chat",
    response_model=InternalChatResponse,
    summary="Internal chat (service-to-service)",
    description=(
        "Same orchestration flow as /api/v1/chat but authenticated via "
        "X-Service-Key instead of Bearer JWT. Intended for ERP proxy calls only — "
        "never expose this endpoint to the public internet."
    ),
    responses={
        401: {"description": "Missing or invalid X-Service-Key"},
        400: {"description": "Missing X-Tenant-Id or X-User-Id"},
        429: {"description": "Rate limit exceeded"},
        503: {"description": "SERVICE_KEY not configured or Anthropic key missing"},
    },
)
async def internal_chat(
    payload: InternalChatRequest,
    svc: Annotated[ServiceAuthContext, Depends(get_service_auth_context)],
) -> InternalChatResponse:
    t0 = time.perf_counter()

    # Convert to AuthContext (compatible with orchestrator and all downstream helpers)
    auth = AuthContext(
        user_id=str(svc.user_id),
        tenant_id=svc.tenant_id,
        role=svc.role,
    )

    # Per-tenant configuration (cached 5 min). Memory turns, per-role rate
    # limit and monthly budget are all derived from this single read.
    cfg = await get_tenant_config(auth.tenant_id)

    # Monthly budget gate — 0 means unlimited. Check BEFORE the limiter so
    # an over-budget tenant gets a clear domain error, not a generic 429.
    if cfg.monthly_budget_usd > 0:
        spent = await get_monthly_spend_usd(auth.tenant_id)
        if spent >= cfg.monthly_budget_usd:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "scope": "budget",
                    "error": "BUDGET_EXCEEDED",
                    "message": (
                        "El presupuesto mensual del asistente fue alcanzado. "
                        "Contactá al administrador."
                    ),
                    "spent_usd": round(spent, 4),
                    "budget_usd": cfg.monthly_budget_usd,
                },
            )

    # Rate limiting — tenant cap unchanged; per-user cap now comes from
    # the per-role config (cfg.rate_limit_for_role).
    try:
        limiter.check_and_record_request(
            auth.tenant_id,
            auth.user_id,
            user_per_hour_override=cfg.rate_limit_for_role(auth.role),
        )
        limiter.check_token_budget(auth.tenant_id)
    except RateLimitExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"scope": e.scope, "message": e.detail},
        ) from e

    system_prompt = select_prompt(auth.role)

    # Conversation: X-Conversation-Id header takes priority over body field
    conv_requested = svc.conversation_id or payload.conversation_id
    conv_id = await _resolve_conversation(conv_requested, auth)

    history = await load_recent_messages(
        conv_id, tenant_id=auth.tenant_id, turns=cfg.memory_turns,
    )
    sanitizer = Sanitizer()

    try:
        result = await run_conversation(
            user_message=payload.message,
            auth=auth,
            history=history,
            system_prompt=system_prompt,
            sanitizer=sanitizer,
            conversation_id=conv_id,
        )
    except RuntimeError as e:
        duration = int((time.perf_counter() - t0) * 1000)
        await _persist_failure_audit(
            conv_id, auth, payload.message, str(e), duration,
            request_id=svc.request_id, system_prompt=system_prompt,
        )
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        duration = int((time.perf_counter() - t0) * 1000)
        await _persist_failure_audit(
            conv_id, auth, payload.message, str(e), duration,
            request_id=svc.request_id, system_prompt=system_prompt,
        )
        raise HTTPException(status_code=500, detail="internal_error") from e

    await append_message(conversation_id=conv_id, role="user", content=payload.message)
    await append_message(
        conversation_id=conv_id, role="assistant", content=result.response_text
    )
    await touch_conversation(conv_id)

    audit_status = (
        "PARTIAL"
        if result.stop_reason and result.stop_reason != "end_turn"
        else "SUCCESS"
    )
    await persist_audit_row(
        request_id=svc.request_id,
        conversation_id=conv_id,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        user_role=auth.role,
        user_question=payload.message,
        system_prompt=system_prompt,
        tools_invoked=result.tools_invoked,
        final_response=result.response_text,
        tokens_input=result.tokens_input,
        tokens_output=result.tokens_output,
        duration_ms=result.duration_ms,
        status=audit_status,
        error_msg=None,
    )

    limiter.record_tokens(auth.tenant_id, result.tokens_input + result.tokens_output)

    final_text = await sanitizer.detokenize_text(
        result.response_text, conversation_id=conv_id, role=auth.role
    )

    return InternalChatResponse(
        response=final_text,
        conversation_id=conv_id,
        request_id=svc.request_id,
        tools_used=[t.name for t in result.tools_invoked],
        tokens_input=result.tokens_input,
        tokens_output=result.tokens_output,
        duration_ms=result.duration_ms,
    )


# ---------------------------------------------------------------------------
# Helpers (mirrors chat.py — kept private to avoid coupling)
# ---------------------------------------------------------------------------

async def _resolve_conversation(conv_id: str | None, auth: AuthContext) -> str:
    if conv_id:
        existing = await load_conversation(conv_id, tenant_id=auth.tenant_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="conversation_not_found_for_tenant",
            )
        return str(existing["conversation_id"])
    return await create_conversation(
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        user_role=auth.role,
    )


async def _persist_failure_audit(
    conv_id: str | None,
    auth: AuthContext,
    user_question: str,
    error: str,
    duration_ms: int,
    *,
    request_id: str,
    system_prompt: str,
) -> None:
    await persist_audit_row(
        request_id=request_id,
        conversation_id=conv_id,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        user_role=auth.role,
        user_question=user_question,
        system_prompt=system_prompt,
        tools_invoked=None,
        final_response=None,
        tokens_input=0,
        tokens_output=0,
        duration_ms=duration_ms,
        status="ERROR",
        error_msg=error,
    )


# ---------------------------------------------------------------------------
# GET /suggestions — contextual question suggestions (cached, per tenant+role)
# ---------------------------------------------------------------------------

_SUGGESTIONS_CACHE: dict[str, tuple[float, list[str]]] = {}
_SUGGESTIONS_TTL = 3600  # seconds

# Per-role intent descriptions injected into the Claude prompt so the model
# understands the user's scope, horizon, and what kinds of questions are
# legitimate for that role. Without this, every role gets nearly identical
# suggestions because the prompt only had the bare role name.
_ROLE_INTENT: dict[str, str] = {
    "direccion":
        "gerente general que piensa en patrones sistémicos, "
        "causa raíz y decisiones de política para TODO el negocio, "
        "con horizonte mensual. NUNCA pregunta cosas operativas "
        "de una sola tienda ni de un producto puntual.",
    "marca":
        "gerente de marca que analiza SU marca a través de todas "
        "las tiendas, compara contra plan y planifica transferencias "
        "entre sucursales, con horizonte semanal.",
    "tienda":
        "encargado de UNA tienda que necesita saber qué hacer HOY "
        "en su local: qué reponer, qué transferir, qué liquidar. "
        "Horizonte diario y operativo, solo su tienda.",
    "sku":
        "analista que decide sobre UN producto específico: su "
        "descuento, su rotación, su cobertura, en qué tienda rota "
        "mejor. Preguntas puntuales sobre un SKU.",
}

# Per-role fallback suggestions used when Claude fails or returns <3 lines.
# A single shared fallback was misleading — "¿Qué tiendas tienen mayor impacto?"
# is nonsense for a single-store user.
_FALLBACK_BY_ROLE: dict[str, list[str]] = {
    "direccion": [
        "¿Cómo venimos vs plan este mes?",
        "¿Cuál es la alerta de mayor impacto?",
        "¿Qué decisión urgente requiere mi atención?",
    ],
    "marca": [
        "¿Qué tiendas rinden bajo el promedio?",
        "¿Dónde conviene redistribuir mi marca?",
        "¿Qué productos están sobrestockeados?",
    ],
    "tienda": [
        "¿Qué productos repongo hoy?",
        "¿Qué transfiero a otras sucursales?",
        "¿Qué conviene liquidar esta semana?",
    ],
    "sku": [
        "¿Cómo está rotando este producto?",
        "¿En qué tienda rota mejor este SKU?",
        "¿Qué descuento acelera su venta?",
    ],
}

_SUGGESTIONS_SYSTEM = (
    "Sos un asistente de retail. Generá exactamente 3 preguntas "
    "cortas (máx 60 chars cada una) que haría un {intent} "
    "Contexto actual del negocio: {context}. "
    "Las preguntas DEBEN reflejar el horizonte y alcance descritos. "
    "Solo las 3 preguntas, sin numeración, separadas por newline."
)


class SuggestionsResponse(BaseModel):
    suggestions: list[str] = Field(
        description="3 contextual questions tailored to the user's role and active alerts.",
    )


@router.get(
    "/suggestions",
    response_model=SuggestionsResponse,
    summary="Contextual question suggestions (service-to-service)",
    description=(
        "Returns 3 short, role-aware questions generated by Claude from the tenant's "
        "active alert context. Results are cached in-process for 1 hour per tenant+role. "
        "On any Claude failure the endpoint returns static fallback suggestions — the "
        "caller always receives a valid response."
    ),
    responses={
        401: {"description": "Missing or invalid X-Service-Key"},
        400: {"description": "Missing X-Tenant-Id"},
        503: {"description": "SERVICE_KEY not configured"},
    },
)
async def get_suggestions(
    svc: Annotated[ServiceAuthContext, Depends(get_service_auth_context)],
) -> SuggestionsResponse:
    # Tenant-level kill switch: when suggestions_enabled = false we skip
    # both the Claude call AND the cache lookup, returning the role-specific
    # static fallback. The cache is by-passed deliberately — a tenant that
    # re-enables the toggle should see fresh, generated suggestions on the
    # next request, not whatever happened to be cached.
    cfg = await get_tenant_config(svc.tenant_id)
    if not cfg.suggestions_enabled:
        log.info("suggestions.disabled", tenant_id=svc.tenant_id, role=svc.role)
        fallback = _FALLBACK_BY_ROLE.get(svc.role, _FALLBACK_BY_ROLE["sku"])
        return SuggestionsResponse(suggestions=list(fallback))

    cache_key = f"{svc.tenant_id}:{svc.role}"
    now = time.time()
    cached = _SUGGESTIONS_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _SUGGESTIONS_TTL:
        log.info("suggestions.cache_hit", tenant_id=svc.tenant_id, role=svc.role)
        return SuggestionsResponse(suggestions=cached[1])

    suggestions = await _generate_suggestions(svc.tenant_id, svc.role)
    _SUGGESTIONS_CACHE[cache_key] = (now, suggestions)
    return SuggestionsResponse(suggestions=suggestions)


async def _generate_suggestions(tenant_id: int, role: str) -> list[str]:
    """Call Claude with a compact alert summary to produce 3 tailored questions.

    Falls back to the role-specific list in _FALLBACK_BY_ROLE on any error
    (DB or Anthropic). Unknown roles default to the 'sku' fallback.
    """
    intent = _ROLE_INTENT.get(role, _ROLE_INTENT["sku"])
    role_fallback = _FALLBACK_BY_ROLE.get(role, _FALLBACK_BY_ROLE["sku"])

    context = ""
    try:
        alerts = await fetch_active_alerts(tenant_id, limit=3)
        if alerts:
            parts = [
                f"{a.get('alert_type', '?')} en "
                f"{a.get('store_name') or 'tienda desconocida'} "
                f"(impacto ${a.get('estimated_impact_usd') or 0:.0f})"
                for a in alerts
            ]
            context = "; ".join(parts)
    except Exception:  # noqa: BLE001
        log.warning("suggestions.alerts_fetch_failed", tenant_id=tenant_id)

    if not context:
        context = "sin alertas activas disponibles"

    prompt = _SUGGESTIONS_SYSTEM.format(intent=intent, context=context)
    try:
        client = get_client()
        msg = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text if msg.content else ""
        lines = [ln.strip() for ln in raw.split("\n") if ln.strip()][:3]
        if len(lines) < 3:
            lines = (lines + role_fallback)[:3]
        log.info(
            "suggestions.generated",
            tenant_id=tenant_id,
            role=role,
            count=len(lines),
        )
        return lines
    except Exception:  # noqa: BLE001
        log.warning("suggestions.claude_failed", tenant_id=tenant_id, role=role)
        return list(role_fallback)


# ---------------------------------------------------------------------------
# GET /conversations — last 20 conversations for the authenticated user
# ---------------------------------------------------------------------------

class ConversationSummary(BaseModel):
    conversation_id: str
    title: str
    last_message_at: str | None
    message_count: int


@router.get(
    "/conversations",
    response_model=list[ConversationSummary],
    summary="List conversations (service-to-service)",
    description=(
        "Returns the 20 most recent conversations for the user identified by "
        "X-Tenant-Id + X-User-Id.  Tenant and user isolation are enforced by the "
        "WHERE clause — a user can only see their own conversations."
    ),
    responses={
        401: {"description": "Missing or invalid X-Service-Key"},
        400: {"description": "Missing X-Tenant-Id or X-User-Id"},
        503: {"description": "SERVICE_KEY not configured"},
    },
)
async def get_conversations(
    svc: Annotated[ServiceAuthContext, Depends(get_service_auth_context)],
) -> list[ConversationSummary]:
    rows = await fetch_conversations(svc.tenant_id, svc.user_id)
    return [ConversationSummary(**r) for r in rows]


# ---------------------------------------------------------------------------
# GET /conversations/{conversation_id}/messages — full message history
# ---------------------------------------------------------------------------

class ConversationMessageItem(BaseModel):
    role: str
    content: str
    tools_used: list[str] | None = None
    duration_ms: int | None = None
    created_at: str


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[ConversationMessageItem],
    summary="Conversation message history (service-to-service)",
    description=(
        "Returns all messages for a conversation in chronological order. "
        "Validates that the conversation belongs to the tenant in X-Tenant-Id — "
        "cross-tenant access returns 404."
    ),
    responses={
        401: {"description": "Missing or invalid X-Service-Key"},
        404: {"description": "Conversation not found or belongs to a different tenant"},
        503: {"description": "SERVICE_KEY not configured"},
    },
)
async def get_conversation_messages(
    conversation_id: str,
    svc: Annotated[ServiceAuthContext, Depends(get_service_auth_context)],
) -> list[ConversationMessageItem]:
    # Validate tenant ownership before returning any messages
    existing = await load_conversation(conversation_id, tenant_id=svc.tenant_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="conversation_not_found_for_tenant",
        )
    rows = await fetch_conversation_messages_for_history(conversation_id, svc.tenant_id)
    return [ConversationMessageItem(**r) for r in rows]


# ---------------------------------------------------------------------------
# POST /feedback — persist a thumbs-up / thumbs-down rating
# ---------------------------------------------------------------------------

_VALID_RATINGS = frozenset({"positive", "negative"})


class FeedbackRequest(BaseModel):
    request_id: str = Field(..., description="UUID from the AiChatResponseDto.requestId field.")
    rating: str = Field(..., description="'positive' or 'negative'.")
    comment: str | None = Field(default=None, max_length=500)


class FeedbackResponse(BaseModel):
    ok: bool


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    summary="Submit response feedback (service-to-service)",
    description=(
        "Persists a user rating (thumbs up/down) for a specific AI response. "
        "One rating per request_id is expected but not enforced at the DB level "
        "— duplicates from retry scenarios are acceptable."
    ),
    responses={
        400: {"description": "Invalid rating value or missing fields"},
        401: {"description": "Missing or invalid X-Service-Key"},
        503: {"description": "SERVICE_KEY not configured"},
    },
)
async def submit_feedback(
    payload: FeedbackRequest,
    svc: Annotated[ServiceAuthContext, Depends(get_service_auth_context)],
) -> FeedbackResponse:
    if payload.rating not in _VALID_RATINGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid rating '{payload.rating}'. Must be 'positive' or 'negative'.",
        )
    await insert_feedback(
        tenant_id=svc.tenant_id,
        user_id=svc.user_id,
        request_id=payload.request_id,
        rating=payload.rating,
        comment=payload.comment,
    )
    log.info(
        "feedback.submitted",
        tenant_id=svc.tenant_id,
        user_id=svc.user_id,
        request_id=payload.request_id,
        rating=payload.rating,
    )
    return FeedbackResponse(ok=True)


# ---------------------------------------------------------------------------
# GET /metrics — director-only usage panel (sub-phase 6.6)
# ---------------------------------------------------------------------------

_METRICS_CACHE: dict[int, tuple[float, "MetricsResponse"]] = {}
_METRICS_TTL = 300  # 5 minutes — fresh enough to feel live, cheap enough to skip the DB hammer.


class MetricsResponse(BaseModel):
    period: str = Field(description="ISO month: 'YYYY-MM'.")
    total_queries: int
    total_cost_usd: float
    active_users: int
    top_tool: str
    top_tool_count: int
    longest_conversation_turns: int
    avg_duration_ms: int
    queries_by_role: dict[str, int]
    queries_by_day: list[dict[str, Any]]


def _current_month_window() -> tuple[str, str, str]:
    """Returns (period_label, start_iso, end_iso) for the current UTC month."""
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    period = now.strftime("%Y-%m")
    return period, start.isoformat(), end.isoformat()


def _top_tool_from_invocations(raw_json_rows: list[str]) -> tuple[str, int]:
    """Parses each tools_invoked JSON array and counts tool names across all rows."""
    counter: Counter[str] = Counter()
    for raw in raw_json_rows:
        try:
            tools = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(tools, list):
            continue
        for entry in tools:
            # Each entry can be a string name or a dict with 'name' (the audit
            # writer has used both shapes across releases). Handle both.
            if isinstance(entry, str):
                counter[entry] += 1
            elif isinstance(entry, dict):
                name = entry.get("name") or entry.get("tool")
                if isinstance(name, str):
                    counter[name] += 1
    if not counter:
        return "", 0
    name, count = counter.most_common(1)[0]
    return name, count


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="Tenant usage metrics for the current UTC month",
    description=(
        "Aggregated AI Assistant usage for the caller's tenant: query counts, "
        "cost, active users, top tool, queries by role and by day. Cached "
        "in-process for 5 minutes. Authorization at the .NET layer restricts "
        "this endpoint to users with the ai.assistant.director capability."
    ),
    responses={
        401: {"description": "Missing or invalid X-Service-Key"},
        400: {"description": "Missing X-Tenant-Id"},
        503: {"description": "SERVICE_KEY not configured"},
    },
)
async def get_metrics(
    svc: Annotated[ServiceAuthContext, Depends(get_service_auth_context)],
) -> MetricsResponse:
    now = time.time()
    cached = _METRICS_CACHE.get(svc.tenant_id)
    if cached and (now - cached[0]) < _METRICS_TTL:
        log.info("metrics.cache_hit", tenant_id=svc.tenant_id)
        return cached[1]

    period, start_iso, end_iso = _current_month_window()
    aggs = await fetch_metrics_aggregates(svc.tenant_id, start_iso, end_iso)
    tool_jsons = await fetch_metrics_tools_invoked(svc.tenant_id, start_iso, end_iso)
    by_role_rows = await fetch_metrics_by_role(svc.tenant_id, start_iso, end_iso)
    by_day_rows = await fetch_metrics_by_day(svc.tenant_id, start_iso, end_iso)
    longest = await fetch_metrics_longest_conversation_turns(
        svc.tenant_id, start_iso, end_iso
    )

    top_tool, top_tool_count = _top_tool_from_invocations(tool_jsons)

    response = MetricsResponse(
        period=period,
        total_queries=int(aggs["total_queries"] or 0),
        total_cost_usd=round(float(aggs["total_cost_usd"] or 0.0), 4),
        active_users=int(aggs["active_users"] or 0),
        top_tool=top_tool,
        top_tool_count=top_tool_count,
        longest_conversation_turns=longest,
        avg_duration_ms=int(aggs["avg_duration_ms"] or 0),
        queries_by_role={r["user_role"]: int(r["cnt"]) for r in by_role_rows},
        queries_by_day=[
            {"date": r["date"], "count": int(r["cnt"])} for r in by_day_rows
        ],
    )

    _METRICS_CACHE[svc.tenant_id] = (now, response)
    return response


# ---------------------------------------------------------------------------
# /config — director-only tenant settings (sub-phase 6.7)
# ---------------------------------------------------------------------------

_ALLOWED_MEMORY_TURNS = frozenset({3, 5, 10})
_ALLOWED_BUDGET_ALERT_PCT = frozenset({50, 80, 100})
_RATE_LIMIT_MIN = 1
_RATE_LIMIT_MAX = 200
_RATE_LIMIT_KEYS = frozenset(
    {"rate_limit_director", "rate_limit_marca",
     "rate_limit_tienda", "rate_limit_producto"}
)


class TenantConfigResponse(BaseModel):
    memory_turns: int
    monthly_budget_usd: float
    budget_alert_pct: int
    rate_limit_director: int
    rate_limit_marca: int
    rate_limit_tienda: int
    rate_limit_producto: int
    suggestions_enabled: bool
    current_spend_usd: float = Field(
        description="Sum of cost_usd for SUCCESS audit rows in the current "
                    "UTC month. Used by the UI to render the spend bar."
    )


class UpdateConfigRequest(BaseModel):
    key: str
    value: str


def _validate_config_value(key: str, value: str) -> None:
    """Raise HTTPException(422) on invalid value for ``key``. The PATCH
    handler is the only place that rejects bad input — the underlying
    update_tenant_config helper trusts its caller."""
    try:
        if key == "memory_turns":
            if int(value) not in _ALLOWED_MEMORY_TURNS:
                raise ValueError
        elif key == "monthly_budget_usd":
            if float(value) < 0:
                raise ValueError
        elif key == "budget_alert_pct":
            if int(value) not in _ALLOWED_BUDGET_ALERT_PCT:
                raise ValueError
        elif key in _RATE_LIMIT_KEYS:
            v = int(value)
            if not (_RATE_LIMIT_MIN <= v <= _RATE_LIMIT_MAX):
                raise ValueError
        elif key == "suggestions_enabled":
            if value.lower() not in ("true", "false"):
                raise ValueError
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"config_key '{key}' no permitida",
            )
    except (TypeError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Valor inválido para '{key}': {value!r}",
        ) from e


@router.get(
    "/config",
    response_model=TenantConfigResponse,
    summary="Tenant AI settings (director-only at the .NET layer)",
)
async def get_config(
    svc: Annotated[ServiceAuthContext, Depends(get_service_auth_context)],
) -> TenantConfigResponse:
    cfg = await get_tenant_config(svc.tenant_id)
    spent = await get_monthly_spend_usd(svc.tenant_id)
    return TenantConfigResponse(
        memory_turns=cfg.memory_turns,
        monthly_budget_usd=cfg.monthly_budget_usd,
        budget_alert_pct=cfg.budget_alert_pct,
        rate_limit_director=cfg.rate_limit_director,
        rate_limit_marca=cfg.rate_limit_marca,
        rate_limit_tienda=cfg.rate_limit_tienda,
        rate_limit_producto=cfg.rate_limit_producto,
        suggestions_enabled=cfg.suggestions_enabled,
        current_spend_usd=round(spent, 4),
    )


@router.put(
    "/config",
    response_model=dict[str, Any],
    summary="Update one tenant AI setting",
    description=(
        "Single-key update. Validates value shape against the key's "
        "constraints (memory_turns ∈ {3,5,10}, budget_alert_pct ∈ "
        "{50,80,100}, rate_limit_* ∈ [1,200], suggestions_enabled ∈ "
        "{true,false}, monthly_budget_usd ≥ 0)."
    ),
)
async def update_config(
    payload: UpdateConfigRequest,
    svc: Annotated[ServiceAuthContext, Depends(get_service_auth_context)],
) -> dict[str, Any]:
    _validate_config_value(payload.key, payload.value)
    try:
        await update_tenant_config(
            tenant_id=svc.tenant_id,
            key=payload.key,
            value=payload.value,
            updated_by=svc.user_id,
        )
    except ValueError as e:
        # update_tenant_config raises on unknown keys, but _validate_config_value
        # should have caught those first. Mirror the validator's HTTP shape so
        # the .NET proxy maps it consistently.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    log.info(
        "config.updated",
        tenant_id=svc.tenant_id, key=payload.key, value=payload.value,
    )
    return {"ok": True, "key": payload.key, "value": payload.value}
