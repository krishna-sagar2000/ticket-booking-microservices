# Mock Payment Gateway

Run: `uvicorn app.main:app --port 8005`

Switch failure mode: `POST /admin/mode` with `{"mode": "down"}` (or `slow`, `ok`).
