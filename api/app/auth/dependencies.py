"""FastAPI auth dependency.

Resolution order:
    1. If ``Authorization: Bearer <jwt>`` header is present, decode the JWT and
       use its claims. Invalid / expired tokens -> 401.
    2. Otherwise, fall back to the mock headers ``X-Mock-User`` /
       ``X-Mock-Tenant`` / ``X-Mock-Role``. This convenience path is disabled
       in production by setting ``AUTH_REQUIRE_JWT=true`` in the environment.
    3. With no headers at all and AUTH_REQUIRE_JWT=false, defaults to
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

    # Mock path
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
