"""Edge cases on top of test_seats.py: boundaries, error messages, validation limits, several
events, restart safety, schema constraints, the expiry job's error handling, and the 500 format."""
import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import config, db, expiry_job, rules
from app.main import app
from .test_seats import API, call, client, confirm, expire, hold, release, seat

FROZEN = datetime(2026, 11, 1, 18, 0, 0)


def freeze(monkeypatch, at):
    monkeypatch.setattr(rules, "_now", lambda: at)


def add_event_2(engine):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO events (id, name, starts_at) VALUES (2, 'Second Show', '2026-12-01 19:00:00')"))
        conn.execute(text("INSERT INTO seats (event_id, seat_no, status) VALUES (2, 'A1', 'AVAILABLE'), (2, 'A2', 'AVAILABLE')"))


# ---- health and correlation id ----

def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "UP", "service": "seat-service"}


def test_correlation_id_is_echoed_in_header():
    r = client.get(f"{API}/events/1/seats", headers={"X-Correlation-Id": "t-echo"})
    assert r.headers["X-Correlation-Id"] == "t-echo"


def test_correlation_id_is_generated_when_missing():
    r = release("b1", "Z9")
    generated = r.headers["X-Correlation-Id"]
    assert len(generated) == 36 and r.json()["correlationId"] == generated


# ---- hold expiry time and the exact boundary ----

def test_hold_expires_hold_seconds_from_now(monkeypatch):
    freeze(monkeypatch, FROZEN)
    monkeypatch.setattr(config, "HOLD_SECONDS", 30)
    assert hold("b1", "A1").json()["holdExpiresAt"] == "2026-11-01T18:00:30Z"


def test_BR2_confirm_at_exact_expiry_second_is_allowed(monkeypatch):
    freeze(monkeypatch, FROZEN)
    hold("b1", "A1")
    freeze(monkeypatch, FROZEN + timedelta(seconds=config.HOLD_SECONDS))
    assert confirm("b1", "A1").status_code == 200


def test_BR2_confirm_one_second_after_expiry_is_refused(monkeypatch):
    freeze(monkeypatch, FROZEN)
    hold("b1", "A1")
    freeze(monkeypatch, FROZEN + timedelta(seconds=config.HOLD_SECONDS + 1))
    r = confirm("b1", "A1")
    assert r.status_code == 409
    assert (r.json()["code"], r.json()["message"]) == ("HOLD_EXPIRED", "The hold has expired")


def test_BR2_sweep_at_exact_expiry_second_keeps_the_hold(monkeypatch):
    freeze(monkeypatch, FROZEN)
    hold("b1", "A1")
    freeze(monkeypatch, FROZEN + timedelta(seconds=config.HOLD_SECONDS))
    assert expire().json() == {"expiredCount": 0}
    freeze(monkeypatch, FROZEN + timedelta(seconds=config.HOLD_SECONDS + 1))
    assert expire().json() == {"expiredCount": 1}


def test_BR2_sweep_releases_only_expired_holds(monkeypatch):
    freeze(monkeypatch, FROZEN)
    hold("old", "A1", "A2")
    freeze(monkeypatch, FROZEN + timedelta(seconds=20))
    hold("new", "A3")
    freeze(monkeypatch, FROZEN + timedelta(seconds=config.HOLD_SECONDS + 1))
    assert expire().json() == {"expiredCount": 2}
    assert seat("A1")["status"] == "AVAILABLE" and seat("A2")["status"] == "AVAILABLE"
    assert seat("A3")["status"] == "HELD" and seat("A3")["bookingId"] == "new"


def test_BR2_confirm_retry_after_hold_time_has_passed_is_still_ok(monkeypatch):
    freeze(monkeypatch, FROZEN)
    hold("b1", "A1")
    confirm("b1", "A1")
    freeze(monkeypatch, FROZEN + timedelta(hours=1))
    r = confirm("b1", "A1")
    assert r.status_code == 200 and r.json()["status"] == "SOLD"


# ---- BR1 refusal messages name the seats and why ----

def test_BR1_hold_refusal_names_several_held_seats():
    hold("b1", "A1", "A2")
    r = hold("b2", "A1", "A2", "A3")
    assert r.status_code == 409 and r.json()["message"] == "Seats A1, A2 are already held"


def test_BR1_hold_refusal_says_sold():
    hold("b1", "A1")
    confirm("b1", "A1")
    assert hold("b2", "A1").json()["message"] == "Seat A1 is already sold"


def test_BR1_hold_refusal_names_held_and_sold_seats():
    hold("b1", "A1")
    confirm("b1", "A1")
    hold("b2", "A2")
    r = hold("b3", "A1", "A2", "A3")
    assert r.json()["message"] == "Seat A2 is already held; Seat A1 is already sold"
    assert seat("A3")["status"] == "AVAILABLE"


def test_BR1_same_booking_cannot_hold_the_same_seat_twice():
    hold("b1", "A1")
    r = hold("b1", "A1")
    assert r.status_code == 409 and r.json()["code"] == "SEAT_UNAVAILABLE"
    assert seat("A1")["bookingId"] == "b1"


def test_BR1_unknown_seat_is_404_even_when_others_are_taken():
    hold("b1", "A1")
    r = hold("b2", "A1", "Z9")
    assert r.status_code == 404 and r.json()["message"] == "Seat Z9 does not exist for event 1"


def test_BR1_seat_not_found_lists_every_missing_seat():
    r = hold("b1", "Y8", "A1", "Z9")
    assert r.status_code == 404 and r.json()["message"] == "Seat Y8, Z9 does not exist for event 1"
    assert seat("A1")["status"] == "AVAILABLE"


# ---- confirm / release edge cases ----

def test_confirm_seat_sold_to_another_booking_is_refused():
    hold("b1", "A1")
    confirm("b1", "A1")
    r = confirm("b2", "A1")
    assert r.status_code == 409 and r.json()["message"] == "Seat A1 is no longer held by this booking"
    assert seat("A1")["bookingId"] == "b1"


def test_confirm_available_seat_is_refused():
    r = confirm("b1", "A1")
    assert r.status_code == 409 and r.json()["code"] == "HOLD_EXPIRED"
    assert seat("A1")["status"] == "AVAILABLE"


def test_confirm_after_release_is_refused():
    hold("b1", "A1")
    release("b1", "A1")
    assert confirm("b1", "A1").status_code == 409


def test_confirm_unknown_seat_or_event_is_404():
    assert confirm("b1", "Z9").json()["code"] == "SEAT_NOT_FOUND"
    assert call("confirm", "b1", ["A1"], event_id=99).json()["code"] == "EVENT_NOT_FOUND"


def test_release_unknown_event_is_404():
    r = call("release", "b1", ["A1"], event_id=99)
    assert r.status_code == 404 and r.json()["code"] == "EVENT_NOT_FOUND"


def test_release_counts_only_this_bookings_held_seats():
    hold("b1", "A1", "A2")
    confirm("b1", "A1")       # A1 is now SOLD: must stay sold
    hold("b2", "A3")          # A3 belongs to another booking: must stay held
    r = release("b1", "A1", "A2", "A3", "A4")
    assert r.status_code == 200 and r.json()["releasedCount"] == 1
    assert [seat(s)["status"] for s in ("A1", "A2", "A3", "A4")] == ["SOLD", "AVAILABLE", "HELD", "AVAILABLE"]


def test_release_response_shape():
    hold("b1", "A1")
    assert release("b1", "a1").json() == {"bookingId": "b1", "eventId": 1, "seats": ["A1"],
                                          "status": "AVAILABLE", "releasedCount": 1}


def test_confirm_response_shape():
    hold("b1", "A1", "A2")
    assert confirm("b1", "A1", "A2").json() == {"bookingId": "b1", "eventId": 1,
                                                "seats": ["A1", "A2"], "status": "SOLD"}


def test_full_lifecycle_of_one_seat():
    assert seat("B1")["status"] == "AVAILABLE"
    hold("b1", "B1")
    assert seat("B1")["status"] == "HELD"
    release("b1", "B1")
    assert seat("B1")["status"] == "AVAILABLE"
    hold("b2", "B1")
    confirm("b2", "B1")
    assert seat("B1") == {"seatNo": "B1", "status": "SOLD", "bookingId": "b2", "holdExpiresAt": None}


# ---- several events: same seat number, separate seats ----

def test_same_seat_number_in_two_events_is_independent(seat_db):
    add_event_2(seat_db)
    assert hold("b1", "A1").status_code == 200
    assert call("hold", "b2", ["A1"], event_id=2).status_code == 200
    assert seat("A1", event_id=1)["bookingId"] == "b1"
    assert seat("A1", event_id=2)["bookingId"] == "b2"
    assert call("release", "b1", ["A1"], event_id=2).json()["releasedCount"] == 0


def test_seat_of_one_event_is_not_found_in_another(seat_db):
    add_event_2(seat_db)
    r = call("hold", "b1", ["B1"], event_id=2)
    assert r.status_code == 404 and r.json()["message"] == "Seat B1 does not exist for event 2"


def test_list_seats_shows_only_that_event(seat_db):
    add_event_2(seat_db)
    assert [s["seatNo"] for s in client.get(f"{API}/events/2/seats").json()] == ["A1", "A2"]


# ---- validation limits (400 VALIDATION_ERROR) ----

def post_hold(body):
    return client.post(f"{API}/seats/hold", json=body)


@pytest.mark.parametrize("body", [
    {"bookingId": "b1", "eventId": 0, "seats": ["A1"]},
    {"bookingId": "b1", "eventId": -1, "seats": ["A1"]},
    {"bookingId": "x" * 65, "eventId": 1, "seats": ["A1"]},
    {"bookingId": "b1", "eventId": 1, "seats": [f"S{i}" for i in range(11)]},
    {"bookingId": "b1", "eventId": 1, "seats": ["A" * 11]},
    {"bookingId": "b1", "eventId": 1, "seats": ["   "]},
    {"bookingId": "b1", "eventId": 1, "seats": "A1"},
    {"bookingId": "b1", "eventId": 1},
    {"eventId": 1, "seats": ["A1"]},
])
def test_invalid_hold_body_is_400(body):
    r = post_hold(body)
    assert r.status_code == 400 and r.json()["code"] == "VALIDATION_ERROR"


def test_body_that_is_not_json_is_400():
    r = client.post(f"{API}/seats/hold", content="not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("action", ["confirm", "release"])
def test_confirm_and_release_validate_the_body_too(action):
    r = client.post(f"{API}/seats/{action}", json={"bookingId": "b1", "eventId": 1, "seats": []})
    assert r.status_code == 400 and r.json()["code"] == "VALIDATION_ERROR"


def test_longest_valid_booking_id_and_ten_seats_are_accepted():
    ten = ["A1", "A2", "A3", "A4", "A5", "B1", "B2", "B3", "B4", "B5"]
    r = post_hold({"bookingId": "x" * 64, "eventId": 1, "seats": ten})
    assert r.status_code == 200 and r.json()["seats"] == ten


def test_validation_error_changes_nothing():
    post_hold({"bookingId": "b1", "eventId": 1, "seats": ["A1", "A1"]})
    assert seat("A1")["status"] == "AVAILABLE"


def test_list_seats_with_non_numeric_event_is_400():
    r = client.get(f"{API}/events/abc/seats")
    assert r.status_code == 400 and r.json()["code"] == "VALIDATION_ERROR"


# ---- startup and schema: restart safety, constraints ----

def test_restart_does_not_reset_seats():
    hold("b1", "A1")
    confirm("b1", "A1")
    db.init_db()  # what every service restart runs
    assert seat("A1")["status"] == "SOLD"
    assert len(client.get(f"{API}/events/1/seats").json()) == 10


def test_schema_rejects_an_unknown_status(seat_db):
    with pytest.raises(IntegrityError), seat_db.begin() as conn:
        conn.execute(text("UPDATE seats SET status='BROKEN' WHERE seat_no='A1'"))


def test_schema_rejects_a_duplicate_seat(seat_db):
    with pytest.raises(IntegrityError), seat_db.begin() as conn:
        conn.execute(text("INSERT INTO seats (event_id, seat_no, status) VALUES (1, 'A1', 'AVAILABLE')"))


def test_lifespan_without_database_still_serves_health(monkeypatch):
    monkeypatch.setattr(db, "engine", None)
    with TestClient(app) as no_db:
        assert no_db.get("/health").status_code == 200


# ---- expiry job keeps running when the database fails ----

def test_BR2_expiry_job_survives_a_database_error(monkeypatch):
    calls = []

    def flaky_expire():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database is down")
        return {"expiredCount": 0}

    async def stop_after_three_rounds(_seconds):
        if len(calls) >= 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(rules, "expire_holds", flaky_expire)
    monkeypatch.setattr(expiry_job.asyncio, "sleep", stop_after_three_rounds)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(expiry_job.run_forever())
    assert len(calls) == 3  # failed once, then carried on


# ---- unexpected errors use the shared format ----

def test_unexpected_error_is_500_in_shared_format(monkeypatch):
    def boom(_event_id):
        raise RuntimeError("database is down")

    monkeypatch.setattr(rules, "list_seats", boom)
    r = TestClient(app, raise_server_exceptions=False).get(f"{API}/events/1/seats",
                                                           headers={"X-Correlation-Id": "t-500"})
    assert r.status_code == 500
    assert r.json() == {"code": "INTERNAL_ERROR", "message": "Something went wrong", "correlationId": "t-500"}
