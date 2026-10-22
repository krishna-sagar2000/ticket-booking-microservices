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

## Booking-service side (to do: booking + notification owners)
Same scenario end to end: create a booking, wait past `HOLD_SECONDS`, call `POST /api/v1/bookings/expire` and `POST /api/v1/seats/expire-holds`, show booking `EXPIRED` and seat `AVAILABLE`, and show that a paid (`CONFIRMED`) booking and its `BOOKED` seat are untouched.
