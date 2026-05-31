"""Auth endpoints — /api/v1/auth/*

POST /login    → issue access + refresh tokens
POST /refresh  → rotate refresh token
POST /logout   → revoke refresh token
GET  /me       → current user info

Rate limiting on /login: 5 requests / minute / IP via slowapi.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth import repository as repo
from app.auth.models import User
from app.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserResponse,
)
from app.auth.service import (
    access_token_expires_in,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_refresh_token,
    verify_password,
)
from app.config import settings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
log = structlog.get_logger(__name__)

limiter = Limiter(key_func=get_remote_address)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

_GENERIC_401 = "Credenciales inválidas"


def _token_response(user: User, vertical: str, platform_tenant_id: int | None = None) -> TokenResponse:
    plain_refresh = create_refresh_token()
    # Use platform_tenant_id in the JWT so chat endpoints resolve vertical correctly.
    # Falls back to user.tenant_id (auth internal id) if not mapped yet.
    effective_tid = platform_tenant_id if platform_tenant_id is not None else user.tenant_id
    return TokenResponse(
        access_token=create_access_token(
            str(user.id), effective_tid, user.role, vertical
        ),
        refresh_token=plain_refresh,
        token_type="bearer",
        expires_in=access_token_expires_in(),
        tenant_id=effective_tid,
        role=user.role,
        vertical=vertical,
    ), plain_refresh


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, payload: LoginRequest) -> TokenResponse:
    tenant = await repo.get_tenant_by_slug(payload.tenant_slug)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=_GENERIC_401)

    user = await repo.get_user_by_email(tenant.id, payload.email)
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=_GENERIC_401)

    await repo.update_last_login(str(user.id))

    token_resp, plain_refresh = _token_response(user, tenant.vertical, tenant.platform_tenant_id)
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=getattr(settings, "refresh_token_expire_days", 30)
    )
    await repo.save_refresh_token(
        str(user.id), hash_refresh_token(plain_refresh), expires_at
    )

    log.info("auth.login", tenant=tenant.slug, user_id=str(user.id), role=user.role)
    return token_resp


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest) -> TokenResponse:
    token_hash = hash_refresh_token(payload.refresh_token)
    stored = await repo.get_valid_refresh_token(token_hash)
    if not stored:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Refresh token inválido o expirado")

    user = await repo.get_user_by_id(str(stored.user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=_GENERIC_401)

    tenant = await repo.get_tenant_by_id(user.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=_GENERIC_401)

    # Rotate: revoke current, issue new pair
    await repo.revoke_refresh_token(token_hash)

    token_resp, plain_refresh = _token_response(user, tenant.vertical, tenant.platform_tenant_id)
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=getattr(settings, "refresh_token_expire_days", 30)
    )
    await repo.save_refresh_token(
        str(user.id), hash_refresh_token(plain_refresh), expires_at
    )
    return token_resp


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    token: str | None = Depends(oauth2_scheme),
) -> dict:
    if token:
        claims = decode_access_token(token)
        if claims:
            await repo.revoke_all_user_refresh_tokens(str(claims.get("sub", "")))
    # Always 200 — do not reveal whether the token was valid
    return {"detail": "ok"}


@router.get("/me", response_model=UserResponse)
async def me(
    token: str | None = Depends(oauth2_scheme),
) -> UserResponse:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Token requerido",
                            headers={"WWW-Authenticate": "Bearer"})
    claims = decode_access_token(token)
    if not claims:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Token inválido o expirado",
                            headers={"WWW-Authenticate": "Bearer"})

    user = await repo.get_user_by_id(str(claims["sub"]))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Usuario no encontrado")

    return UserResponse(
        id=str(user.id),
        email=user.email,
        role=user.role,
        full_name=user.full_name,
        tenant_id=user.tenant_id,
        is_active=user.is_active,
        created_at=user.created_at,
    )
