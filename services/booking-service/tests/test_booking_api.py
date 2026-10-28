"""Endpoint and flow tests. Seat, Payment and Notification are faked (see conftest.py)."""
import threading

from fastapi.testclient import TestClient

from app import db
from app.main import app

PAY = "/api/v1/bookings/{}/pay"


def pay(client, booking_id, key):
    return client.post(PAY.format(booking_id), headers={"Idempotency-Key": key})


# ------------------------------------------------------------------ create
def test_create_booking_holds_seats_and_returns_201(client, fake):
    r = client.post("/api/v1/bookings",
                    json={"eventId": 1, "seats": ["A1", "A2"], "customerEmail": "a@x.com"})
    assert r.status_code == 201
    b = r.json()
    assert b["status"] == "HELD" and b["seats"] == ["A1", "A2"] and b["amount"] == 500.0
    assert b["holdExpiresAt"].endswith("Z")
    assert fake.seat_owner[(1, "A1")] == b["bookingId"]


def test_create_booking_accepts_snake_case_fields(client, fake):
    r = client.post("/api/v1/bookings",
                    json={"event_id": 1, "seats": ["A1"], "customer_email": "a@x.com"})
    assert r.status_code == 201


def test_create_booking_seat_taken_returns_409(client, new_booking):
    new_booking(seats=["A1"])
    r = client.post("/api/v1/bookings",
                    json={"eventId": 1, "seats": ["A1"], "customerEmail": "b@x.com"})
    assert r.status_code == 409
    assert r.json()["code"] == "SEAT_UNAVAILABLE"
    assert db.count_by_status() == {"HELD": 1}          # no second booking row


def test_create_booking_validation_errors_use_shared_format(client, fake):
    bad_bodies = [
        {"eventId": 1, "seats": [], "customerEmail": "a@x.com"},
        {"eventId": 1, "seats": ["A1", "A1"], "customerEmail": "a@x.com"},
        {"eventId": 0, "seats": ["A1"], "customerEmail": "a@x.com"},
        {"eventId": 1, "seats": ["A1"], "customerEmail": "not-an-email"},
        {"seats": ["A1"]},
    ]
    for body in bad_bodies:
        r = client.post("/api/v1/bookings", json=body, headers={"X-Correlation-Id": "t-1"})
        assert r.status_code == 400, body
        assert r.json() == {"code": "VALIDATION_ERROR", "message": r.json()["message"],
                            "correlationId": "t-1"}


def test_create_booking_seat_service_down_returns_503(client, fake):
    fake.seat_down = True
    r = client.post("/api/v1/bookings",
                    json={"eventId": 1, "seats": ["A1"], "customerEmail": "a@x.com"})
    assert r.status_code == 503
    assert r.json()["code"] == "SEAT_SERVICE_UNAVAILABLE"
    assert db.count_by_status() == {}


def test_get_unknown_booking_is_404(client, fake):
    r = client.get("/api/v1/bookings/does-not-exist")
    assert r.status_code == 404 and r.json()["code"] == "BOOKING_NOT_FOUND"


# --------------------------------------------------------------------- pay
def test_pay_happy_path_confirms_seats_and_notifies(client, fake, new_booking):
    b = new_booking(seats=["A1", "A2"])
    r = pay(client, b["bookingId"], "key-1")
    assert r.status_code == 200
    assert r.json()["status"] == "CONFIRMED" and r.json()["paymentId"] == "pay-1"
    assert {(1, "A1"), (1, "A2")} <= fake.sold
    assert fake.notifications[0]["type"] == "BOOKING_CONFIRMED"
    assert fake.charge_calls == 1


def test_pay_requires_idempotency_key(client, new_booking):
    b = new_booking()
    r = client.post(PAY.format(b["bookingId"]))
    assert r.status_code == 400 and r.json()["code"] == "VALIDATION_ERROR"


def test_BR3_cannot_pay_expired_booking(client, fake, clock_, new_booking):
    b = new_booking()
    clock_.advance(31)
    r = pay(client, b["bookingId"], "key-late")
    assert r.status_code == 409 and r.json()["code"] == "HOLD_EXPIRED"
    assert fake.charge_calls == 0                                   # no money taken
    assert client.get(f"/api/v1/bookings/{b['bookingId']}").json()["status"] == "EXPIRED"


def test_BR3_cannot_pay_confirmed_booking_again(client, fake, new_booking):
    b = new_booking()
    assert pay(client, b["bookingId"], "key-1").status_code == 200
    r = pay(client, b["bookingId"], "key-2")                        # NEW key, same booking
    assert r.status_code == 409 and r.json()["code"] == "BOOKING_NOT_PAYABLE"
    assert fake.charge_calls == 1


def test_BR3_cannot_pay_cancelled_booking(client, fake, new_booking):
    b = new_booking()
    client.post(f"/api/v1/bookings/{b['bookingId']}/cancel")
    r = pay(client, b["bookingId"], "key-1")
    assert r.status_code == 409 and r.json()["code"] == "BOOKING_NOT_PAYABLE"


def test_pay_gateway_down_returns_503_and_booking_stays_held(client, fake, new_booking):
    b = new_booking()
    fake.payment_mode = "down"
    r = pay(client, b["bookingId"], "key-1")
    assert r.status_code == 503 and r.json()["code"] == "PAYMENT_GATEWAY_UNAVAILABLE"
    assert client.get(f"/api/v1/bookings/{b['bookingId']}").json()["status"] == "HELD"
    assert not fake.sold

    # Gateway comes back: the SAME key can be retried, because a 503 is not saved.
    fake.payment_mode = "ok"
    r = pay(client, b["bookingId"], "key-1")
    assert r.status_code == 200 and r.json()["status"] == "CONFIRMED"
    assert fake.charge_calls == 1


def test_pay_payment_service_timeout_returns_503(client, fake, new_booking):
    b = new_booking()
    fake.payment_mode = "timeout"
    r = pay(client, b["bookingId"], "key-1")
    assert r.status_code == 503 and r.json()["code"] == "PAYMENT_SERVICE_UNAVAILABLE"
    assert client.get(f"/api/v1/bookings/{b['bookingId']}").json()["status"] == "HELD"


def test_pay_notification_down_still_confirms(client, fake, new_booking):
    b = new_booking()
    fake.notification_down = True
    r = pay(client, b["bookingId"], "key-1")
    assert r.status_code == 200 and r.json()["status"] == "CONFIRMED"


def test_pay_seat_down_after_charge_retry_with_same_key_does_not_charge_twice(
        client, fake, new_booking):
    b = new_booking()
    fake.seat_down = True
    r = pay(client, b["bookingId"], "key-1")
    assert r.status_code == 503 and r.json()["code"] == "SEAT_SERVICE_UNAVAILABLE"
    assert client.get(f"/api/v1/bookings/{b['bookingId']}").json()["status"] == "HELD"

    fake.seat_down = False
    r = pay(client, b["bookingId"], "key-1")
    assert r.status_code == 200 and r.json()["status"] == "CONFIRMED"
    assert fake.charge_calls == 1          # Payment replayed the first charge


def test_pay_when_seat_already_released_reports_refund_needed(client, fake, clock_, new_booking):
    b = new_booking()
    fake.seat_confirm_reject = True        # Seat expired the hold just before confirm
    clock_.advance(29)
    original_charge = fake._payment

    def charge_then_time_passes(body, headers):
        resp = original_charge(body, headers)
        clock_.advance(2)                  # payment took 2 s; the hold ran out meanwhile
        return resp
    fake._payment = charge_then_time_passes

    r = pay(client, b["bookingId"], "key-1")
    assert r.status_code == 409 and r.json()["code"] == "HOLD_EXPIRED"
    assert "refund" in r.json()["message"]
    assert client.get(f"/api/v1/bookings/{b['bookingId']}").json()["status"] == "EXPIRED"


def test_correlation_id_is_passed_to_every_service(client, fake, new_booking):
    r = client.post("/api/v1/bookings", headers={"X-Correlation-Id": "trace-42"},
                    json={"eventId": 1, "seats": ["B1"], "customerEmail": "a@x.com"})
    client.post(PAY.format(r.json()["bookingId"]),
                headers={"Idempotency-Key": "k", "X-Correlation-Id": "trace-43"})
    ids = {path: headers["X-Correlation-Id"] for path, _, headers in fake.calls}
    assert ids["/api/v1/seats/hold"] == "trace-42"
    assert ids["/api/v1/payments"] == "trace-43"
    assert ids["/api/v1/seats/confirm"] == "trace-43"
    assert ids["/api/v1/notifications"] == "trace-43"


def test_payment_receives_the_same_idempotency_key(client, fake, new_booking):
    b = new_booking()
    pay(client, b["bookingId"], "client-key-7")
    pay_call = [h for p, _, h in fake.calls if p == "/api/v1/payments"][0]
    assert pay_call["Idempotency-Key"] == "client-key-7"


# --------------------------------------------------------------- BR4 / Challenge 2
def test_BR4_same_key_returns_same_result(client, fake, new_booking):
    b = new_booking()
    first = pay(client, b["bookingId"], "key-1")
    second = pay(client, b["bookingId"], "key-1")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.headers["Idempotent-Replayed"] == "false"
    assert second.headers["Idempotent-Replayed"] == "true"
    assert fake.charge_calls == 1
    assert len([p for p, _, _ in fake.calls if p == "/api/v1/payments"]) == 1


def test_BR4_same_key_different_body_rejected(client, fake, new_booking):
    b1, b2 = new_booking(seats=["A1"]), new_booking(seats=["A2"])
    assert pay(client, b1["bookingId"], "key-1").status_code == 200
    r = pay(client, b2["bookingId"], "key-1")             # same key, different request
    assert r.status_code == 422 and r.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert fake.charge_calls == 1


def test_BR4_saved_error_is_replayed_too(client, fake, clock_, new_booking):
    b = new_booking()
    clock_.advance(31)
    first = pay(client, b["bookingId"], "key-1")
    second = pay(client, b["bookingId"], "key-1")
    assert first.status_code == second.status_code == 409
    assert first.json()["code"] == second.json()["code"] == "HOLD_EXPIRED"
    assert second.headers["Idempotent-Replayed"] == "true"


def _parallel(n, fn):
    barrier = threading.Barrier(n)
    results = [None] * n

    def run(i):
        barrier.wait()
        results[i] = fn(i)
    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_BR4_two_identical_requests_at_the_same_moment_charge_once(fake, new_booking):
    b = new_booking()
    fake.payment_delay = 0.5               # keep the first request busy

    results = _parallel(2, lambda i: pay(TestClient(app), b["bookingId"], "same-key"))
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409]
    busy = [r for r in results if r.status_code == 409][0]
    assert busy.json()["code"] == "REQUEST_IN_PROGRESS"
    assert fake.charge_calls == 1


def test_two_different_keys_at_the_same_moment_charge_once(fake, new_booking):
    b = new_booking()
    fake.payment_delay = 0.5

    results = _parallel(2, lambda i: pay(TestClient(app), b["bookingId"], f"key-{i}"))
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409]
    assert [r for r in results if r.status_code == 409][0].json()["code"] == "PAYMENT_IN_PROGRESS"
    assert fake.charge_calls == 1


# ------------------------------------------------------------------ cancel
def test_cancel_held_booking_releases_seats(client, fake, new_booking):
    b = new_booking(seats=["A1"])
    r = client.post(f"/api/v1/bookings/{b['bookingId']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    assert (1, "A1") not in fake.seat_owner
    assert fake.notifications[-1]["type"] == "BOOKING_CANCELLED"


def test_cancel_confirmed_booking_is_invalid_state_change(client, fake, new_booking):
    b = new_booking()
    pay(client, b["bookingId"], "key-1")
    r = client.post(f"/api/v1/bookings/{b['bookingId']}/cancel")
    assert r.status_code == 409 and r.json()["code"] == "INVALID_STATE_CHANGE"
    assert (1, "A1") in fake.sold                       # paid seat never released


def test_cancel_twice_is_invalid_state_change(client, fake, new_booking):
    b = new_booking()
    client.post(f"/api/v1/bookings/{b['bookingId']}/cancel")
    r = client.post(f"/api/v1/bookings/{b['bookingId']}/cancel")
    assert r.status_code == 409 and r.json()["code"] == "INVALID_STATE_CHANGE"


def test_cancel_still_succeeds_when_seat_service_is_down(client, fake, new_booking):
    b = new_booking()
    fake.seat_down = True
    r = client.post(f"/api/v1/bookings/{b['bookingId']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"


# ------------------------------------------------------------------ expire
def test_expire_marks_only_overdue_held_bookings_and_is_safe_twice(client, fake, clock_,
                                                                    new_booking):
    paid = new_booking(seats=["A1"])
    pay(client, paid["bookingId"], "key-1")
    cancelled = new_booking(seats=["A2"])
    client.post(f"/api/v1/bookings/{cancelled['bookingId']}/cancel")
    overdue = new_booking(seats=["A3"])

    assert client.post("/api/v1/bookings/expire").json() == {"expiredCount": 0}
    clock_.advance(31)
    fresh = new_booking(seats=["A4"])

    assert client.post("/api/v1/bookings/expire").json() == {"expiredCount": 1}
    assert client.post("/api/v1/bookings/expire").json() == {"expiredCount": 0}   # run twice

    status = {k: client.get(f"/api/v1/bookings/{v['bookingId']}").json()["status"]
              for k, v in {"paid": paid, "cancelled": cancelled,
                           "overdue": overdue, "fresh": fresh}.items()}
    assert status == {"paid": "CONFIRMED", "cancelled": "CANCELLED",
                      "overdue": "EXPIRED", "fresh": "HELD"}
