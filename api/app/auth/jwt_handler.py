"""JWT encode/decode helpers (HS256).

Claims emitted / consumed:
    sub:        user id (string)
    tenant_id:  BIGINT (integer)
    role:       'direccion' / 'marca' / 'tienda' / 'sku'
    iat:        issued-at (UTC seconds)
    exp:        expiration (UTC seconds)

Tokens are short-lived (60 minutes by default; see settings.jwt_expire_minutes).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from app.config import settings


class InvalidTokenError(Exception):
    """Raised when a bearer token is malformed, expired, or signed with the
    wrong key. The endpoint translates this into HTTP 401."""


def create_access_token(
    *,
    user_id: str,
    tenant_id: int,
    role: str,
    expires_minutes: int | None = None,
) -> str:
    """Mint an HS256 token. Default expiry from settings."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=expires_minutes or settings.jwt_expire_minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "tenant_id": int(tenant_id),
        "role": role.lower(),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a token. Raises InvalidTokenError on any failure.

    Returns the claims dict on success.
    """
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as e:
        raise InvalidTokenError(str(e)) from e

    # Defensive checks: the JWT library already validates exp/iat, but we want
    # explicit shape errors for missing custom claims.
    for required in ("sub", "tenant_id", "role"):
        if required not in claims:
            raise InvalidTokenError(f"missing claim: {required}")
    if not isinstance(claims["tenant_id"], int):
        raise InvalidTokenError("tenant_id must be int")
    return claims
