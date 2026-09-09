from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app


def test_health_endpoint_reports_ok(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        response = client.get("/api/v1/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "reachable"
    assert "active_securities" in body
