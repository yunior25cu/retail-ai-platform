"""Pydantic schemas for auth API request/response contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=1)
    tenant_slug: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int          # seconds until access token expires
    tenant_id: int
    role: str
    vertical: str


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class UserCreate(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)
    role: str
    full_name: str | None = None
    tenant_id: int


class UserResponse(BaseModel):
    id: str
    email: str
    role: str
    full_name: str | None
    tenant_id: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
