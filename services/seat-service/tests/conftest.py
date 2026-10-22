"""Every test gets a fresh, seeded in-memory SQLite database, so tests need no MySQL/Docker.

The race-condition proof (Challenge 1) needs real MySQL and lives in evidence/challenge-1-concurrency/.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import db


@pytest.fixture(autouse=True)
def seat_db(monkeypatch):
    # StaticPool + check_same_thread=False: one shared connection, usable from TestClient's thread
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(db, "engine", engine)
    db.init_db()
    yield engine
    engine.dispose()
