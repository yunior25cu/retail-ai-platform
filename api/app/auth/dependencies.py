"""FastAPI auth dependency.

Resolution order:
    1. If SERVICE_KEY is configured AND ``X-Service-Key`` header matches,
       resolve identity from X-Tenant-Id / X-User-Id / X-User-Role headers
       (service-to-service mode, called by ERP proxy).
    2. If SERVICE_MODE=true and no matching service key, reject with 401.
    3. If ``Authorization: Bearer <jwt>`` header is present, decode the JWT and
       use its claims. Invalid / expired tokens -> 401.
    4. Otherwise, fall back to the mock headers ``X-Mock-User`` /
       ``X-Mock-Tenant`` / ``X-Mock-Role``. This convenience path is disabled
       in production by setting ``AUTH_REQUIRE_JWT=true`` in the environment.
    5. With no headers at all and AUTH_REQUIRE_JWT=false, defaults to
       ``dev-user`` / tenant=7 / role=direccion for local exploration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, HTTPException, Request, status

from app.auth.jwt_handler import InvalidTokenError, decode_access_token
from app.config import settings


@dataclass(frozen=True)
class AuthContext:
    """Carries the resolved identity of the caller through the request."""

    user_id: str
    tenant_id: int
    role: str  # 'direccion' / 'marca' / 'tienda' / 'sku'


VALID_ROLES = {"direccion", "marca", "tienda", "sku"}


async def get_auth_context(
    request: Request,
    x_mock_user: Annotated[str | None, Header(alias="X-Mock-User")] = None,
    x_mock_tenant: Annotated[int | None, Header(alias="X-Mock-Tenant")] = None,
    x_mock_role: Annotated[str | None, Header(alias="X-Mock-Role")] = None,
) -> AuthContext:
    # --- Service-to-service path ---
    # Activated only when SERVICE_KEY is configured and the header matches.
    # Allows ERPs to call /api/v1/chat with service headers (e.g. for testing).
    # The dedicated /api/v1/internal/chat endpoint always uses service auth.
    if settings.service_key and request.headers.get("X-Service-Key"):
        provided = request.headers.get("X-Service-Key", "")
        if provided != settings.service_key:
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
        role = (request.headers.get("X-User-Role") or "sku").lower()
        if role not in VALID_ROLES:
            role = "sku"
        return AuthContext(
            user_id=request.headers.get("X-User-Id") or "service-user",
            tenant_id=int(tenant_id_str),
            role=role,
        )

    # SERVICE_MODE=true: reject all non-service requests
    if settings.service_mode:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_service_key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # --- Bearer JWT path ---
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        try:
            claims = decode_access_token(token)
        except InvalidTokenError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"invalid_token: {e}",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e
        role = str(claims["role"]).lower()
        if role not in VALID_ROLES:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"invalid_role: {role}",
            )
        return AuthContext(
            user_id=str(claims["sub"]),
            tenant_id=int(claims["tenant_id"]),
            role=role,
        )

    # --- Mock path (dev / CLI / tests) ---
    if settings.auth_require_jwt:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_bearer_token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    role = (x_mock_role or "direccion").lower()
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"invalid_role: {role}")
    return AuthContext(
        user_id=x_mock_user or "dev-user",
        tenant_id=x_mock_tenant if x_mock_tenant is not None else 7,
        role=role,
    )
