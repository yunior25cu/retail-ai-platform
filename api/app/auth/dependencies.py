"""FastAPI auth dependency.

For sub-phase 4.3 this is a MOCK: accepts optional headers
``X-Mock-User`` / ``X-Mock-Tenant`` / ``X-Mock-Role`` and falls back to
``dev-user`` / ``tenant=7`` / ``role=direccion``. Sub-phase 4.5 replaces this
with a real JWT decoder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Header


@dataclass(frozen=True)
class AuthContext:
    """Carries the resolved identity of the caller through the request."""

    user_id: str
    tenant_id: int
    role: str  # 'direccion' / 'marca' / 'tienda' / 'sku'


async def get_auth_context(
    x_mock_user: Annotated[str | None, Header(alias="X-Mock-User")] = None,
    x_mock_tenant: Annotated[int | None, Header(alias="X-Mock-Tenant")] = None,
    x_mock_role: Annotated[str | None, Header(alias="X-Mock-Role")] = None,
) -> AuthContext:
    """Return an ``AuthContext`` derived from the request headers (mock).

    Defaults are intentionally permissive for local development:
    ``dev-user`` / tenant ``7`` / role ``direccion``.
    """
    return AuthContext(
        user_id=x_mock_user or "dev-user",
        tenant_id=x_mock_tenant if x_mock_tenant is not None else 7,
        role=(x_mock_role or "direccion").lower(),
    )
