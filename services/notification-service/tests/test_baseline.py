from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_is_up():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "UP"


def test_correlation_id_is_echoed():
    r = client.get("/health", headers={"X-Correlation-Id": "abc-123"})
    assert r.headers["X-Correlation-Id"] == "abc-123"


def test_correlation_id_is_created_when_missing():
    r = client.get("/health")
    assert r.headers["X-Correlation-Id"]


def test_unknown_route_has_error_json():
    r = client.get("/api/v1/does-not-exist")
    assert r.status_code == 404


def test_swagger_docs_available():
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
