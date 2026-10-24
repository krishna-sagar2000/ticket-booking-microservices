
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_BR4_same_key_returns_same_result():
    key = "test-br4-replay-001"
    payload = {"bookingId": "booking-br4-replay-001", "amount": 500.00}
    headers = {"Idempotency-Key": key}

    first = client.post("/api/v1/payments", json=payload, headers=headers)
    second = client.post("/api/v1/payments", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json() == first.json()


def test_BR4_same_key_different_body_rejected():
    key = "test-br4-different-001"
    headers = {"Idempotency-Key": key}

    first = client.post(
        "/api/v1/payments",
        json={"bookingId": "booking-br4-different-001", "amount": 500.00},
        headers=headers,
    )
    second = client.post(
        "/api/v1/payments",
        json={"bookingId": "booking-br4-different-001", "amount": 600.00},
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 422
    assert second.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
