from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)
SEATS = "/api/v1/seats"


def hold(seat_id, booking_id):
    return client.post(f"{SEATS}/{seat_id}/hold", json={"bookingId": booking_id})


def confirm(seat_id, booking_id):
    return client.post(f"{SEATS}/{seat_id}/confirm", json={"bookingId": booking_id})


def release(seat_id, booking_id):
    return client.post(f"{SEATS}/{seat_id}/release", json={"bookingId": booking_id})


def expire():
    return client.post(f"{SEATS}/expire-holds")


def seat(seat_id):
    return next(s for s in client.get(SEATS).json() if s["seatId"] == seat_id)


# ---- BR1: a seat belongs to one booking at a time ----

def test_BR1_seat_cannot_be_held_twice():
    assert hold(1, "b1").status_code == 200
    r = hold(1, "b2")
    assert r.status_code == 409
    assert r.json()["code"] == "SEAT_UNAVAILABLE"
    assert seat(1)["bookingId"] == "b1"


def test_BR1_booked_seat_cannot_be_held():
    hold(1, "b1")
    confirm(1, "b1")
    r = hold(1, "b2")
    assert r.status_code == 409 and r.json()["code"] == "SEAT_UNAVAILABLE"


def test_BR1_released_seat_can_be_held_again():
    hold(1, "b1")
    release(1, "b1")
    assert hold(1, "b2").status_code == 200
    assert seat(1)["bookingId"] == "b2"


# ---- BR2: a hold expires after HOLD_SECONDS; a paid seat is never released ----

def test_BR2_expired_hold_is_released(monkeypatch):
    monkeypatch.setattr(config, "HOLD_SECONDS", -5)  # hold is already past its expiry
    hold(1, "b1")
    assert expire().json() == {"expiredCount": 1}
    assert seat(1) == {"seatId": 1, "label": "A1", "status": "AVAILABLE", "bookingId": None, "holdExpiresAt": None}


def test_BR2_paid_seat_is_not_released(monkeypatch):
    monkeypatch.setattr(config, "HOLD_SECONDS", -5)
    hold(1, "b1")
    confirm(1, "b1")
    assert expire().json() == {"expiredCount": 0}
    assert seat(1)["status"] == "BOOKED"


def test_BR2_unexpired_hold_is_kept():
    hold(1, "b1")
    assert expire().json() == {"expiredCount": 0}
    assert seat(1)["status"] == "HELD"


def test_BR2_expire_twice_is_safe(monkeypatch):
    monkeypatch.setattr(config, "HOLD_SECONDS", -5)
    hold(1, "b1")
    hold(2, "b2")
    assert expire().json() == {"expiredCount": 2}
    r = expire()
    assert r.status_code == 200 and r.json() == {"expiredCount": 0}


# ---- hold / confirm / release contract ----

def test_list_seats_returns_seeded_seats():
    r = client.get(SEATS)
    assert r.status_code == 200
    assert len(r.json()) == 10
    assert all(s["status"] == "AVAILABLE" for s in r.json())


def test_hold_returns_expiry():
    r = hold(1, "b1")
    body = r.json()
    assert body["seatId"] == 1 and body["status"] == "HELD"
    assert body["holdExpiresAt"].endswith("Z")


def test_hold_unknown_seat_is_404():
    r = hold(99, "b1")
    assert r.status_code == 404 and r.json()["code"] == "SEAT_NOT_FOUND"


def test_confirm_held_seat():
    hold(1, "b1")
    r = confirm(1, "b1")
    assert r.status_code == 200 and r.json() == {"seatId": 1, "status": "BOOKED"}


def test_confirm_by_other_booking_is_rejected():
    hold(1, "b1")
    r = confirm(1, "b2")
    assert r.status_code == 409 and r.json()["code"] == "INVALID_STATE_CHANGE"
    assert seat(1)["status"] == "HELD"


def test_confirm_available_seat_is_rejected():
    r = confirm(1, "b1")
    assert r.status_code == 409 and r.json()["code"] == "INVALID_STATE_CHANGE"


def test_release_held_seat():
    hold(1, "b1")
    r = release(1, "b1")
    assert r.status_code == 200 and r.json() == {"seatId": 1, "status": "AVAILABLE"}


def test_release_by_other_booking_is_rejected():
    hold(1, "b1")
    r = release(1, "b2")
    assert r.status_code == 409 and r.json()["code"] == "INVALID_STATE_CHANGE"
    assert seat(1)["bookingId"] == "b1"


def test_release_booked_seat_is_rejected():
    hold(1, "b1")
    confirm(1, "b1")
    r = release(1, "b1")
    assert r.status_code == 409 and r.json()["code"] == "INVALID_STATE_CHANGE"


def test_numeric_booking_id_is_accepted():
    assert hold(1, 42).status_code == 200
    assert confirm(1, "42").status_code == 200


def test_missing_booking_id_is_400():
    r = client.post(f"{SEATS}/1/hold", json={})
    assert r.status_code == 400 and r.json()["code"] == "VALIDATION_ERROR"


def test_error_carries_correlation_id():
    r = client.post(f"{SEATS}/99/hold", json={"bookingId": "b1"}, headers={"X-Correlation-Id": "t-1"})
    assert r.json()["correlationId"] == "t-1"
