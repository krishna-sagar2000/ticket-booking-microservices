# Seat Service

Owner: Anwesa    Review partner: Booking owner

Keeps seat availability for events, never lets a seat go to two bookings, and releases holds that expire. Rules: **BR1** (a seat belongs to one booking at a time) and **BR2** (a hold expires after `HOLD_SECONDS`; a paid seat is never released). Called only by booking-service. It makes no outbound calls.

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

On startup the service runs `schema.sql` (tables) and `seed.sql` (event 1, seats A1-A5 and B1-B5), then starts the expiry job. Both files are safe to re-run: restarting never resets seats.

Settings (`.env`): `PORT`, `DB_URL`, `HOLD_SECONDS` (30), `EXPIRY_INTERVAL_SECONDS` (5, how often the expiry job runs).

### Reset the seats (fresh demo / after a schema change)
```
docker exec ticket-mysql mysql -u seat_user -pseat_pass seat_db -e "DROP TABLE IF EXISTS seats, events"
```
Then restart the service; it recreates and re-seeds both tables. Only local test data is lost.

## Test
```
pytest
```
Tests build an in-memory SQLite database from the same `schema.sql` and `seed.sql` (`tests/conftest.py`), so they need no Docker/MySQL. The race-condition proof needs real MySQL: see `evidence/challenge-1-concurrency/`.

## API (all under `/api/v1`; OpenAPI: `docs/openapi/seat-service.json`)

| Method | Path | Body | Success | Errors |
|---|---|---|---|---|
| GET | `/events/{eventId}/seats` | - | 200 `[{seatNo, status, bookingId, holdExpiresAt}]` | 404 `EVENT_NOT_FOUND` |
| POST | `/seats/hold` | `{"bookingId", "eventId", "seats": ["A1","A2"]}` | 200 `{bookingId, eventId, seats, status:"HELD", holdExpiresAt}` | 409 `SEAT_UNAVAILABLE`, 404 `EVENT_NOT_FOUND` / `SEAT_NOT_FOUND` |
| POST | `/seats/confirm` | same | 200 `{..., status:"SOLD"}` | 409 `HOLD_EXPIRED`, 404 |
| POST | `/seats/release` | same | 200 `{..., status:"AVAILABLE", releasedCount}` | 404 |
| POST | `/seats/expire-holds` | - | 200 `{expiredCount}` | - |

- **hold** is all or none: if any seat is not AVAILABLE (or does not exist), no seat is held. The 409 message names the taken seat, e.g. `"Seat A2 is already held"`. `holdExpiresAt` is UTC, whole seconds (`"2026-10-22T19:10:31Z"`), now + `HOLD_SECONDS`.
- **confirm** succeeds only if every seat is HELD by this booking and the hold has not expired (otherwise 409 `HOLD_EXPIRED`, nothing changes). Confirming again for the same booking returns 200, so booking-service can retry safely.
- **release** frees this booking's HELD seats and returns how many it freed. It never frees a SOLD seat and never touches another booking's seat. Releasing again returns 200 with `releasedCount: 0`.
- **expire-holds** runs the BR2 sweep by hand. The background job already runs it every `EXPIRY_INTERVAL_SECONDS`; this endpoint is for demos and evidence.
- Validation (400 `VALIDATION_ERROR`): `bookingId` 1-64 chars, `eventId` >= 1, `seats` 1-10 seat numbers (1-10 chars each), no repeats.
- Errors use the shared body `{"code", "message", "correlationId"}`. Send `X-Correlation-Id`; it is echoed back and logged.

Seat states: `AVAILABLE -> HELD` (hold) `-> SOLD` (confirm), or `HELD -> AVAILABLE` (release, or the expiry job once `hold_expires_at` has passed). `SOLD` is final.

## How the rules are enforced
- **BR1:** hold is one `UPDATE seats SET status='HELD', ... WHERE event_id=? AND seat_no IN (...) AND status='AVAILABLE'` inside a transaction. If it changed fewer rows than seats requested, the transaction is rolled back. One statement means the database checks and changes each row under its row lock, so two bookings can never both win a seat. A single statement also locks rows in index order, so overlapping multi-seat holds cannot deadlock. See `evidence/challenge-1-concurrency/README.md`, which also has a demo of SELECT-then-UPDATE failing.
- **BR2:** `app/expiry_job.py` runs `UPDATE seats SET status='AVAILABLE', ... WHERE status='HELD' AND hold_expires_at < now` every few seconds. It only matches expired HELD rows, so a SOLD seat is never released, and running it twice (or in several workers at once) is harmless. confirm also refuses an expired hold that the job has not swept yet.
- **Clock:** all times come from the seat service's own clock (UTC, written and compared by the same code), so a hold's expiry and its check never use different clocks.

## Where things go
- `schema.sql`, `seed.sql` - tables and sample data (also used by the tests)
- `app/main.py`  - app setup (shared; only the router include was added)
- `app/api/seats.py` - routes + request validation; startup applies the SQL files and starts the job
- `app/rules.py` - business rules (BR1 `hold_seats`, BR2 `confirm_seats` / `release_seats` / `expire_holds`)
- `app/expiry_job.py` - BR2 background job
- `app/db.py`    - the atomic queries (own DB only: `seat_db`)
- `tests/`       - `test_seats.py` (rule tests named `test_BR<n>_...`), `test_baseline.py`
