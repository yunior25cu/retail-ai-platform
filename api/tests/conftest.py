"""Shared pytest fixtures."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    """Sync test client. Entering the context triggers FastAPI lifespan
    (pool initialise) so tests can hit the DB-backed endpoints."""
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_rate_limiter() -> None:
    """Make rate-limiter state local to each test. Without this, the in-memory
    limiter accumulates hits across tests and triggers spurious 429s."""
    from app.security.rate_limiter import limiter

    limiter.reset()
