"""Database access for seat_db. Seat service talks ONLY to its own database.

Tables are created from ../schema.sql and filled from ../seed.sql (see init_db). The Table
objects below only describe those columns for building queries; they never create anything.

Every state change is ONE conditional UPDATE over all the requested seats. The WHERE clause
is the rule check, and the number of rows it changed decides the outcome: if it is not
every requested seat, the transaction is rolled back, so a booking gets all of its seats
or none (BR1). Never SELECT-then-UPDATE in Python.
Times are naive UTC datetimes passed in from Python, so writes and comparisons share one clock.
"""
from datetime import datetime
from pathlib import Path

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, create_engine, select, text, update

from . import config

engine = create_engine(config.DB_URL, pool_pre_ping=True) if config.DB_URL else None

AVAILABLE, HELD, SOLD = "AVAILABLE", "HELD", "SOLD"
SQL_DIR = Path(__file__).resolve().parent.parent

metadata = MetaData()
events = Table(
    "events", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100)),
    Column("starts_at", DateTime),
)
seats = Table(
    "seats", metadata,
    Column("event_id", Integer, primary_key=True),
    Column("seat_no", String(10), primary_key=True),
    Column("status", String(10)),
    Column("booking_id", String(64)),
    Column("hold_expires_at", DateTime),
)


def check_connection() -> bool:
    """Used by scripts/db/check_db.py and by you while learning."""
    with engine.connect() as conn:
        return conn.execute(text("SELECT 1")).scalar() == 1


def _run_sql_file(conn, name: str) -> None:
    sql = "\n".join(line for line in (SQL_DIR / name).read_text().splitlines()
                    if not line.lstrip().startswith("--"))
    if conn.dialect.name == "sqlite":  # the tests run the same files on SQLite
        sql = sql.replace("INSERT IGNORE", "INSERT OR IGNORE")
    for statement in sql.split(";"):
        if statement.strip():
            conn.execute(text(statement))


def init_db() -> None:
    """Create the tables (schema.sql) and add the sample rows (seed.sql). Safe on every startup."""
    with engine.begin() as conn:
        _run_sql_file(conn, "schema.sql")
        _run_sql_file(conn, "seed.sql")


def _seat_dict(row) -> dict:
    return {"seatNo": row.seat_no, "status": row.status,
            "bookingId": row.booking_id, "holdExpiresAt": row.hold_expires_at}


def event_exists(event_id: int) -> bool:
    with engine.connect() as conn:
        return conn.execute(select(events.c.id).where(events.c.id == event_id)).first() is not None


def list_seats(event_id: int) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(select(seats).where(seats.c.event_id == event_id).order_by(seats.c.seat_no))
        return [_seat_dict(r) for r in rows]


def get_seats(event_id: int, seat_nos: list[str]) -> dict[str, dict]:
    """Current state of the given seats, keyed by seat_no. Missing seats are left out."""
    with engine.connect() as conn:
        rows = conn.execute(select(seats).where(seats.c.event_id == event_id, seats.c.seat_no.in_(seat_nos)))
        return {r.seat_no: _seat_dict(r) for r in rows}


def _all_or_nothing(stmt, expected: int) -> bool:
    """Run one UPDATE; commit only if it matched exactly `expected` rows, else roll back."""
    with engine.connect() as conn:
        tx = conn.begin()
        if conn.execute(stmt).rowcount == expected:
            tx.commit()
            return True
        tx.rollback()
        return False


def _these_seats(event_id: int, seat_nos: list[str]):
    return (seats.c.event_id == event_id) & seats.c.seat_no.in_(seat_nos)


def hold_seats(event_id: int, seat_nos: list[str], booking_id: str, until: datetime) -> bool:
    """AVAILABLE -> HELD for every seat, or for none. True = this booking got all of them."""
    stmt = (update(seats)
            .where(_these_seats(event_id, seat_nos), seats.c.status == AVAILABLE)
            .values(status=HELD, booking_id=booking_id, hold_expires_at=until))
    return _all_or_nothing(stmt, len(seat_nos))


def confirm_seats(event_id: int, seat_nos: list[str], booking_id: str, now: datetime) -> bool:
    """HELD by this booking and not expired -> SOLD, for every seat or none.

    A seat this booking already bought also matches, so a retried confirm succeeds again
    (MySQL counts matched rows, not only changed ones; SQLAlchemy's driver setting does this).
    """
    still_held = (seats.c.status == HELD) & (seats.c.hold_expires_at >= now)
    stmt = (update(seats)
            .where(_these_seats(event_id, seat_nos), seats.c.booking_id == booking_id,
                   still_held | (seats.c.status == SOLD))
            .values(status=SOLD, hold_expires_at=None))
    return _all_or_nothing(stmt, len(seat_nos))


def release_seats(event_id: int, seat_nos: list[str], booking_id: str) -> int:
    """HELD by this booking -> AVAILABLE. SOLD seats never match. Returns how many were freed."""
    stmt = (update(seats)
            .where(_these_seats(event_id, seat_nos), seats.c.booking_id == booking_id, seats.c.status == HELD)
            .values(status=AVAILABLE, booking_id=None, hold_expires_at=None))
    with engine.begin() as conn:
        return conn.execute(stmt).rowcount


def expire_holds(now: datetime) -> int:
    """Every HELD seat whose hold has passed -> AVAILABLE. SOLD rows never match. Returns count."""
    stmt = (update(seats)
            .where(seats.c.status == HELD, seats.c.hold_expires_at < now)
            .values(status=AVAILABLE, booking_id=None, hold_expires_at=None))
    with engine.begin() as conn:
        return conn.execute(stmt).rowcount
