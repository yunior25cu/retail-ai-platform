"""Shared pytest fixtures."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    """Sync test client. Entering the context triggers FastAPI lifespan
    (pool initialise) so tests can hit the DB-backed endpoints."""
    # Import inside fixture so failed config loads surface as test failures,
    # not as collection errors.
    from app.main import app

    with TestClient(app) as c:
        yield c
