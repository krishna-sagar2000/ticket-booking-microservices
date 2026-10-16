"""Database connection. Each service talks ONLY to its own database."""
from sqlalchemy import create_engine, text
from . import config

engine = create_engine(config.DB_URL, pool_pre_ping=True) if config.DB_URL else None


def check_connection() -> bool:
    """Used by scripts/db/check_db.py and by you while learning."""
    with engine.connect() as conn:
        return conn.execute(text("SELECT 1")).scalar() == 1
