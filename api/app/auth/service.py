"""Auth business logic — pure functions, no state, no DB access.

Depends on:
  - bcrypt for password hashing (cost factor from settings)
  - jwt_handler for token creation
  - hashlib for refresh token hashing
"""

from __future__ import annotations

import hashlib
import secrets

import bcrypt

from app.auth.jwt_handler import (
    InvalidTokenError,
    create_access_token as _create_jwt,
    decode_access_token as _decode_jwt,
)
from app.config import settings


def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt."""
    rounds = getattr(settings, "bcrypt_rounds", 12)
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:  # noqa: BLE001
        return False


def create_access_token(
    user_id: str,
    tenant_id: int,
    role: str,
    vertical: str,
) -> str:
    """Mint an HS256 access token including the vertical claim."""
    expire_hours = getattr(settings, "jwt_expire_hours", None)
    expires_minutes = expire_hours * 60 if expire_hours else None
    return _create_jwt(
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        vertical=vertical,
        expires_minutes=expires_minutes,
    )


def decode_access_token(token: str) -> dict | None:
    """Decode a JWT and return claims, or None if invalid/expired."""
    try:
        return _decode_jwt(token)
    except (InvalidTokenError, Exception):  # noqa: BLE001
        return None


def create_refresh_token() -> str:
    """Generate a cryptographically secure random token (plain text).

    The caller stores hash_refresh_token(token) in the DB, never the plain.
    """
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    """SHA-256 hash of the refresh token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def access_token_expires_in() -> int:
    """Seconds until an access token expires (for TokenResponse.expires_in)."""
    expire_hours = getattr(settings, "jwt_expire_hours", None)
    minutes = expire_hours * 60 if expire_hours else settings.jwt_expire_minutes
    return minutes * 60
