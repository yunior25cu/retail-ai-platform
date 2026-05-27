"""Service-to-service auth dependency for internal endpoints.

Called by ERP backends (e.g. .NET Balaxys AiAssistantController) that
have already authenticated the end-user and forward identity via trusted
internal headers.  The ERP proves its identity with a shared SERVICE_KEY;
user identity travels via X-Tenant-Id / X-User-Id / X-User-Role.

Python never validates a user JWT in this path — .NET owns that.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from fastapi import HTTPException, Request, status

from app.config import settings

VALID_ROLES = {"direccion", "marca", "tienda", "sku"}


@dataclass(frozen=True)
class ServiceAuthContext:
    """Identity resolved from X-* service headers."""

    tenant_id: int
    user_id: int       # ERP user ID (audit log only — not validated here)
    role: str          # direccion | marca | tienda | sku
    conversation_id: str | None
    request_id: str    # generated if caller omits X-Request-Id


async def get_service_auth_context(request: Request) -> ServiceAuthContext:
    """FastAPI dependency for POST /api/v1/internal/chat.

    Raises:
        503  if SERVICE_KEY is not configured server-side
        401  if X-Service-Key header is absent or wrong
        400  if X-Tenant-Id or X-User-Id are missing / non-integer
    Invalid X-User-Role is silently mapped to 'sku' (most restrictive).
    """
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
    try:
        user_id = int(user_id_str)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-User-Id must be an integer",
        ) from e

    role = (request.headers.get("X-User-Role") or "sku").lower()
    if role not in VALID_ROLES:
        role = "sku"

    conversation_id = request.headers.get("X-Conversation-Id") or None
    request_id = request.headers.get("X-Request-Id") or str(uuid4())

    return ServiceAuthContext(
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        conversation_id=conversation_id,
        request_id=request_id,
    )
