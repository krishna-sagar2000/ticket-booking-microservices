# Challenge 1: Concurrency (BR1: a seat belongs to one booking at a time)

## Result

| Run | Parallel `POST /api/v1/seats/{id}/hold` | 200 | 409 `SEAT_UNAVAILABLE` | Final row |
|---|---|---|---|---|
| 1 | 20 on seat 5 | 1 (`race-00`) | 19 | `HELD`, `booking_id = race-00` |
| 2 | 50 on seat 6 | 1 (`race-19`) | 49 | `HELD`, `booking_id = race-19` |

seat-service ran as **4 separate uvicorn worker processes** (`--workers 4`), so no in-process lock could have serialised these requests. Only the database did.

## Files

| File | What it shows |
|---|---|
| `race_hold.py` | Test script. N threads wait on a `threading.Barrier`, then all send `POST /hold` for the same seat at once, each with a different `bookingId`. It checks for exactly one 200, N-1 409s, and that the seat is held by the winner. |
| `race_output.txt` | Raw output of both runs (run 2 omits the per-request lines) |
| `db_dump.txt` | `SELECT * FROM seat_db.seats` right after the runs: one consistent row per seat, held by the winning booking |
| `service_log_excerpt.txt` | seat-service JSON log lines for run 1. The correlation IDs (`race-5-NN`) match the requests: one `response 200` (`race-5-00`, the winner) and the rest `response 409` |
| `naive_select_then_update.py`, `naive_output.txt` | Contrast demo of the anti-pattern below. 20 requests, **20 told they got the seat** |

Reproduce from the repo root, with MySQL and seat-service running:
```
services/seat-service/.venv/Scripts/python evidence/challenge-1-concurrency/race_hold.py --seat 5 --n 20
services/seat-service/.venv/Scripts/python evidence/challenge-1-concurrency/naive_select_then_update.py
```

## How seat-service holds a seat

`services/seat-service/app/db.py: hold_seat` runs one statement:

```sql
UPDATE seats SET status='HELD', booking_id=:bid, held_until=:t
WHERE id=:seat_id AND status='AVAILABLE'
```

`app/rules.py: hold` then checks the affected row count. **1** means this request won. **0** means the seat was not AVAILABLE, so it raises `AppError(409, "SEAT_UNAVAILABLE")` (or 404 if the seat does not exist).

The check (`status='AVAILABLE'`) and the change (`SET status='HELD'`) are one atomic operation inside MySQL:
1. InnoDB takes an exclusive row lock on the seat before it evaluates the `WHERE`.
2. While the first request holds the lock, every other `UPDATE` on that row waits.
3. When the first commits, each waiting `UPDATE` re-reads the latest committed row. It now sees `status='HELD'`, so the `WHERE` no longer matches and it changes 0 rows.

No two requests can both see `AVAILABLE` and both write.

## Why "SELECT then UPDATE" in application code fails

```python
status = SELECT status FROM seats WHERE id = ?      # 1. check
if status == 'AVAILABLE':                            #    (decided in Python)
    UPDATE seats SET status='HELD', booking_id = ?   # 2. act
```

Between step 1 and step 2 the decision is made in Python on a value that may already be stale. Nothing stops other requests from running step 1 in that gap:

```
time   request A                 request B
 t1    SELECT -> AVAILABLE
 t2                              SELECT -> AVAILABLE    (A has not written yet)
 t3    UPDATE -> HELD by A
 t4                              UPDATE -> HELD by B    (overwrites A, no re-check)
       A and B are both told "200, seat held"
```

`naive_select_then_update.py` does exactly this against the real `seat_db`. With 20 concurrent requests, **all 20 passed the check and were told they held the seat**. The row ended up holding only the last writer (`naive-10`), so 19 customers would have proceeded to payment for a seat that belongs to someone else.

The gap is never zero in a real service: network round trips, validation, logging and multiple workers all widen it. The demo adds a 50 ms pause to make it visible on every run. MySQL's default isolation level (REPEATABLE READ) does not help, because a plain `SELECT` takes no lock. Fixing it in Python with a `threading.Lock` would also fail, because each of the 4 worker processes (and every other instance of the service) has its own lock.

Correct alternatives are:
- the conditional `UPDATE` used here (simplest: one round trip, no explicit transaction)
- `SELECT ... FOR UPDATE` inside a transaction (pessimistic lock, two statements)
- a version column with optimistic retry
