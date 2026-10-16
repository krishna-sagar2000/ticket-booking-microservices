# Shared contracts (frozen - change only with the whole team)

- Base path: `/api/v1/...` and `GET /health` on every service
- Ports: Booking 8001, Seat 8002, Payment 8003, Notification 8004, Mock gateway 8005
- Error JSON: `{"code": "...", "message": "...", "correlationId": "..."}`
- Headers: `X-Correlation-Id` (pass it on every call to another service), `Idempotency-Key` (on pay)
- Env vars: PORT, DB_URL, SEAT_SERVICE_URL, PAYMENT_SERVICE_URL, NOTIFICATION_SERVICE_URL, GATEWAY_URL, HOLD_SECONDS (30), GATEWAY_TIMEOUT_SECONDS (5)
- Status codes: 200, 201, 400, 404, 409, 422, 503
- Logs: JSON, to the console
- Booking states: HELD -> CONFIRMED / CANCELLED / EXPIRED; anything else -> 409 INVALID_STATE_CHANGE
     