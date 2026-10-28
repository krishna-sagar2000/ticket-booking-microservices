"""Database connection and models. Each service talks ONLY to its own database."""
import datetime as dt

from sqlalchemy import create_engine, text, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

from . import config

engine = create_engine(config.DB_URL, pool_pre_ping=True) if config.DB_URL else None
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False) if engine else None

Base = declarative_base()


class Notification(Base):
    """A record of a notification sent/recorded for a booking.

    No real email/SMS is sent - this is a mock, per assignment scope.
    Owned exclusively by notification-service (notification_db).
    """
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    booking_id = Column(String(64), nullable=False, index=True)
    type = Column(String(64), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: dt.datetime.now(dt.timezone.utc), nullable=False)


def init_db() -> None:
    """Create tables if they do not exist yet. Called once at service startup."""
    if engine is not None:
        Base.metadata.create_all(engine)


def check_connection() -> bool:
    """Used by scripts/db/check_db.py and by you while learning."""
    with engine.connect() as conn:
        return conn.execute(text("SELECT 1")).scalar() == 1
