"""Containers start together, so the database may not be ready for the first request."""
import pytest
from sqlalchemy.exc import OperationalError

from app import db


def test_database_not_ready_is_retried_on_the_next_request(tmp_path):
    db._engine = None
    with pytest.raises(OperationalError):
        # nothing listens on port 1: same as MySQL still starting up
        db.init_engine("mysql+pymysql://booking_user:x@127.0.0.1:1/booking_db")
    assert db._engine is None          # not remembered, so the next call tries again

    db.init_engine(f"sqlite:///{tmp_path / 'later.db'}")   # database is up now
    assert db.check_connection()
