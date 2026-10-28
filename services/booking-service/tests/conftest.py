"""Test setup: a fresh SQLite database per test, and fake Seat / Payment / Notification
services that answer the real HTTP calls made by app/clients.py.

No MySQL and no other service is needed to run `pytest`.
"""
import os
import threading
import time
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app import clients, clock, db
from app.main import app


class FakeServices:
    """In-memory stand-ins for the three services Booking calls."""

    def __init__(self):
        self.lock = threading.Lock()
        self.seat_owner: dict[tuple[int, str], str] = {}   # (event, seat) -> booking id
        self.sold: set[tuple[int, str]] = set()
        self.payments: dict[str, dict] = {}                 # Idempotency-Key -> response
        self.charge_calls = 0
        self.notifications: list[dict] = []
        self.calls: list[tuple[str, dict, dict]] = []       # (path, body, headers)
        # failure switches
        self.seat_down = False
        self.seat_confirm_reject = False
        self.payment_mode = "ok"        # ok | down | timeout
        self.payment_delay = 0.0
        self.notification_down = False

    # -- dispatcher used instead of httpx.post
    def post(self, url, json=None, headers=None, timeout=None):
        path = httpx.URL(url).path
        self.calls.append((path, json, dict(headers or {})))
        if path.startswith("/api/v1/seats/"):
            return self._seat(path.rsplit("/", 1)[-1], json)
        if path == "/api/v1/payments":
            return self._payment(json, headers or {})
        if path == "/api/v1/notifications":
            if self.notification_down:
                raise httpx.ConnectError("notification down")
            self.notifications.append(json)
            return httpx.Response(201, json={"notificationId": len(self.notifications)})
        return httpx.Response(404, json={"code": "NOT_FOUND", "message": path})

    def _seat(self, action, body):
        if self.seat_down:
            raise httpx.ConnectError("seat down")
        event, booking, seats = body["eventId"], body["bookingId"], body["seats"]
        with self.lock:
            if action == "hold":
                taken = [s for s in seats if (event, s) in self.seat_owner]
                if taken:
                    return httpx.Response(409, json={"code": "SEAT_UNAVAILABLE",
                                                     "message": f"Seat {taken[0]} is already held",
                                                     "correlationId": "-"})
                for s in seats:
                    self.seat_owner[(event, s)] = booking
                return httpx.Response(200, json={"bookingId": booking, "status": "HELD"})
            if action == "confirm":
                if self.seat_confirm_reject:
                    return httpx.Response(409, json={"code": "HOLD_EXPIRED", "message": "expired"})
                for s in seats:
                    self.sold.add((event, s))
                return httpx.Response(200, json={"status": "SOLD"})
            if action == "release":
                for s in seats:
                    if self.seat_owner.get((event, s)) == booking and (event, s) not in self.sold:
                        del self.seat_owner[(event, s)]
                return httpx.Response(200, json={"status": "AVAILABLE"})
        return httpx.Response(404, json={"code": "NOT_FOUND", "message": action})

    def _payment(self, body, headers):
        key = headers.get("Idempotency-Key")
        if self.payment_mode == "down":
            return httpx.Response(503, json={"code": "PAYMENT_GATEWAY_UNAVAILABLE",
                                             "message": "Gateway is down", "correlationId": "-"})
        if self.payment_mode == "timeout":
            raise httpx.ReadTimeout("payment timed out")
        with self.lock:
            if key in self.payments:                         # Payment's own idempotency
                return httpx.Response(200, json=self.payments[key])
        time.sleep(self.payment_delay)
        with self.lock:
            self.charge_calls += 1
            resp = {"paymentId": f"pay-{self.charge_calls}", "bookingId": body["bookingId"],
                    "amount": body["amount"], "status": "APPROVED"}
            self.payments[key] = resp
        return httpx.Response(201, json=resp)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """SQLite by default. Set TEST_DB_URL to run the same tests on MySQL, e.g.
    TEST_DB_URL=mysql+pymysql://booking_user:booking_pass@localhost:3306/booking_db
    (WARNING: the tables in that database are dropped and recreated for every test)."""
    url = os.getenv("TEST_DB_URL")
    engine = db.init_engine(url or f"sqlite:///{tmp_path / 'booking_test.db'}")
    if url:
        db.metadata.drop_all(engine)
        db.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture
def fake(monkeypatch):
    services = FakeServices()
    monkeypatch.setattr(clients.httpx, "post", services.post)
    return services


class Clock:
    """Controllable clock: clock_.advance(31) moves time forward 31 seconds."""

    def __init__(self):
        self.current = clock.now()

    def now(self):
        return self.current

    def advance(self, seconds):
        self.current += timedelta(seconds=seconds)


@pytest.fixture
def clock_(monkeypatch):
    c = Clock()
    monkeypatch.setattr(clock, "now", c.now)
    return c


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def new_booking(client, fake):
    def _make(seats=("A1",), event_id=1, email="asha@example.com"):
        r = client.post("/api/v1/bookings", json={"eventId": event_id, "seats": list(seats),
                                                  "customerEmail": email})
        assert r.status_code == 201, r.text
        return r.json()
    return _make
