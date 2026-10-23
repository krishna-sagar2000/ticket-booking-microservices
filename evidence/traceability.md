# Traceability: rule -> code -> test -> evidence

| Rule | Code (file: function) | Test | Evidence |
|---|---|---|---|
| BR1 | `services/seat-service/app/db.py: hold_seats` (one `UPDATE ... WHERE seat_no IN (...) AND status='AVAILABLE'`, rolled back unless every seat matched); `app/rules.py: hold_seats` (refused -> 409 SEAT_UNAVAILABLE) | `services/seat-service/tests/test_seats.py`: `test_BR1_seat_cannot_be_held_twice`, `test_BR1_hold_is_all_or_nothing`, `test_BR1_hold_with_unknown_seat_holds_nothing`, `test_BR1_sold_seat_cannot_be_held`, `test_BR1_released_seat_can_be_held_again` | `evidence/challenge-1-concurrency/` (`race_hold.py`, `race_output.txt`, `db_dump.txt`, `README.md`) |
| BR2 | Seat side: `services/seat-service/app/expiry_job.py: run_forever` -> `app/rules.py: expire_holds` -> `app/db.py: expire_holds` (`UPDATE ... WHERE status='HELD' AND hold_expires_at < now`, never matches SOLD); `app/rules.py: confirm_seats` (expired hold -> 409 HOLD_EXPIRED), `release_seats` (never frees SOLD). Booking side: _booking-service owner to add_ | `services/seat-service/tests/test_seats.py`: `test_BR2_expired_hold_is_released`, `test_BR2_paid_seat_is_not_released`, `test_BR2_unexpired_hold_is_kept`, `test_BR2_expire_twice_is_safe`, `test_BR2_expired_hold_cannot_be_confirmed`, `test_BR2_background_job_releases_expired_holds` | `evidence/challenge-3b-holds/`: seat side (`seat_hold_expiry.py`, `seat_hold_expiry_output.txt`, `seat_db_dump.txt`); booking side pending |
| BR3 | | | |
| BR4 | | | |
