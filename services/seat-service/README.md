# Seat Service

Owner: Anwesa    Review partner: ________

Owns the seat inventory and hold state in `seat_db`. Rules: **BR1** (a seat belongs to one booking at a time) and **BR2** (holds expire, a booked seat is never released). Called by booking-service. It makes no outbound calls.

## Run (from this folder)
```
python -m venv .venv
.venv\Scripts\activate          (Windows)   |   source .venv/bin/activate (Mac/Linux)
pip install -r requirements.txt
copy .env.example .env           (Windows)   |   cp .env.example .env
uvicorn app.main:app --port 8002 --reload
```
Check: http://127.0.0.1:8002/health  and  http://127.0.0.1:8002/docs
(On Windows use `127.0.0.1`, not `localhost`: `localhost` adds ~2 s per request.)

On startup the service creates the `seats` table and seeds seats A1-A10 (ids 1-10) if they are missing. Restarting never resets existing seats.

## Test
```
pytest
```
Tests use an in-memory SQLite database (`tests/conftest.py`), so they need no Docker/MySQL. The race-condition proof needs real MySQL: see `evidence/challenge-1-concurrency/`.

## API (`/api/v1/seats`)

| Method | Path | Body | Success | Errors |
|---|---|---|---|---|
| GET | `/api/v1/seats` | - | 200 `[{seatId, label, status, bookingId, holdExpiresAt}]` | - |
| POST | `/api/v1/seats/{id}/hold` | `{"bookingId": "..."}` | 200 `{seatId, status:"HELD", holdExpiresAt}` | 409 `SEAT_UNAVAILABLE` (not AVAILABLE), 404 `SEAT_NOT_FOUND` |
| POST | `/api/v1/seats/{id}/confirm` | `{"bookingId": "..."}` | 200 `{seatId, status:"BOOKED"}` | 409 `INVALID_STATE_CHANGE` (not HELD by this booking), 404 `SEAT_NOT_FOUND` |
| POST | `/api/v1/seats/{id}/release` | `{"bookingId": "..."}` | 200 `{seatId, status:"AVAILABLE"}` | 409 `INVALID_STATE_CHANGE` (not HELD by this booking), 404 `SEAT_NOT_FOUND` |
| POST | `/api/v1/seats/expire-holds` | - | 200 `{expiredCount: N}` | - |

- `bookingId` is a string of 1-64 characters. A number (`42`) is also accepted and stored as `"42"`. A missing or invalid body, or a non-integer seat id, returns 400 `VALIDATION_ERROR`.
- `holdExpiresAt` is UTC ISO-8601 in whole seconds, e.g. `"2026-10-22T19:10:31Z"` (now + `HOLD_SECONDS`).
- Seat states: `AVAILABLE -> HELD` (hold), `HELD -> BOOKED` (confirm), `HELD -> AVAILABLE` (release, or expire-holds once `holdExpiresAt` has passed). `BOOKED` is final: it cannot be released or expired.
- `confirm` does not check `holdExpiresAt`. booking-service enforces BR3 (`HOLD_EXPIRED`) before calling it. A hold that has passed its expiry but has not been swept yet can still be confirmed by its own booking.
- `expire-holds` is safe to call any number of times. The second call returns `expiredCount: 0`.
- Errors use the shared body `{"code", "message", "correlationId"}`. Send `X-Correlation-Id`; it is echoed back and logged.

## How BR1 is enforced
Every state change is a single conditional `UPDATE` whose `WHERE` clause is the rule. The rowcount decides the outcome (1 = success, 0 = refused). Nothing is checked in Python and then updated (`app/db.py`). For why this is race-free, and a demo of the SELECT-then-UPDATE alternative failing, see `evidence/challenge-1-concurrency/README.md`.

## Where things go
- `app/main.py`  - app setup (shared; only the router include was added)
- `app/api/seats.py` - routes + request validation; startup creates/seeds the table
- `app/rules.py` - business rules (BR1 `hold`, BR2 `expire_holds`, plus `confirm` / `release`)
- `app/db.py`    - `seats` model, seeding, and the atomic queries (own DB only: `seat_db`)
- `tests/`       - `test_seats.py` (rule tests named `test_BR<n>_...`), `test_baseline.py`
