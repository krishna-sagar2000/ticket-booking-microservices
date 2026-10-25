# Booking Service (port 8001, `booking_db`)

Owner: Aishwarya    Review partner: Krishna Sagar (Notification owner)

**One sentence:** runs the booking lifecycle (HELD → CONFIRMED / CANCELLED / EXPIRED), enforces BR3 and the Booking side of BR4, and coordinates Seat, Payment and Notification over REST.

The client talks only to this service. It is the only service that calls others.
Full design explanation: [`docs/booking-service-design.md`](../../docs/booking-service-design.md).

## Run (from this folder)
```
python -m venv .venv
.venv\Scripts\activate          (Windows)   |   source .venv/bin/activate (Mac/Linux)
pip install -r requirements.txt
copy .env.example .env           (Windows)   |   cp .env.example .env
uvicorn app.main:app --port 8001 --reload
```
Check http://localhost:8001/health and http://localhost:8001/docs.
Tables are created on first start if missing; `schema.sql` is the same definition for the report and for manual setup:
`mysql -u booking_user -pbooking_pass booking_db < schema.sql`

## Test
```
pytest                       # 60 tests, SQLite + faked Seat/Payment/Notification, no MySQL needed
```
To run the same tests on MySQL (drops and recreates the booking tables!):
```
set TEST_DB_URL=mysql+pymysql://booking_user:booking_pass@localhost:3306/booking_db   (Windows)
export TEST_DB_URL=...                                                                  (Mac/Linux)
pytest
```

## Run the whole flow before teammates are ready
`dev/stubs.py` has in-memory stand-ins for Seat, Payment and Notification (dev only, not part of the system). In four terminals (venv active):
```
uvicorn dev.stubs:seat_app --port 8002
uvicorn dev.stubs:payment_app --port 8003
uvicorn dev.stubs:notification_app --port 8004
cd ../mock-gateway && uvicorn app.main:app --port 8005
```
Then from the repo root: `python scripts/e2e_booking_flow.py` and `python scripts/booking_idempotency_demo.py`.
`dev/sample-run/` holds the output of one such run with the stubs. **It is not evidence** — regenerate the outputs with the real services on integration day.

## Endpoints (all under `/api/v1`)
| Method | Path | Body / header | Success | Errors |
|---|---|---|---|---|
| POST | `/bookings` | `{"eventId":1,"seats":["A1","A2"],"customerEmail":"a@x.com"}` | 201 booking, `HELD` | 400 VALIDATION_ERROR, 409 SEAT_UNAVAILABLE, 503 SEAT_SERVICE_UNAVAILABLE |
| GET | `/bookings/{id}` | – | 200 booking | 404 BOOKING_NOT_FOUND |
| POST | `/bookings/{id}/pay` | header `Idempotency-Key` | 200 booking, `CONFIRMED` | 400, 404, 409 BOOKING_NOT_PAYABLE / HOLD_EXPIRED / REQUEST_IN_PROGRESS / PAYMENT_IN_PROGRESS, 422 IDEMPOTENCY_KEY_REUSED, 503 PAYMENT_GATEWAY_UNAVAILABLE / PAYMENT_SERVICE_UNAVAILABLE / SEAT_SERVICE_UNAVAILABLE |
| POST | `/bookings/{id}/cancel` | – | 200 booking, `CANCELLED` | 404, 409 INVALID_STATE_CHANGE / PAYMENT_IN_PROGRESS |
| POST | `/bookings/expire` | – | 200 `{"expiredCount": n}` | – |

snake_case input (`event_id`, `customer_email`) is accepted too. The price is `seats × SEAT_PRICE`, set by the server. The pay response carries the header `Idempotent-Replayed: true|false`. The OpenAPI file is exported at `docs/openapi/booking-service.json`.

Booking response:
```json
{"bookingId":"bae028b6-...","eventId":1,"seats":["A1"],"customerEmail":"happy@example.com",
 "amount":250.0,"status":"CONFIRMED","holdExpiresAt":"2026-10-20T06:00:01Z",
 "paymentId":"299eea74-...","createdAt":"2026-10-20T05:59:51Z"}
```

## Calls this service makes (contract the other owners must match)
| To | Request | Booking expects |
|---|---|---|
| Seat | `POST /api/v1/seats/hold` `{"bookingId","eventId","seats":[...]}` | 2xx = all held; 409 SEAT_UNAVAILABLE; 404 unknown seat/event |
| Seat | `POST /api/v1/seats/confirm` (same body) | 2xx = SOLD. **Must be idempotent**: confirming seats already SOLD to the same booking returns 2xx. 409 if the hold is gone |
| Seat | `POST /api/v1/seats/release` (same body) | 2xx. Releases only seats HELD by that booking |
| Payment | `POST /api/v1/payments`, header `Idempotency-Key` (the client's key, passed on), `{"bookingId","amount"}` | 2xx with `status: "APPROVED"` and `paymentId`; 409/422 for key problems; 503 PAYMENT_GATEWAY_UNAVAILABLE. **Must not save a 503 against the key** so a retry with the same key can charge |
| Notification | `POST /api/v1/notifications` `{"bookingId","type","message","recipient"}` | 2xx. Any failure is only logged |

All calls send `X-Correlation-Id`, use URLs from `.env` and have timeouts (`SERVICE_TIMEOUT_SECONDS`=3, `PAYMENT_TIMEOUT_SECONDS`=8 — longer than Payment's 5 s gateway timeout). If a teammate's shape differs, only `app/clients.py` changes.

## Code map
| File | Layer | What is in it |
|---|---|---|
| `app/api/bookings.py`, `app/api/schemas.py` | API | routes, request validation, response shapes |
| `app/booking_flow.py` | flow | order of the steps across services and what to undo on failure |
| `app/rules.py` | rules | BR3 `check_payable`, state machine `ensure_transition`, BR4 `request_fingerprint` / `check_idempotent_repeat`, seat-list checks |
| `app/db.py` | data | all SQL; atomic conditional UPDATEs; idempotency key table |
| `app/clients.py` | outbound | HTTP calls to Seat, Payment, Notification |
| `app/clock.py` | util | current UTC time (tests move it forward) |

## Settings (`.env`)
`PORT`, `DB_URL`, `SEAT_SERVICE_URL`, `PAYMENT_SERVICE_URL`, `NOTIFICATION_SERVICE_URL`, `HOLD_SECONDS` (30), `SEAT_PRICE` (250.00), `MAX_SEATS_PER_BOOKING` (6), `SERVICE_TIMEOUT_SECONDS` (3), `PAYMENT_TIMEOUT_SECONDS` (8), `PAY_LOCK_TTL_SECONDS` (60).
