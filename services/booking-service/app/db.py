"""Database access for booking_db. This is the ONLY file that runs SQL.

The booking service never reads seat_db, payment_db or notification_db.
Seats and payments are referred to only by plain values (seat_no, payment_id).

Every state change is ONE conditional UPDATE (... WHERE status='HELD' ...).
If it changes 0 rows, someone else got there first. This is what makes the
state machine safe when two requests arrive at the same moment.
"""
from datetime import datetime

from sqlalchemy import (Column, DateTime, ForeignKey, Index, Integer, MetaData,
                        Numeric, String, Table, Text, create_engine, delete,
                        insert, select, update, func, or_)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from . import config

metadata = MetaData()

# Keep these definitions in step with schema.sql (schema.sql is the copy the team reads).
bookings = Table(
    "bookings", metadata,
    Column("id", String(36), primary_key=True),             # UUID created by Booking
    Column("event_id", Integer, nullable=False),
    Column("customer_email", String(255), nullable=False),
    Column("amount", Numeric(10, 2), nullable=False),
    Column("status", String(20), nullable=False),           # HELD|CONFIRMED|CANCELLED|EXPIRED
    Column("hold_expires_at", DateTime, nullable=False),
    Column("pay_lock", String(100), nullable=True),         # Idempotency-Key of the payment in flight
    Column("pay_locked_at", DateTime, nullable=True),
    Column("payment_id", String(64), nullable=True),        # ID from Payment service (no FK)
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
    Index("ix_bookings_status_expiry", "status", "hold_expires_at"),
)

booking_seats = Table(
    "booking_seats", metadata,
    Column("booking_id", String(36), ForeignKey("bookings.id"), primary_key=True),
    Column("seat_no", String(10), primary_key=True),
)

idempotency_keys = Table(
    "idempotency_keys", metadata,
    Column("idem_key", String(100), primary_key=True),      # PK = only one request can claim a key
    Column("booking_id", String(36), nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("status", String(20), nullable=False),           # IN_PROGRESS | DONE
    Column("response_code", Integer, nullable=True),
    Column("response_body", Text, nullable=True),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)

_engine: Engine | None = None


def init_engine(url: str | None = None) -> Engine:
    """Create the engine and the tables if they do not exist yet (same as schema.sql)."""
    global _engine
    url = url or config.DB_URL
    if not url:
        raise RuntimeError("DB_URL is not set. Copy .env.example to .env")
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
    _engine = create_engine(url, **kwargs)
    metadata.create_all(_engine)
    return _engine


def get_engine() -> Engine:
    return _engine or init_engine()


def check_connection() -> bool:
    """Used by scripts/db/check_db.py and by you while learning."""
    with get_engine().connect() as conn:
        return conn.execute(select(1)).scalar() == 1


# ---------------------------------------------------------------- bookings
def insert_booking(booking_id: str, event_id: int, customer_email: str, amount: float,
                   seats: list[str], hold_expires_at: datetime, now: datetime) -> None:
    """Booking row and its seats are written in ONE transaction."""
    with get_engine().begin() as conn:
        conn.execute(insert(bookings).values(
            id=booking_id, event_id=event_id, customer_email=customer_email,
            amount=amount, status="HELD", hold_expires_at=hold_expires_at,
            created_at=now, updated_at=now))
        conn.execute(insert(booking_seats),
                     [{"booking_id": booking_id, "seat_no": s} for s in seats])


def get_booking(booking_id: str) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(select(bookings).where(bookings.c.id == booking_id)).mappings().first()
        if row is None:
            return None
        seats = conn.execute(
            select(booking_seats.c.seat_no)
            .where(booking_seats.c.booking_id == booking_id)
            .order_by(booking_seats.c.seat_no)).scalars().all()
    booking = dict(row)
    booking["amount"] = float(booking["amount"])
    booking["seats"] = list(seats)
    return booking


def _lock_is_free(stale_before: datetime):
    """No payment in flight, or the one in flight was abandoned long ago."""
    return or_(bookings.c.pay_lock.is_(None), bookings.c.pay_locked_at < stale_before)


def claim_for_payment(booking_id: str, idem_key: str, now: datetime, stale_before: datetime) -> bool:
    """BR3 + concurrency, atomically: take the right to pay only if the booking is
    HELD, not expired and nobody else is paying. True = this request may pay."""
    stmt = (update(bookings)
            .where(bookings.c.id == booking_id,
                   bookings.c.status == "HELD",
                   bookings.c.hold_expires_at > now,
                   _lock_is_free(stale_before))
            .values(pay_lock=idem_key, pay_locked_at=now, updated_at=now))
    with get_engine().begin() as conn:
        return conn.execute(stmt).rowcount == 1


def release_pay_lock(booking_id: str, idem_key: str, now: datetime) -> None:
    """Payment did not complete; let the customer try again."""
    stmt = (update(bookings)
            .where(bookings.c.id == booking_id, bookings.c.pay_lock == idem_key)
            .values(pay_lock=None, pay_locked_at=None, updated_at=now))
    with get_engine().begin() as conn:
        conn.execute(stmt)


def mark_confirmed(booking_id: str, idem_key: str, payment_id: str | None, now: datetime) -> bool:
    """HELD -> CONFIRMED, only by the request that holds the payment lock."""
    stmt = (update(bookings)
            .where(bookings.c.id == booking_id,
                   bookings.c.status == "HELD",
                   bookings.c.pay_lock == idem_key)
            .values(status="CONFIRMED", payment_id=payment_id,
                    pay_lock=None, pay_locked_at=None, updated_at=now))
    with get_engine().begin() as conn:
        return conn.execute(stmt).rowcount == 1


def mark_cancelled(booking_id: str, now: datetime, stale_before: datetime) -> bool:
    """HELD -> CANCELLED, refused while a payment is in flight."""
    stmt = (update(bookings)
            .where(bookings.c.id == booking_id,
                   bookings.c.status == "HELD",
                   _lock_is_free(stale_before))
            .values(status="CANCELLED", updated_at=now))
    with get_engine().begin() as conn:
        return conn.execute(stmt).rowcount == 1


def mark_expired(booking_id: str, now: datetime, stale_before: datetime) -> bool:
    """HELD -> EXPIRED for one booking whose hold time has passed."""
    stmt = (update(bookings)
            .where(bookings.c.id == booking_id,
                   bookings.c.status == "HELD",
                   bookings.c.hold_expires_at <= now,
                   _lock_is_free(stale_before))
            .values(status="EXPIRED", updated_at=now))
    with get_engine().begin() as conn:
        return conn.execute(stmt).rowcount == 1


def expire_due_bookings(now: datetime, stale_before: datetime) -> int:
    """HELD -> EXPIRED for every booking whose hold has passed.
    Touches only HELD rows, so it never changes a CONFIRMED booking and is safe to run twice."""
    stmt = (update(bookings)
            .where(bookings.c.status == "HELD",
                   bookings.c.hold_expires_at <= now,
                   _lock_is_free(stale_before))
            .values(status="EXPIRED", updated_at=now))
    with get_engine().begin() as conn:
        return conn.execute(stmt).rowcount


def count_by_status() -> dict[str, int]:
    with get_engine().connect() as conn:
        rows = conn.execute(select(bookings.c.status, func.count())
                            .group_by(bookings.c.status)).all()
    return {status: n for status, n in rows}


# --------------------------------------------------------- idempotency keys
def idem_begin(idem_key: str, booking_id: str, request_hash: str, now: datetime) -> dict | None:
    """Try to claim an Idempotency-Key.

    Returns None if THIS request inserted the key (it is new: go and do the work).
    Returns the existing row if the key was already there.
    The primary key guarantees that of two identical requests arriving together,
    exactly one insert succeeds.
    """
    for _ in range(3):
        try:
            with get_engine().begin() as conn:
                conn.execute(insert(idempotency_keys).values(
                    idem_key=idem_key, booking_id=booking_id, request_hash=request_hash,
                    status="IN_PROGRESS", created_at=now, updated_at=now))
            return None
        except IntegrityError:
            existing = idem_get(idem_key)
            if existing is not None:
                return existing
            # The other request finished with a retryable error and removed the key; try again.
    raise RuntimeError("Could not claim idempotency key")


def idem_get(idem_key: str) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(select(idempotency_keys)
                           .where(idempotency_keys.c.idem_key == idem_key)).mappings().first()
    return dict(row) if row else None


def idem_finish(idem_key: str, response_code: int, response_body: str, now: datetime) -> None:
    stmt = (update(idempotency_keys)
            .where(idempotency_keys.c.idem_key == idem_key)
            .values(status="DONE", response_code=response_code,
                    response_body=response_body, updated_at=now))
    with get_engine().begin() as conn:
        conn.execute(stmt)


def idem_drop(idem_key: str) -> None:
    """Forget a key whose request failed with a retryable error (e.g. 503)."""
    with get_engine().begin() as conn:
        conn.execute(delete(idempotency_keys).where(idempotency_keys.c.idem_key == idem_key))
