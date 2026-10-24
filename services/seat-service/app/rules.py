"""Business rules for this service live here (one function per rule).

Tag every rule with its id, for example:
    # BR1: a seat belongs to one booking at a time
and write a test named test_BR1_... so the report can trace rule -> code -> test.

The rule checks themselves are the WHERE clauses in db.py; a refused UPDATE changes nothing.
Only after that do we read the seats, to explain the refusal (404 vs 409, which seat).
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import config, db
from .errors import AppError


def _now() -> datetime:
    """Naive UTC, whole seconds (MySQL DATETIME has no fraction, so what we return is what we store)."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _iso(t) -> Optional[str]:
    if isinstance(t, str):  # SQLite (tests) returns DATETIME as text
        t = datetime.fromisoformat(t)
    return t.isoformat() + "Z" if t else None


def _require_seats(event_id: int, seat_nos: list[str]) -> dict[str, dict]:
    """404 if the event or any seat does not exist; else the seats' current state."""
    if not db.event_exists(event_id):
        raise AppError(404, "EVENT_NOT_FOUND", f"Event {event_id} does not exist")
    found = db.get_seats(event_id, seat_nos)
    missing = [s for s in seat_nos if s not in found]
    if missing:
        raise AppError(404, "SEAT_NOT_FOUND", f"Seat {', '.join(missing)} does not exist for event {event_id}")
    return found


def _seats_phrase(seat_nos: list[str]) -> str:
    return f"Seat {seat_nos[0]} is" if len(seat_nos) == 1 else f"Seats {', '.join(seat_nos)} are"


def _result(booking_id: str, event_id: int, seat_nos: list[str], status: str, **extra) -> dict:
    return {"bookingId": booking_id, "eventId": event_id, "seats": seat_nos, "status": status, **extra}


def list_seats(event_id: int) -> list[dict]:
    if not db.event_exists(event_id):
        raise AppError(404, "EVENT_NOT_FOUND", f"Event {event_id} does not exist")
    return [{**s, "holdExpiresAt": _iso(s["holdExpiresAt"])} for s in db.list_seats(event_id)]


# BR1: a seat belongs to one booking at a time (all requested seats are held, or none)
def hold_seats(booking_id: str, event_id: int, seat_nos: list[str]) -> dict:
    expires_at = _now() + timedelta(seconds=config.HOLD_SECONDS)
    if not db.hold_seats(event_id, seat_nos, booking_id, expires_at):
        found = _require_seats(event_id, seat_nos)
        held = [s for s in seat_nos if found[s]["status"] == db.HELD]
        sold = [s for s in seat_nos if found[s]["status"] == db.SOLD]
        parts = ([f"{_seats_phrase(held)} already held"] if held else []) + \
                ([f"{_seats_phrase(sold)} already sold"] if sold else [])
        detail = "; ".join(parts) or "A seat was taken by another booking"
        raise AppError(409, "SEAT_UNAVAILABLE", detail)
    return _result(booking_id, event_id, seat_nos, db.HELD, holdExpiresAt=_iso(expires_at))


# BR2: a seat is sold only while this booking's hold is still valid; a retry of a sale is a no-op
def confirm_seats(booking_id: str, event_id: int, seat_nos: list[str]) -> dict:
    if not db.confirm_seats(event_id, seat_nos, booking_id, _now()):
        found = _require_seats(event_id, seat_nos)
        lost = [s for s in seat_nos
                if not (found[s]["bookingId"] == booking_id and found[s]["status"] in (db.HELD, db.SOLD))]
        detail = (f"{_seats_phrase(lost)} no longer held by this booking" if lost
                  else "The hold has expired")
        raise AppError(409, "HOLD_EXPIRED", detail)
    return _result(booking_id, event_id, seat_nos, db.SOLD)


# BR2: a paid (SOLD) seat is never released; releasing twice is a no-op
def release_seats(booking_id: str, event_id: int, seat_nos: list[str]) -> dict:
    _require_seats(event_id, seat_nos)  # seats are never deleted, so this check cannot go stale
    released = db.release_seats(event_id, seat_nos, booking_id)
    return _result(booking_id, event_id, seat_nos, db.AVAILABLE, releasedCount=released)


# BR2: a hold expires after HOLD_SECONDS; a paid (SOLD) seat is never released
def expire_holds() -> dict:
    return {"expiredCount": db.expire_holds(_now())}
