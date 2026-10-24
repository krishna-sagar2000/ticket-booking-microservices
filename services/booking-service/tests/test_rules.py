"""Unit tests of app/rules.py. No web server, no database."""
from datetime import datetime, timedelta

import pytest

from app import rules
from app.errors import AppError

NOW = datetime(2026, 10, 20, 12, 0, 0)


# ---------------------------------------------------------------- BR3
def test_BR3_cannot_pay_expired_booking():
    with pytest.raises(AppError) as e:
        rules.check_payable("HELD", NOW - timedelta(seconds=1), NOW)
    assert (e.value.status_code, e.value.code) == (409, "HOLD_EXPIRED")


def test_BR3_cannot_pay_at_the_exact_expiry_second():
    with pytest.raises(AppError) as e:
        rules.check_payable("HELD", NOW, NOW)
    assert e.value.code == "HOLD_EXPIRED"


def test_BR3_cannot_pay_booking_marked_expired():
    with pytest.raises(AppError) as e:
        rules.check_payable("EXPIRED", NOW + timedelta(seconds=10), NOW)
    assert e.value.code == "HOLD_EXPIRED"


@pytest.mark.parametrize("status", ["CONFIRMED", "CANCELLED"])
def test_BR3_cannot_pay_booking_that_is_not_held(status):
    with pytest.raises(AppError) as e:
        rules.check_payable(status, NOW + timedelta(seconds=10), NOW)
    assert (e.value.status_code, e.value.code) == (409, "BOOKING_NOT_PAYABLE")


def test_BR3_held_and_in_time_is_payable():
    rules.check_payable("HELD", NOW + timedelta(seconds=10), NOW)   # no error


# ------------------------------------------------------- state machine
@pytest.mark.parametrize("target", ["CONFIRMED", "CANCELLED", "EXPIRED"])
def test_state_held_can_move_to_each_final_state(target):
    rules.ensure_transition("HELD", target)


@pytest.mark.parametrize("current,target", [
    ("CONFIRMED", "CANCELLED"), ("CONFIRMED", "HELD"), ("CANCELLED", "CONFIRMED"),
    ("EXPIRED", "CONFIRMED"), ("EXPIRED", "CANCELLED"), ("HELD", "HELD"),
])
def test_state_invalid_change_is_rejected(current, target):
    with pytest.raises(AppError) as e:
        rules.ensure_transition(current, target)
    assert (e.value.status_code, e.value.code) == (409, "INVALID_STATE_CHANGE")


# ---------------------------------------------------------------- BR4
def test_BR4_same_request_gives_same_fingerprint():
    a = rules.request_fingerprint("POST", "/api/v1/bookings/b1/pay", {"x": 1, "y": 2})
    b = rules.request_fingerprint("post", "/api/v1/bookings/b1/pay", {"y": 2, "x": 1})
    assert a == b


def test_BR4_different_request_gives_different_fingerprint():
    a = rules.request_fingerprint("POST", "/api/v1/bookings/b1/pay", None)
    b = rules.request_fingerprint("POST", "/api/v1/bookings/b2/pay", None)
    assert a != b


def test_BR4_same_key_same_request_done_is_replayed():
    assert rules.check_idempotent_repeat("h1", "DONE", "h1") == "REPLAY"


def test_BR4_same_key_different_body_rejected_rule():
    with pytest.raises(AppError) as e:
        rules.check_idempotent_repeat("h1", "DONE", "h2")
    assert (e.value.status_code, e.value.code) == (422, "IDEMPOTENCY_KEY_REUSED")


def test_BR4_same_key_still_running_is_409():
    with pytest.raises(AppError) as e:
        rules.check_idempotent_repeat("h1", "IN_PROGRESS", "h1")
    assert (e.value.status_code, e.value.code) == (409, "REQUEST_IN_PROGRESS")


def test_BR4_retryable_errors_are_not_saved():
    assert not rules.is_final_outcome(503, "PAYMENT_GATEWAY_UNAVAILABLE")
    assert not rules.is_final_outcome(409, "PAYMENT_IN_PROGRESS")
    assert rules.is_final_outcome(409, "HOLD_EXPIRED")
    assert rules.is_final_outcome(200, None)


# ---------------------------------------------------- input validation
def test_seats_are_normalised():
    assert rules.check_requested_seats([" a1", "B2 "], 6) == ["A1", "B2"]


@pytest.mark.parametrize("seats", [[], [""], ["A1", "a1"], ["A1", "A2", "A3"]])
def test_bad_seat_lists_are_rejected(seats):
    with pytest.raises(AppError) as e:
        rules.check_requested_seats(seats, 2)
    assert (e.value.status_code, e.value.code) == (400, "VALIDATION_ERROR")


def test_amount_is_computed_by_server():
    assert rules.booking_amount(3, 250.0) == 750.0
