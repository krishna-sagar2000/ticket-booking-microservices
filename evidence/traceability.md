# Traceability: rule -> code -> test -> evidence

| Rule | Code (file: function) | Test | Evidence |
|---|---|---|---|
| BR1 | | | |
| BR2 | | | |
| BR3 | booking-service `app/rules.py: check_payable`; atomic guard `app/db.py: claim_for_payment` | `tests/test_rules.py: test_BR3_*`, `tests/test_booking_api.py: test_BR3_cannot_pay_expired_booking`, `test_BR3_cannot_pay_confirmed_booking_again`, `test_BR3_cannot_pay_cancelled_booking` | `scripts/e2e_booking_flow.py` scenarios 5 and 6 (to save in evidence/tests/) |
| BR4 (Booking side) | booking-service `app/booking_flow.py: pay_with_idempotency`; `app/rules.py: request_fingerprint, check_idempotent_repeat, is_final_outcome`; `app/db.py: idem_begin` (PK on idem_key) | `test_BR4_same_key_returns_same_result`, `test_BR4_same_key_different_body_rejected`, `test_BR4_two_identical_requests_at_the_same_moment_charge_once`, `test_two_different_keys_at_the_same_moment_charge_once` | `scripts/booking_idempotency_demo.py` output + DB query (to save in evidence/challenge-2-idempotency/) |
| BR4 (Payment side) | | | |
| State machine | booking-service `app/rules.py: ensure_transition`; `app/db.py: mark_confirmed, mark_cancelled, mark_expired` | `tests/test_rules.py: test_state_*`, `test_cancel_*` | e2e scenario 5 |
