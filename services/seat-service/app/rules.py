"""Business rules for this service live here (one function per rule).

Tag every rule with its id, for example:
    # BR1: a seat belongs to one booking at a time
and write a test named test_BR1_... so the report can trace rule -> code -> test.

The rule checks themselves are the WHERE clauses in db.py; a rowcount of 0 means the rule
refused the change. Only after that do we look at the seat, to pick 404 vs 409.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import config, db
from .errors import AppError


def _now() -> datetime:
    """Naive UTC, whole seconds (MySQL DATETIME has no fraction, so what we return is what we store)."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _iso(t: Optional[datetime]) -> Optional[str]:
    return t.isoformat() + "Z" if t else None


def _refused(seat_id: int, code: str, message: str) -> AppError:
    if db.get_seat(seat_id) is None:
        return AppError(404, "SEAT_NOT_FOUND", f"Seat {seat_id} does not exist")
    return AppError(409, code, message)


def list_seats() -> list[dict]:
    return [{"seatId": s["id"], "label": s["label"], "status": s["status"],
             "bookingId": s["bookingId"], "holdExpiresAt": _iso(s["heldUntil"])}
            for s in db.list_seats()]


# BR1: a seat belongs to one booking at a time
def hold(seat_id: int, booking_id: str) -> dict:
    expires_at = _now() + timedelta(seconds=config.HOLD_SECONDS)
    if db.hold_seat(seat_id, booking_id, expires_at) != 1:
        raise _refused(seat_id, "SEAT_UNAVAILABLE", "Seat already taken")
    return {"seatId": seat_id, "status": db.HELD, "holdExpiresAt": _iso(expires_at)}


def confirm(seat_id: int, booking_id: str) -> dict:
    if db.confirm_seat(seat_id, booking_id) != 1:
        raise _refused(seat_id, "INVALID_STATE_CHANGE", "Seat is not held by this booking")
    return {"seatId": seat_id, "status": db.BOOKED}


def release(seat_id: int, booking_id: str) -> dict:
    if db.release_seat(seat_id, booking_id) != 1:
        raise _refused(seat_id, "INVALID_STATE_CHANGE", "Seat is not held by this booking")
    return {"seatId": seat_id, "status": db.AVAILABLE}


# BR2: a hold expires after HOLD_SECONDS; a paid (BOOKED) seat is never released
def expire_holds() -> dict:
    return {"expiredCount": db.expire_holds(_now())}
