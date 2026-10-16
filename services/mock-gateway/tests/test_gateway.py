from fastapi.testclient import TestClient
from app.main import app, state

client = TestClient(app)


def test_charge_approved():
    state["mode"] = "ok"
    r = client.post("/charge", json={"bookingId": "b1", "amount": 100})
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"


def test_charge_when_down_returns_503():
    client.post("/admin/mode", json={"mode": "down"})
    r = client.post("/charge", json={"bookingId": "b1", "amount": 100})
    assert r.status_code == 503
    client.post("/admin/mode", json={"mode": "ok"})
