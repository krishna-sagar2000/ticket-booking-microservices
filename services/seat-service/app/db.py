"""Database connection, the seats table, and its queries. Seat service talks ONLY to seat_db.

Every state change is ONE conditional UPDATE: the WHERE clause is the rule check, and the
rowcount tells the caller whether it won. Never SELECT-then-UPDATE in Python (see BR1).
Times are naive UTC datetimes passed in from Python, so all comparisons use one clock.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, create_engine, insert, select, text, update
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from . import config

engine = create_engine(config.DB_URL, pool_pre_ping=True) if config.DB_URL else None

AVAILABLE, HELD, BOOKED = "AVAILABLE", "HELD", "BOOKED"
SEED_LABELS = [f"A{n}" for n in range(1, 11)]


class Base(DeclarativeBase):
    pass


class Seat(Base):
    __tablename__ = "seats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(10), unique=True)
    status: Mapped[str] = mapped_column(String(20), default=AVAILABLE, index=True)
    booking_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    held_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


def check_connection() -> bool:
    """Used by scripts/db/check_db.py and by you while learning."""
    with engine.connect() as conn:
        return conn.execute(text("SELECT 1")).scalar() == 1


def init_db() -> None:
    """Create the seats table and seed A1..A10. Safe to run on every startup."""
    Base.metadata.create_all(engine)
    rows = [{"id": i, "label": label, "status": AVAILABLE} for i, label in enumerate(SEED_LABELS, start=1)]
    with engine.begin() as conn:
        # MySQL: INSERT IGNORE; SQLite (used by the tests): INSERT OR IGNORE
        stmt = insert(Seat).prefix_with("IGNORE", dialect="mysql").prefix_with("OR IGNORE", dialect="sqlite")
        conn.execute(stmt, rows)


def _row_to_dict(row) -> dict:
    return {"id": row.id, "label": row.label, "status": row.status,
            "bookingId": row.booking_id, "heldUntil": row.held_until}


def list_seats() -> list[dict]:
    with engine.connect() as conn:
        return [_row_to_dict(r) for r in conn.execute(select(Seat.__table__).order_by(Seat.id))]


def get_seat(seat_id: int) -> Optional[dict]:
    with engine.connect() as conn:
        row = conn.execute(select(Seat.__table__).where(Seat.id == seat_id)).first()
        return _row_to_dict(row) if row else None


def hold_seat(seat_id: int, booking_id: str, until: datetime) -> int:
    """AVAILABLE -> HELD. Returns rows changed: 1 = this caller won the seat, 0 = it did not."""
    stmt = (update(Seat)
            .where(Seat.id == seat_id, Seat.status == AVAILABLE)
            .values(status=HELD, booking_id=booking_id, held_until=until))
    with engine.begin() as conn:
        return conn.execute(stmt).rowcount


def confirm_seat(seat_id: int, booking_id: str) -> int:
    """HELD (by this booking) -> BOOKED. Returns rows changed (0 or 1)."""
    stmt = (update(Seat)
            .where(Seat.id == seat_id, Seat.status == HELD, Seat.booking_id == booking_id)
            .values(status=BOOKED, held_until=None))
    with engine.begin() as conn:
        return conn.execute(stmt).rowcount


def release_seat(seat_id: int, booking_id: str) -> int:
    """HELD (by this booking) -> AVAILABLE. Returns rows changed (0 or 1)."""
    stmt = (update(Seat)
            .where(Seat.id == seat_id, Seat.status == HELD, Seat.booking_id == booking_id)
            .values(status=AVAILABLE, booking_id=None, held_until=None))
    with engine.begin() as conn:
        return conn.execute(stmt).rowcount


def expire_holds(now: datetime) -> int:
    """Every HELD seat whose hold has passed -> AVAILABLE. BOOKED rows never match. Returns count."""
    stmt = (update(Seat)
            .where(Seat.status == HELD, Seat.held_until < now)
            .values(status=AVAILABLE, booking_id=None, held_until=None))
    with engine.begin() as conn:
        return conn.execute(stmt).rowcount
