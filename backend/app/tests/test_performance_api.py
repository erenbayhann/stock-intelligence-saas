from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app


def _client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


def test_performance_summary_defaults_to_7d_window(db_session):
    client = _client(db_session)
    try:
        response = client.get("/api/v1/performance/summary")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["window"] == "7d"
    assert body["n_predictions"] == 0


def test_performance_summary_rejects_unsupported_window(db_session):
    client = _client(db_session)
    try:
        response = client.get("/api/v1/performance/summary?window=90d")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
