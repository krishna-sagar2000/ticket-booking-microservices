# Traceability: rule -> code -> test -> evidence

| Rule | Code (file: function) | Test | Evidence |
|---|---|---|---|
| BR1 | `services/seat-service/app/db.py: hold_seat` (atomic `UPDATE ... WHERE status='AVAILABLE'`); `app/rules.py: hold` (rowcount 0 -> 409 SEAT_UNAVAILABLE) | `services/seat-service/tests/test_seats.py`: `test_BR1_seat_cannot_be_held_twice`, `test_BR1_booked_seat_cannot_be_held`, `test_BR1_released_seat_can_be_held_again` | `evidence/challenge-1-concurrency/` (20 and 50 parallel holds -> exactly 1 x 200; `race_output.txt`, `db_dump.txt`, `README.md`) |
| BR2 | Seat side: `services/seat-service/app/db.py: expire_holds` (`UPDATE ... WHERE status='HELD' AND held_until < now`, never matches BOOKED); `app/rules.py: expire_holds` (`POST /api/v1/seats/expire-holds`). Booking side: _booking-service owner to add_ | `services/seat-service/tests/test_seats.py`: `test_BR2_expired_hold_is_released`, `test_BR2_paid_seat_is_not_released`, `test_BR2_unexpired_hold_is_kept`, `test_BR2_expire_twice_is_safe` | `evidence/challenge-3b-holds/`: seat side done (`seat_hold_expiry.py`, 8/8 PASS, `seat_db_dump.txt`); booking side pending |
| BR3 | | | |
| BR4 | | | |
