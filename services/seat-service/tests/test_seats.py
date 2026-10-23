import time
from datetime import timedelta

from fastapi.testclient import TestClient

from app import config, rules
from app.main import app

client = TestClient(app)
API = "/api/v1"


def call(action, booking_id, seats, event_id=1):
    return client.post(f"{API}/seats/{action}", json={"bookingId": booking_id, "eventId": event_id, "seats": seats})


def hold(booking_id, *seats):
    return call("hold", booking_id, list(seats))


def confirm(booking_id, *seats):
    return call("confirm", booking_id, list(seats))


def release(booking_id, *seats):
    return call("release", booking_id, list(seats))


def expire():
    return client.post(f"{API}/seats/expire-holds")


def seat(seat_no, event_id=1):
    return next(s for s in client.get(f"{API}/events/{event_id}/seats").json() if s["seatNo"] == seat_no)


# ---- BR1: a seat belongs to one booking at a time ----

def test_BR1_seat_cannot_be_held_twice():
    assert hold("b1", "A1").status_code == 200
    r = hold("b2", "A1")
    assert r.status_code == 409
    assert r.json()["code"] == "SEAT_UNAVAILABLE"
    assert "A1" in r.json()["message"]
    assert seat("A1")["bookingId"] == "b1"


def test_BR1_hold_is_all_or_nothing():
    hold("b1", "A2")
    r = hold("b2", "A1", "A2", "A3")  # A2 is taken, so none of the three may be held
    assert r.status_code == 409 and "A2" in r.json()["message"]
    assert seat("A1")["status"] == "AVAILABLE"
    assert seat("A3")["status"] == "AVAILABLE"
    assert seat("A2")["bookingId"] == "b1"


def test_BR1_hold_with_unknown_seat_holds_nothing():
    r = hold("b1", "A1", "Z9")
    assert r.status_code == 404 and r.json()["code"] == "SEAT_NOT_FOUND"
    assert seat("A1")["status"] == "AVAILABLE"


def test_BR1_sold_seat_cannot_be_held():
    hold("b1", "A1")
    confirm("b1", "A1")
    r = hold("b2", "A1")
    assert r.status_code == 409 and r.json()["code"] == "SEAT_UNAVAILABLE"


def test_BR1_released_seat_can_be_held_again():
    hold("b1", "A1")
    release("b1", "A1")
    assert hold("b2", "A1").status_code == 200
    assert seat("A1")["bookingId"] == "b2"


# ---- BR2: a hold expires after HOLD_SECONDS; a paid seat is never released ----

def test_BR2_expired_hold_is_released(monkeypatch):
    monkeypatch.setattr(config, "HOLD_SECONDS", -5)  # hold is already past its expiry
    hold("b1", "A1", "A2")
    assert expire().json() == {"expiredCount": 2}
    assert seat("A1") == {"seatNo": "A1", "status": "AVAILABLE", "bookingId": None, "holdExpiresAt": None}


def test_BR2_paid_seat_is_not_released(monkeypatch):
    hold("b1", "A1")
    confirm("b1", "A1")
    a_day_later = rules._now() + timedelta(days=1)
    monkeypatch.setattr(rules, "_now", lambda: a_day_later)  # long after the hold would have expired
    assert expire().json() == {"expiredCount": 0}
    assert release("b1", "A1").json()["releasedCount"] == 0
    assert seat("A1")["status"] == "SOLD" and seat("A1")["bookingId"] == "b1"


def test_BR2_unexpired_hold_is_kept():
    hold("b1", "A1")
    assert expire().json() == {"expiredCount": 0}
    assert seat("A1")["status"] == "HELD"


def test_BR2_expire_twice_is_safe(monkeypatch):
    monkeypatch.setattr(config, "HOLD_SECONDS", -5)
    hold("b1", "A1")
    hold("b2", "A2")
    assert expire().json() == {"expiredCount": 2}
    r = expire()
    assert r.status_code == 200 and r.json() == {"expiredCount": 0}


def test_BR2_expired_hold_cannot_be_confirmed(monkeypatch):
    monkeypatch.setattr(config, "HOLD_SECONDS", -5)
    hold("b1", "A1")  # expired, but the job has not swept it yet
    r = confirm("b1", "A1")
    assert r.status_code == 409 and r.json()["code"] == "HOLD_EXPIRED"
    assert seat("A1")["status"] == "HELD"


def test_BR2_background_job_releases_expired_holds(monkeypatch):
    monkeypatch.setattr(config, "HOLD_SECONDS", -5)
    monkeypatch.setattr(config, "EXPIRY_INTERVAL_SECONDS", 0.05)
    hold("b1", "A1")
    with TestClient(app) as running:  # starts the app's lifespan, which starts the job
        deadline = time.monotonic() + 5
        while seat("A1")["status"] != "AVAILABLE" and time.monotonic() < deadline:
            time.sleep(0.05)
        assert running.get("/health").status_code == 200
    assert seat("A1")["status"] == "AVAILABLE"


# ---- hold / confirm / release contract (what booking-service relies on) ----

def test_list_seats_of_event():
    r = client.get(f"{API}/events/1/seats")
    assert r.status_code == 200
    assert [s["seatNo"] for s in r.json()] == ["A1", "A2", "A3", "A4", "A5", "B1", "B2", "B3", "B4", "B5"]
    assert all(s["status"] == "AVAILABLE" for s in r.json())


def test_list_seats_unknown_event_is_404():
    r = client.get(f"{API}/events/99/seats")
    assert r.status_code == 404 and r.json()["code"] == "EVENT_NOT_FOUND"


def test_hold_response_shape():
    body = hold("b1", "A1", "A2").json()
    assert body["bookingId"] == "b1" and body["eventId"] == 1
    assert body["seats"] == ["A1", "A2"] and body["status"] == "HELD"
    assert body["holdExpiresAt"].endswith("Z")
    assert seat("A2")["holdExpiresAt"] == body["holdExpiresAt"]


def test_hold_unknown_event_is_404():
    r = call("hold", "b1", ["A1"], event_id=99)
    assert r.status_code == 404 and r.json()["code"] == "EVENT_NOT_FOUND"


def test_confirm_held_seats():
    hold("b1", "A1", "A2")
    r = confirm("b1", "A1", "A2")
    assert r.status_code == 200 and r.json()["status"] == "SOLD"
    assert seat("A1")["status"] == "SOLD" and seat("A1")["holdExpiresAt"] is None


def test_confirm_retry_is_ok():
    hold("b1", "A1")
    confirm("b1", "A1")
    r = confirm("b1", "A1")
    assert r.status_code == 200 and r.json()["status"] == "SOLD"


def test_confirm_by_other_booking_is_rejected():
    hold("b1", "A1")
    r = confirm("b2", "A1")
    assert r.status_code == 409 and r.json()["code"] == "HOLD_EXPIRED"
    assert seat("A1")["status"] == "HELD"


def test_confirm_is_all_or_nothing():
    hold("b1", "A1")  # b1 never held A2
    r = confirm("b1", "A1", "A2")
    assert r.status_code == 409 and "A2" in r.json()["message"]
    assert seat("A1")["status"] == "HELD"


def test_release_held_seats():
    hold("b1", "A1", "A2")
    r = release("b1", "A1", "A2")
    assert r.status_code == 200 and r.json()["releasedCount"] == 2
    assert seat("A1")["status"] == "AVAILABLE" and seat("A1")["bookingId"] is None


def test_release_twice_is_ok():
    hold("b1", "A1")
    release("b1", "A1")
    r = release("b1", "A1")
    assert r.status_code == 200 and r.json()["releasedCount"] == 0


def test_release_by_other_booking_changes_nothing():
    hold("b1", "A1")
    r = release("b2", "A1")
    assert r.status_code == 200 and r.json()["releasedCount"] == 0
    assert seat("A1")["bookingId"] == "b1"


def test_release_unknown_seat_is_404():
    r = release("b1", "Z9")
    assert r.status_code == 404 and r.json()["code"] == "SEAT_NOT_FOUND"


def test_invalid_bodies_are_400():
    for body in ({}, {"bookingId": "b1", "eventId": 1, "seats": []},
                 {"bookingId": "b1", "eventId": 1, "seats": ["A1", "A1"]},
                 {"bookingId": "", "eventId": 1, "seats": ["A1"]},
                 {"bookingId": "b1", "eventId": "x", "seats": ["A1"]}):
        r = client.post(f"{API}/seats/hold", json=body)
        assert r.status_code == 400 and r.json()["code"] == "VALIDATION_ERROR", body


def test_error_carries_correlation_id():
    r = client.post(f"{API}/seats/hold", json={"bookingId": "b1", "eventId": 99, "seats": ["A1"]},
                    headers={"X-Correlation-Id": "t-1"})
    assert r.json()["correlationId"] == "t-1"
