
from fastapi.testclient import TestClient
from app.main import app
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

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

   
def test_concurrent_duplicate_payment_is_not_charged_twice():
    key = "test-br4-concurrent-001"
    payload = {
        "bookingId": "booking-br4-concurrent-001",
        "amount": 750.00,
    }
    headers = {"Idempotency-Key": key}

    barrier = Barrier(2)

    def send_payment():
        barrier.wait(timeout=5)
        return client.post(
            "/api/v1/payments",
            json=payload,
            headers=headers,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(send_payment)
            for _ in range(2)
        ]
        responses = [future.result(timeout=15) for future in futures]

    # One request should complete successfully.
    # The other may receive the cached result or an in-progress response.
    assert all(
        response.status_code in (201, 409)
        for response in responses
    )
    assert any(response.status_code == 201 for response in responses)

    successful_responses = [
        response for response in responses
        if response.status_code == 201
    ]
    assert all(
        response.json()["bookingId"] == payload["bookingId"]
        for response in successful_responses
    )

