"""GET /api/v1/health: validates the API is up and the DB ping succeeds."""

from fastapi.testclient import TestClient


def test_health_endpoint_reports_db_ok(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok", body
    assert body["db_ok"] is True, body
    assert isinstance(body.get("db_database"), str)
    # tenant_count is best-effort; can be None if dbo.empresa not yet populated,
    # but if present it must be a non-negative integer.
    tc = body.get("tenant_count")
    assert tc is None or (isinstance(tc, int) and tc >= 0), body


def test_root_returns_app_metadata(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "retail-ai-api"
    assert body["version"] == "0.4.6"
