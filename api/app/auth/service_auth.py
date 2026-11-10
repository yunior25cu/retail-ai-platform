"""Service-to-service auth dependency for internal endpoints.

Called by ERP backends (e.g. .NET Balaxys AiAssistantController) that
have already authenticated the end-user and forward identity via trusted
internal headers.  The ERP proves its identity with a shared SERVICE_KEY;
user identity travels via X-Tenant-Id / X-User-Id / X-User-Role.

Python never validates a user JWT in this path — .NET owns that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from fastapi import HTTPException, Request, status

from app.config import settings

VALID_ROLES = {
    # retail vertical
    "direccion", "marca", "tienda", "sku",
    # produccion vertical
    "produccion", "compras",
    # admin roles (both verticals)
    "admin_tenant", "superadmin", "super_admin",
}


@dataclass(frozen=True)
class ServiceAuthContext:
    """Identity resolved from X-* service headers OR Bearer JWT.

    user_id is str so it can hold both integer ERP user IDs (Balaxys path)
    and UUID sub claims (standalone JWT path). Audit log uses it as-is.
    """

    tenant_id: int
    user_id: str       # ERP int-as-string OR JWT UUID sub
    role: str          # direccion | marca | tienda | sku | produccion
    conversation_id: str | None
    request_id: str    # generated if caller omits X-Request-Id
    # Token MCP de vida corta del ERP (X-Balaxys-Mcp-Token): habilita las tools
    # ERP de Balaxys en este mensaje. Solo por la ruta X-Service-Key (ERP proxy).
    # Nunca se loguea: repr=False.
    mcp_token: str | None = field(default=None, repr=False)


async def get_service_auth_context(request: Request) -> ServiceAuthContext:
    """FastAPI dependency for POST /api/v1/internal/chat and /suggestions.

    Resolution order:
        1. Authorization: Bearer <jwt>  → standalone product path (no ERP proxy)
        2. X-Service-Key + X-Tenant-Id  → Balaxys ERP proxy path (unchanged)

    Raises:
        401  if neither auth method is present or valid
        400  if required X-* headers are missing in the service-key path
        503  if SERVICE_KEY is not configured and JWT path fails
    """
    # ── JWT path (standalone React product) ──────────────────────────────
    # If a valid Bearer JWT is present, use it without X-Service-Key.
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        from app.auth.service import decode_access_token as _decode_jwt
        claims = _decode_jwt(auth_header[7:].strip())
        if claims:
            role = str(claims.get("role", "sku")).lower()
            if role not in VALID_ROLES:
                role = "sku"
            return ServiceAuthContext(
                tenant_id=int(claims["tenant_id"]),
                user_id=str(claims["sub"]),
                role=role,
                conversation_id=request.headers.get("X-Conversation-Id") or None,
                request_id=request.headers.get("X-Request-Id") or str(uuid4()),
            )

    # ── X-Service-Key path (Balaxys ERP proxy — unchanged) ───────────────
    if not settings.service_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SERVICE_KEY not configured on this server",
        )

    provided_key = request.headers.get("X-Service-Key", "")
    if not provided_key or provided_key != settings.service_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service key",
        )

    tenant_id_str = request.headers.get("X-Tenant-Id", "").strip()
    if not tenant_id_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required header: X-Tenant-Id",
        )
    try:
        tenant_id = int(tenant_id_str)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-Id must be an integer",
        ) from e

    user_id_str = request.headers.get("X-User-Id", "").strip()
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required header: X-User-Id",
        )

    role = (request.headers.get("X-User-Role") or "sku").lower()
    if role not in VALID_ROLES:
        role = "sku"

    conversation_id = request.headers.get("X-Conversation-Id") or None
    request_id = request.headers.get("X-Request-Id") or str(uuid4())

    return ServiceAuthContext(
        tenant_id=tenant_id,
        user_id=user_id_str,
        role=role,
        conversation_id=conversation_id,
        request_id=request_id,
        mcp_token=(request.headers.get("X-Balaxys-Mcp-Token") or "").strip() or None,
    )
