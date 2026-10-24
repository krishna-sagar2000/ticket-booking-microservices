"""Database connection. Each service talks ONLY to its own database."""
from pathlib import Path

from sqlalchemy import create_engine, text
from . import config

engine = create_engine(config.DB_URL, pool_pre_ping=True) if config.DB_URL else None

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "schema.sql"


def init_db() -> None:
    """Create payment_db tables from schema.sql if they do not exist yet.

    Mirrors the pattern used by seat-service and notification-service: called
    once on service startup so a fresh clone works without a manual schema
    load step. Safe to call on every startup (CREATE TABLE IF NOT EXISTS).
    """
    if engine is None:
        return
    sql = "\n".join(
        line for line in SCHEMA_FILE.read_text().splitlines()
        if not line.lstrip().startswith("--")
    )
    with engine.begin() as conn:
        for statement in sql.split(";"):
            if statement.strip():
                conn.execute(text(statement))


def check_connection() -> bool:
    """Used by scripts/db/check_db.py and by you while learning."""
    with engine.connect() as conn:
        return conn.execute(text("SELECT 1")).scalar() == 1
