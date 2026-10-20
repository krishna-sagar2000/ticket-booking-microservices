"""Tests for the notification-service API.

These tests hit a real notification_db (via the .env DB_URL), since this
service's whole job is to persist and list notifications. Run the MySQL
container (scripts/db/docker-compose.yml) before running these tests.
"""
import uuid

from fastapi.testclient import TestClient

from app.main import app


def test_create_notification_returns_201_and_id():
    with TestClient(app) as client:
        booking_id = f"test-{uuid.uuid4()}"
        r = client.post(
            "/api/v1/notifications",
            json={
                "bookingId": booking_id,
                "type": "BOOKING_CONFIRMED",
                "message": "Your booking is confirmed.",
            },
        )
        assert r.status_code == 201
        body = r.json()
        assert "notificationId" in body
        assert isinstance(body["notificationId"], int)


def test_list_notifications_returns_created_notification():
    with TestClient(app) as client:
        booking_id = f"test-{uuid.uuid4()}"
        client.post(
            "/api/v1/notifications",
            json={
                "bookingId": booking_id,
                "type": "BOOKING_CONFIRMED",
                "message": "Your booking is confirmed.",
            },
        )

        r = client.get(f"/api/v1/notifications/{booking_id}")
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        assert items[0]["bookingId"] == booking_id
        assert items[0]["type"] == "BOOKING_CONFIRMED"
        assert items[0]["message"] == "Your booking is confirmed."
        assert "createdAt" in items[0]


def test_list_notifications_preserves_order_for_multiple_entries():
    with TestClient(app) as client:
        booking_id = f"test-{uuid.uuid4()}"
        client.post(
            "/api/v1/notifications",
            json={"bookingId": booking_id, "type": "BOOKING_CONFIRMED", "message": "first"},
        )
        client.post(
            "/api/v1/notifications",
            json={"bookingId": booking_id, "type": "BOOKING_CANCELLED", "message": "second"},
        )

        r = client.get(f"/api/v1/notifications/{booking_id}")
        items = r.json()
        assert len(items) == 2
        assert items[0]["message"] == "first"
        assert items[1]["message"] == "second"


def test_list_notifications_for_unknown_booking_returns_empty_list():
    with TestClient(app) as client:
        r = client.get(f"/api/v1/notifications/no-such-booking-{uuid.uuid4()}")
        assert r.status_code == 200
        assert r.json() == []


def test_create_notification_missing_fields_returns_400():
    with TestClient(app) as client:
        r = client.post("/api/v1/notifications", json={"bookingId": "b1"})
        assert r.status_code == 400
        body = r.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert "correlationId" in body


def test_create_notification_empty_type_returns_400():
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/notifications",
            json={"bookingId": "b1", "type": "", "message": "hi"},
        )
        assert r.status_code == 400
