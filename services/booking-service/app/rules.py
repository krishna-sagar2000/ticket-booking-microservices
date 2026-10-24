"""Business rules of the Booking service. No web code and no SQL in this file.

Every function either returns normally (allowed) or raises AppError (not allowed).
The endpoints and the flow call these functions; they never repeat the logic.
Tests: tests/test_rules.py (test_BR3_..., test_BR4_..., test_state_...).
"""
import hashlib
import json
from datetime import datetime

from .errors import AppError

# Booking states -------------------------------------------------------------
HELD = "HELD"
CONFIRMED = "CONFIRMED"
CANCELLED = "CANCELLED"
EXPIRED = "EXPIRED"

# State machine: the ONLY allowed changes. CONFIRMED, CANCELLED and EXPIRED are final.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    HELD: {CONFIRMED, CANCELLED, EXPIRED},
    CONFIRMED: set(),
    CANCELLED: set(),
    EXPIRED: set(),
}


def ensure_transition(current: str, target: str) -> None:
    """State machine: HELD -> CONFIRMED | CANCELLED | EXPIRED. Anything else is refused."""
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise AppError(409, "INVALID_STATE_CHANGE",
                       f"Booking cannot change from {current} to {target}")


def is_hold_expired(hold_expires_at: datetime, now: datetime) -> bool:
    """A hold is valid up to (not including) hold_expires_at."""
    return now >= hold_expires_at


# BR3: a booking can be paid only while it is HELD and its hold has not expired.
def check_payable(status: str, hold_expires_at: datetime, now: datetime) -> None:
    if status == EXPIRED:
        raise AppError(409, "HOLD_EXPIRED",
                       "The seat hold has expired; create a new booking")
    if status != HELD:
        raise AppError(409, "BOOKING_NOT_PAYABLE",
                       f"Booking is {status}; only a HELD booking can be paid")
    if is_hold_expired(hold_expires_at, now):
        raise AppError(409, "HOLD_EXPIRED",
                       "The seat hold has expired; create a new booking")


# BR4 (Booking side): a payment is applied once per booking.
# The same Idempotency-Key must always come with the same request. We store a
# fingerprint (SHA-256) of the request next to the key and compare it on repeats.
def request_fingerprint(method: str, path: str, body: dict | None) -> str:
    canonical = json.dumps(body or {}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{method.upper()}|{path}|{canonical}".encode()).hexdigest()


def check_idempotent_repeat(stored_hash: str, stored_status: str, new_hash: str) -> str:
    """Decide what to do when an Idempotency-Key has been seen before.

    Returns "REPLAY" when the saved response should be returned as-is.
    Raises 422 if the key is reused with a different request, and
    409 if the first request with this key is still running.
    """
    if stored_hash != new_hash:
        raise AppError(422, "IDEMPOTENCY_KEY_REUSED",
                       "This Idempotency-Key was already used for a different request")
    if stored_status != "DONE":
        raise AppError(409, "REQUEST_IN_PROGRESS",
                       "A request with this Idempotency-Key is still being processed")
    return "REPLAY"


# Errors that mean "try again later". Their responses are NOT saved against the
# Idempotency-Key, so the client can retry with the same key and still be safe
# (Payment de-duplicates the charge with the same key).
RETRYABLE_ERROR_CODES = {"REQUEST_IN_PROGRESS", "PAYMENT_IN_PROGRESS"}


def is_final_outcome(status_code: int, code: str | None) -> bool:
    if status_code >= 500:
        return False
    return code not in RETRYABLE_ERROR_CODES


# Input checks for a new booking ----------------------------------------------
def check_requested_seats(seats: list[str], max_seats: int) -> list[str]:
    """Seats must be non-empty, without duplicates and at most max_seats. Returns them normalised."""
    cleaned = [s.strip().upper() for s in seats]
    if not cleaned or any(not s for s in cleaned):
        raise AppError(400, "VALIDATION_ERROR", "At least one seat is required")
    if len(set(cleaned)) != len(cleaned):
        raise AppError(400, "VALIDATION_ERROR", "The same seat is listed twice")
    if len(cleaned) > max_seats:
        raise AppError(400, "VALIDATION_ERROR",
                       f"At most {max_seats} seats can be booked at once")
    return cleaned


def booking_amount(seat_count: int, seat_price: float) -> float:
    """The price is computed by the server from the seat count, never taken from the client."""
    return round(seat_count * seat_price, 2)
