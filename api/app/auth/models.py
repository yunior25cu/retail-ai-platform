"""Domain models for the auth module.

Plain dataclasses — no ORM. Matches auth.tenants / auth.users /
auth.refresh_tokens tables in pymeconta_local.
Note: the 'plan' column is stored as 'tenant_plan' in SQL Server
(plan is a reserved word).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from uuid import UUID


@dataclass
class Tenant:
    id: int
    name: str
    slug: str
    vertical: str
    plan: str
    is_active: bool
    created_at: datetime
    trial_ends_at: date | None = None
    platform_tenant_id: int | None = None  # maps to retail-ai-platform tenant_id


@dataclass
class User:
    id: UUID
    tenant_id: int
    email: str
    password_hash: str
    role: str
    full_name: str | None
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


@dataclass
class RefreshToken:
    id: UUID
    user_id: UUID
    token_hash: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
