"""The booking flow: Booking coordinates Seat, Payment and Notification.

    create : validate -> Seat.hold -> save booking HELD                     (201)
    pay    : idempotency -> BR3 -> claim -> Payment.charge -> Seat.confirm
             -> booking CONFIRMED -> Notification (best effort)          (200)
    cancel : state check -> booking CANCELLED -> Seat.release            (200)
    expire : every HELD booking past its hold -> EXPIRED                 (200)

Business rules live in rules.py, SQL in db.py, HTTP calls in clients.py.
This file only decides the ORDER of the steps and what to undo when one fails.
"""
import json
import logging
import uuid
from datetime import timedelta

from . import clients, clock, config, db, rules
from .errors import AppError, error_body

log = logging.getLogger("booking-service")


def _view(b: dict) -> dict:
    """The JSON shape of a booking returned by every endpoint."""
    return {
        "bookingId": b["id"],
        "eventId": b["event_id"],
        "seats": b["seats"],
        "customerEmail": b["customer_email"],
        "amount": b["amount"],
        "status": b["status"],
        "holdExpiresAt": clock.iso(b["hold_expires_at"]),
        "paymentId": b.get("payment_id"),
        "createdAt": clock.iso(b["created_at"]),
    }


def _stale_before(now):
    return now - timedelta(seconds=config.PAY_LOCK_TTL_SECONDS)


def _load(booking_id: str) -> dict:
    """Read a booking, 404 if missing. A HELD booking whose time is up is marked EXPIRED here
    (lazy expiry), so a reader never sees a HELD booking that can no longer be paid."""
    b = db.get_booking(booking_id)
    if b is None:
        raise AppError(404, "BOOKING_NOT_FOUND", f"Booking {booking_id} does not exist")
    now = clock.now()
    if b["status"] == rules.HELD and rules.is_hold_expired(b["hold_expires_at"], now):
        if db.mark_expired(booking_id, now, _stale_before(now)):
            log.info("booking expired (found on read)", extra={"bookingId": booking_id})
        b = db.get_booking(booking_id)
    return b


# ---------------------------------------------------------------- create
def create_booking(event_id: int, seats: list[str], customer_email: str) -> dict:
    seats = rules.check_requested_seats(seats, config.MAX_SEATS_PER_BOOKING)
    amount = rules.booking_amount(len(seats), config.SEAT_PRICE)
    booking_id = str(uuid.uuid4())   # created here so Seat can store it with the hold

    # Read the clock BEFORE Seat starts its hold: our expiry is then never later than
    # Seat's, so Booking never accepts a payment for a hold that Seat already dropped.
    started = clock.now()
    hold_expires_at = started + timedelta(seconds=config.HOLD_SECONDS)

    try:
        clients.hold_seats(booking_id, event_id, seats)
    except AppError as exc:
        if exc.status_code >= 500:
            # We do not know if Seat held the seats before failing; free them to be safe.
            clients.release_seats(booking_id, event_id, seats)
        log.info("booking rejected: %s", exc.code, extra={"eventId": event_id, "seats": seats})
        raise

    try:
        db.insert_booking(booking_id, event_id, customer_email, amount, seats,
                          hold_expires_at, started)
    except Exception:
        # Compensation: the seats are held but we could not record the booking.
        log.exception("could not save booking; releasing seats", extra={"bookingId": booking_id})
        clients.release_seats(booking_id, event_id, seats)
        raise

    log.info("booking created", extra={"bookingId": booking_id, "seats": seats,
                                       "status": rules.HELD})
    return _view(db.get_booking(booking_id))


def get_booking(booking_id: str) -> dict:
    return _view(_load(booking_id))


# ------------------------------------------------------------------- pay
def pay_with_idempotency(booking_id: str, idem_key: str, path: str) -> tuple[int, dict, bool]:
    """BR4 (Booking side). Returns (status_code, body, replayed)."""
    req_hash = rules.request_fingerprint("POST", path, None)
    existing = db.idem_begin(idem_key, booking_id, req_hash, clock.now())
    if existing is not None:
        rules.check_idempotent_repeat(existing["request_hash"], existing["status"], req_hash)
        log.info("idempotent replay: returning saved response",
                 extra={"bookingId": booking_id, "idempotencyKey": idem_key,
                        "savedStatus": existing["response_code"]})
        return existing["response_code"], json.loads(existing["response_body"]), True

    try:
        body = pay(booking_id, idem_key)
    except AppError as exc:
        if rules.is_final_outcome(exc.status_code, exc.code):
            db.idem_finish(idem_key, exc.status_code,
                           json.dumps(error_body(exc.code, exc.message)), clock.now())
        else:
            db.idem_drop(idem_key)   # retryable: same key may be sent again
        raise
    except Exception:
        db.idem_drop(idem_key)
        raise
    db.idem_finish(idem_key, 200, json.dumps(body), clock.now())
    return 200, body, False


def pay(booking_id: str, idem_key: str) -> dict:
    b = _load(booking_id)
    now = clock.now()
    # BR3: only a HELD, unexpired booking can be paid.
    rules.check_payable(b["status"], b["hold_expires_at"], now)

    # The same check again, but atomic in the database, so two payments with
    # DIFFERENT keys for the same booking cannot both go ahead.
    if not db.claim_for_payment(booking_id, idem_key, now, _stale_before(now)):
        b = _load(booking_id)
        rules.check_payable(b["status"], b["hold_expires_at"], clock.now())
        raise AppError(409, "PAYMENT_IN_PROGRESS",
                       "Another payment for this booking is in progress")

    # Step 1: charge. On any failure the booking stays HELD and can be paid again.
    try:
        payment = clients.charge(booking_id, b["amount"], idem_key)
    except AppError as exc:
        db.release_pay_lock(booking_id, idem_key, clock.now())
        log.warning("payment failed; booking stays HELD: %s", exc.code,
                    extra={"bookingId": booking_id})
        raise
    payment_id = str(payment.get("paymentId") or payment.get("id") or "") or None
    log.info("payment approved", extra={"bookingId": booking_id, "paymentId": payment_id})

    # Step 2: confirm the seats (only after the money is taken).
    try:
        clients.confirm_seats(booking_id, b["event_id"], b["seats"])
    except clients.SeatConfirmRejected as rej:
        # Known gap (report section 9): the payment went through but Seat has
        # already released the hold. A real system would refund automatically.
        db.release_pay_lock(booking_id, idem_key, clock.now())
        db.mark_expired(booking_id, clock.now(), _stale_before(clock.now()))
        log.error("REFUND_REQUIRED: paid but seats could not be confirmed (%s)", rej.code,
                  extra={"bookingId": booking_id, "paymentId": payment_id})
        raise AppError(409, "HOLD_EXPIRED",
                       f"Seats were released before confirmation; payment {payment_id} "
                       "must be refunded")
    except AppError:
        # Seat is down. Booking stays HELD; a retry with the SAME key replays the
        # payment (no second charge) and tries to confirm again.
        db.release_pay_lock(booking_id, idem_key, clock.now())
        log.warning("payment taken but Seat unavailable; retry with the same key",
                    extra={"bookingId": booking_id, "paymentId": payment_id})
        raise

    # Step 3: HELD -> CONFIRMED.
    if not db.mark_confirmed(booking_id, idem_key, payment_id, clock.now()):
        log.error("could not mark booking CONFIRMED after payment",
                  extra={"bookingId": booking_id, "paymentId": payment_id})
        raise AppError(409, "INVALID_STATE_CHANGE", "Booking changed while it was being paid")
    log.info("booking confirmed", extra={"bookingId": booking_id, "status": rules.CONFIRMED})

    # Step 4: notification is best effort and cannot undo the booking.
    clients.notify(booking_id, "BOOKING_CONFIRMED",
                   f"Booking {booking_id} confirmed for seats {', '.join(b['seats'])}",
                   b["customer_email"])
    return _view(db.get_booking(booking_id))


# ---------------------------------------------------------------- cancel
def cancel(booking_id: str) -> dict:
    b = _load(booking_id)
    rules.ensure_transition(b["status"], rules.CANCELLED)

    now = clock.now()
    if not db.mark_cancelled(booking_id, now, _stale_before(now)):
        b = _load(booking_id)
        rules.ensure_transition(b["status"], rules.CANCELLED)   # it changed meanwhile
        raise AppError(409, "PAYMENT_IN_PROGRESS",
                       "Booking is being paid right now and cannot be cancelled")
    log.info("booking cancelled", extra={"bookingId": booking_id, "status": rules.CANCELLED})

    # Booking is CANCELLED first, seats freed second: if the release call fails,
    # Seat's expiry job frees them within HOLD_SECONDS, and nobody can pay meanwhile.
    clients.release_seats(booking_id, b["event_id"], b["seats"])
    clients.notify(booking_id, "BOOKING_CANCELLED", f"Booking {booking_id} cancelled",
                   b["customer_email"])
    return _view(db.get_booking(booking_id))


# ---------------------------------------------------------------- expire
def expire_due() -> dict:
    """Mark every HELD booking whose hold time has passed as EXPIRED. Safe to run twice."""
    now = clock.now()
    count = db.expire_due_bookings(now, _stale_before(now))
    log.info("expiry run", extra={"expiredCount": count})
    return {"expiredCount": count}
