# Challenge 3B: Time-bound holds (BR2)

## Seat-service side (done)

`seat_hold_expiry.py` drives seat-service through its public API with `HOLD_SECONDS=30`. Result: **PASS, 8/8 checks** (`seat_hold_expiry_output.txt`).

| Step | Expected | Observed |
|---|---|---|
| Hold seat 1 (unpaid); hold and confirm seat 2 (paid) | 200, 200, 200 BOOKED | as expected |
| `expire-holds` before 30 s | `expiredCount: 0`, seat 1 still HELD | as expected |
| `expire-holds` after `holdExpiresAt` | `expiredCount: 1`, seat 1 AVAILABLE, **seat 2 still BOOKED** | as expected |
| `expire-holds` again | `expiredCount: 0` (safe to run twice) | as expected |
| Expired booking tries to confirm seat 1 | 409 `INVALID_STATE_CHANGE` | as expected |
| New booking holds seat 1 | 200 | as expected |

`seat_db_dump.txt` shows the table afterwards: seat 1 AVAILABLE, seat 2 BOOKED by `exp-paid`.

Why a paid seat is safe: the sweep is one statement, `UPDATE seats ... WHERE status='HELD' AND held_until < :now` (`services/seat-service/app/db.py: expire_holds`). Confirm sets `status='BOOKED'` and clears `held_until`, so a BOOKED row can never match. The sweep is also race-free with a concurrent confirm: whichever `UPDATE` takes the row lock first wins, and the other re-checks the row and matches 0 rows.

Reproduce from the repo root, with MySQL and seat-service running (takes ~35 s):
```
services/seat-service/.venv/Scripts/python evidence/challenge-3b-holds/seat_hold_expiry.py
```

## Booking-service side (done)

`booking_hold_expiry.py` drives the whole system through Booking's public API, with all five services running and `HOLD_SECONDS=30` in booking and seat. Result: **PASS, 14/14 checks** (`booking_hold_expiry_output.txt`).

| Step | Expected | Observed |
|---|---|---|
| Booking UNPAID holds a seat; booking PAID holds a seat and pays | 201 HELD, 201 HELD, 200 CONFIRMED | as expected |
| `POST /bookings/expire` before 30 s | `expiredCount: 0`, UNPAID still HELD | as expected |
| `POST /bookings/expire` after UNPAID's `holdExpiresAt` | `expiredCount: 1`, UNPAID **EXPIRED**, **PAID still CONFIRMED** | as expected |
| `POST /bookings/expire` again | 200, `expiredCount: 0` (safe to run twice) | as expected |
| Pay the EXPIRED booking | 409 `HOLD_EXPIRED` (BR3) | as expected |
| Pay the CONFIRMED booking again / cancel it | 409 `BOOKING_NOT_PAYABLE` / 409 `INVALID_STATE_CHANGE` | as expected |
| Seat service view | UNPAID's seat AVAILABLE (freed by Seat's expiry: its background job or the expire-holds sweep, whichever runs first), PAID's seat SOLD | as expected |
| Book UNPAID's seat again | 201 | as expected |

`booking_db_dump.txt` shows the `bookings` rows before, during and after expiry: UNPAID goes `HELD -> EXPIRED`, PAID stays `CONFIRMED` with its `updated_at` unchanged.

Why a paid booking is safe: expiry is one statement, `UPDATE bookings SET status='EXPIRED' WHERE status='HELD' AND hold_expires_at <= :now AND (pay_lock IS NULL OR pay_locked_at < :stale)` (`services/booking-service/app/db.py: expire_due_bookings`, called by `app/booking_flow.py: expire_due`). A CONFIRMED or CANCELLED row can never match, so running it twice changes nothing. A booking that is being paid at that moment holds `pay_lock` and is skipped, so expiry cannot race a payment in flight. Reads (`GET`, pay, cancel) also expire an overdue booking on the spot (`booking_flow._load`), so a client never sees a stale HELD.

Booking and Seat each expire their own data (database per service): Booking never touches `seat_db`. Booking sets its `hold_expires_at` *before* asking Seat to hold, so Booking's deadline is never later than Seat's and Booking will not accept a payment for a hold Seat has already freed.

Unit tests: `services/booking-service/tests/test_booking_api.py: test_expire_marks_only_overdue_held_bookings_and_is_safe_twice`, `test_BR3_cannot_pay_expired_booking`; `tests/test_rules.py: test_BR3_*`.

Reproduce from the repo root, with MySQL and all five services running (takes ~35 s):
```
services/booking-service/.venv/bin/python evidence/challenge-3b-holds/booking_hold_expiry.py \
    --out evidence/challenge-3b-holds/booking_hold_expiry_output.txt \
    --dump evidence/challenge-3b-holds/booking_db_dump.txt
```
(Windows: `services\booking-service\.venv\Scripts\python ...`). It needs two AVAILABLE seats in event 1 and picks them itself.
