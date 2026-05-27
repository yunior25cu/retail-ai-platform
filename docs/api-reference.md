# API Reference

Base URL: `http://localhost:8000` (development) — adapt to your deployment host.

Interactive documentation is available at `/docs` (Swagger UI) and `/redoc` (ReDoc) when the server is running.

---

## Authentication

The API resolves identity in this priority order:

1. **Bearer JWT** — `Authorization: Bearer <token>` header. The token must be a valid HS256 JWT signed with `JWT_SECRET` containing claims `sub`, `tenant_id`, and `role`. Invalid or expired tokens return HTTP 401.

2. **Mock headers** — `X-Mock-User`, `X-Mock-Tenant`, `X-Mock-Role`. Only available when `AUTH_REQUIRE_JWT=false` (default in development). Disabled in production.

3. **Dev defaults** — No headers at all. Falls back to `user_id=dev-user`, `tenant_id=7`, `role=direccion`. Only when `AUTH_REQUIRE_JWT=false`.

Valid roles: `direccion` · `marca` · `tienda` · `sku`

To mint a token for testing:

```bash
cd api
python - <<'EOF'
from app.auth.jwt_handler import create_access_token
print(create_access_token(user_id="alice", tenant_id=7, role="direccion"))
EOF
```

---

## Request headers

| Header | Required | Description |
|---|---|---|
| `Authorization: Bearer <jwt>` | Yes (in prod) | Signed JWT with `sub`, `tenant_id`, `role` claims |
| `Content-Type: application/json` | Yes for POST | JSON request body |
| `X-Mock-User` | No | Mock user ID (dev only, overridden by Bearer) |
| `X-Mock-Tenant` | No | Mock tenant ID as integer (dev only) |
| `X-Mock-Role` | No | Mock role string (dev only) |

---

## Endpoints

### GET /api/v1/conversations/{conversation_id}

Returns metadata for an existing conversation. Tenant-scoped: returns 404 for unknown or foreign-tenant conversations.

**Path parameter**: `conversation_id` — UUID of an existing conversation returned by `POST /api/v1/chat`.

**Response 200**

```json
{
  "conversation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "user_role": "direccion",
  "total_messages": 6,
  "total_turns": 3,
  "memory_turns": 3,
  "recent_messages": [
    {"role": "user",      "text": "¿Cuál es el resumen de la semana?"},
    {"role": "assistant", "text": "Esta semana la facturación fue..."}
  ]
}
```

| Field | Description |
|---|---|
| `total_messages` | Total user+assistant messages persisted |
| `total_turns` | `total_messages / 2` rounded down |
| `memory_turns` | Value of `MEMORY_TURNS_PER_REQUEST` config (how many turns Claude sees) |
| `recent_messages` | Last `memory_turns` turns in chronological order |

**Response 404** — conversation not found or belongs to a different tenant.

---

### GET /api/v1/health

Liveness and DB readiness probe. No authentication required.

**Response 200**

```json
{
  "status": "ok",
  "db_ok": true,
  "db_database": "pymeconta_local",
  "tenant_count": 12
}
```

When the database is unreachable, `status` is `"degraded"` and `db_ok` is `false`.

---

### POST /api/v1/chat

Orchestrated, audited, sanitised conversation endpoint. Accepts a natural-language message, invokes Claude with the appropriate tool subset for the caller's role, and returns the composed answer.

**Request body**

```json
{
  "message": "¿Cuáles son las alertas de alto impacto esta semana?",
  "conversation_id": null
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `message` | `string` | Yes | User question. 1–10 000 characters. |
| `conversation_id` | `string` (UUID) | No | Continue an existing conversation. Must belong to the caller's tenant. Omit to start a new one. |

**Response 200**

```json
{
  "request_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "conversation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "response": "Esta semana hay 3 alertas de impacto alto: ...",
  "tools_used": [
    {"name": "get_active_alerts", "duration_ms": 42, "is_error": false}
  ],
  "iterations": 2,
  "stop_reason": "end_turn",
  "tokens_input": 1840,
  "tokens_output": 312,
  "duration_ms": 2100
}
```

| Field | Type | Description |
|---|---|---|
| `request_id` | UUID string | Unique identifier for this request; use with `get_audit_trail` |
| `conversation_id` | UUID string | Pass back in subsequent requests to continue the conversation |
| `response` | string | Claude's final answer (detokenized for non-direccion roles) |
| `tools_used` | array | Each tool invocation with name, duration, and error flag |
| `iterations` | integer | Number of tool-call rounds used |
| `stop_reason` | string | `end_turn` (normal) or `max_tokens` / `tool_use` (abnormal) |
| `tokens_input` | integer | Input tokens consumed (used for cost and rate-limit accounting) |
| `tokens_output` | integer | Output tokens generated |
| `duration_ms` | integer | Total wall-clock time for this request |

---

## Error responses

All errors follow FastAPI's default structure:

```json
{"detail": "<string or object>"}
```

### 400 Bad Request

```json
{"detail": "invalid_role: admin"}
```

Returned when a mock `X-Mock-Role` header contains an unrecognised role string.

### 401 Unauthorized

```json
{
  "detail": "invalid_token: Signature has expired."
}
```

Also returned for:
- Malformed Bearer token
- Missing `tenant_id` / `role` claims
- `missing_bearer_token` when `AUTH_REQUIRE_JWT=true` and no Bearer header is present

The response also carries `WWW-Authenticate: Bearer` header.

### 403 Forbidden

```json
{"detail": "forbidden_for_role"}
```

Returned when Claude attempts to call a tool that the caller's role is not allowed to use (e.g., `get_audit_trail` for a `marca` user). This should not normally reach the client — the tool is filtered from Claude's tool list before the call.

### 404 Not Found

```json
{"detail": "conversation_not_found_for_tenant"}
```

Returned when `conversation_id` in the request body does not belong to the caller's tenant.

### 422 Unprocessable Entity

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "message"],
      "msg": "String should have at least 1 character",
      "input": ""
    }
  ]
}
```

Returned by FastAPI when request body fails Pydantic validation (missing required fields, wrong types, constraint violations).

### 429 Too Many Requests

```json
{
  "detail": {
    "scope": "tenant",
    "message": "tenant 7 exceeded 100/h"
  }
}
```

`scope` is one of:

| Scope | Trigger |
|---|---|
| `tenant` | Tenant exceeded `RATE_LIMIT_TENANT_HOUR` requests in the last hour |
| `user` | User exceeded `RATE_LIMIT_USER_HOUR` requests in the last hour |
| `tokens` | Tenant exceeded `RATE_LIMIT_TOKENS_DAY` tokens in the last 24 hours |

### 500 Internal Server Error

```json
{"detail": "internal_error"}
```

Unexpected server-side exception. The failure is written to `api_audit.ai_audit_log` with `status=ERROR` before the 500 is returned. Check `LOG_JSON` output or the audit table for details.

### 503 Service Unavailable

```json
{"detail": "ANTHROPIC_API_KEY not set or is a placeholder."}
```

Returned when the Anthropic API key is missing or set to its placeholder value. Also covers other configuration errors detected during the orchestrator call.

---

## Data sanitization (non-`direccion` roles)

For roles other than `direccion`, the sanitizer replaces sensitive entity IDs before sending data to Claude:

| Field | Replaced with |
|---|---|
| `sku_id` | `sku_<hex8>` (e.g. `sku_3a7f1b2c`) |
| `store_id` | `store_<hex8>` |
| `brand_id` | `brand_<hex8>` |

The token map is persisted per conversation in `api_audit.conversation_token_map`. The same entity always gets the same token within one conversation. Tokens are resolved back to display names (from `gold.dim_sku`, `gold.dim_store`, etc.) before the final response is returned to the caller.

`direction` users always receive raw numeric IDs. The `get_audit_trail` tool is restricted to `direccion` only.

---

## Audit trail

Every `/chat` request — success or failure — writes a row to `api_audit.ai_audit_log`. The `request_id` in the chat response is the primary key of that row. A `direccion` user can retrieve it via the `get_audit_trail` tool in a follow-up conversation:

```
POST /api/v1/chat
{"message": "Dame el audit trail del request 3fa85f64-5717-..."}
```

Claude will invoke `get_audit_trail(request_id="3fa85f64-...")` and return the full record, including tools invoked, token usage, cost in USD, and the user question.

Direct SQL access:

```sql
SELECT request_id, user_id, user_role, status, cost_usd, tokens_input, tokens_output,
       tools_invoked, error_msg, created_at
  FROM api_audit.ai_audit_log
 WHERE tenant_id = 7
 ORDER BY created_at DESC;
```
