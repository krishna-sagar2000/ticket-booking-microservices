"""
Challenge 2: Payment idempotency evidence.

Run from the repository root with the virtual environment activated.
The payment service and mock gateway must already be running.
"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text

BASE_URL = "http://localhost:8003"
GATEWAY_URL = "http://localhost:8005"
EVIDENCE_DIR = Path("evidence/challenge-2-idempotency")
OUTPUT_FILE = EVIDENCE_DIR / "output.txt"
DB_DUMP_FILE = EVIDENCE_DIR / "database_dump.sql"

# Read the same DB_URL used by the payment service.
import os
from dotenv import load_dotenv

load_dotenv("services/payment-service/.env")
load_dotenv(".env")

DB_URL = os.getenv("DB_URL", "")
if not DB_URL:
    # Match the local development database configuration.
    DB_URL = (
        "mysql+pymysql://payment_user:payment_pass"
        "@localhost:3306/payment_db"
    )

engine = create_engine(DB_URL, pool_pre_ping=True)

lines = []
gateway_count = 0
gateway_count_lock = threading.Lock()
original_charge = None


def record(message):
    print(message, flush=True)
    lines.append(message)


def counted_charge(request):
    """Count actual requests sent to the mock gateway's /charge endpoint."""
    global gateway_count
    if request.url.path == "/charge":
        with gateway_count_lock:
            gateway_count += 1


def gateway_count_now():
    with gateway_count_lock:
        return gateway_count


def payment(booking_id, amount, key):
    return httpx.post(
        f"{BASE_URL}/api/v1/payments",
        json={"bookingId": booking_id, "amount": amount},
        headers={"Idempotency-Key": key},
        timeout=15,
    )


def reset_payment_rows(booking_ids, keys):
    """Remove only this script's records so reruns are repeatable."""
    with engine.begin() as conn:
        for booking_id in booking_ids:
            conn.execute(
                text("DELETE FROM payments WHERE booking_id = :booking_id"),
                {"booking_id": booking_id},
            )
        for key in keys:
            conn.execute(
                text(
                    "DELETE FROM idempotency_keys WHERE idem_key = :key"
                ),
                {"key": key},
            )


def dump_database():
    with engine.connect() as conn:
        payments = conn.execute(
            text("""
                SELECT id, booking_id, amount, status, created_at
                FROM payments
                WHERE booking_id LIKE 'challenge2-%'
                ORDER BY id
            """)
        ).mappings().all()

        idempotency = conn.execute(
            text("""
                SELECT idem_key, request_hash, status,
                       response_code, response_body, created_at
                FROM idempotency_keys
                WHERE idem_key LIKE 'challenge2-%'
                ORDER BY created_at
            """)
        ).mappings().all()

    def sql_value(value):
        if value is None:
            return "NULL"
        if hasattr(value, "isoformat"):
            value = value.isoformat(sep=" ", timespec="seconds")
        if isinstance(value, (dict, list)):
            value = json.dumps(value, sort_keys=True)
        return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"

    with DB_DUMP_FILE.open("w", encoding="utf-8") as f:
        f.write("-- Challenge 2 idempotency evidence database snapshot\n")
        f.write("-- Snapshot of rows whose booking/key starts with challenge2-.\n\n")

        f.write("-- payments rows\n")
        for row in payments:
            f.write(
                "INSERT INTO payments "
                "(id, booking_id, amount, status, created_at) VALUES ("
                + ", ".join(sql_value(row[k]) for k in
                            ("id", "booking_id", "amount", "status", "created_at"))
                + ");\n"
            )

        f.write("\n-- idempotency_keys rows\n")
        for row in idempotency:
            f.write(
                "INSERT INTO idempotency_keys "
                "(idem_key, request_hash, status, response_code, "
                "response_body, created_at) VALUES ("
                + ", ".join(sql_value(row[k]) for k in
                            ("idem_key", "request_hash", "status",
                             "response_code", "response_body", "created_at"))
                + ");\n"
            )

    record(f"Database snapshot saved: {DB_DUMP_FILE}")
    record(f"Challenge 2 payment rows captured: {len(payments)}")
    record(f"Challenge 2 idempotency rows captured: {len(idempotency)}")


def main():
    global gateway_count

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text("", encoding="utf-8")

    booking_ids = [
        "challenge2-replay-001",
        "challenge2-different-001",
        "challenge2-race-001",
    ]
    keys = [
        "challenge2-replay-key",
        "challenge2-different-key",
        "challenge2-race-key",
    ]

    # Reset only this script's test records.
    reset_payment_rows(booking_ids, keys)

    # Count gateway requests from the payment service by temporarily wrapping
    # httpx's request method in this test process. This does not reliably see
    # requests made by the separately running payment-service process, so
    # the service's own logs must also be reviewed for gateway-call evidence.
    record("Challenge 2 — Payment Idempotency")
    record("=" * 48)
    record("Prerequisites: payment-service on :8003 and mock-gateway on :8005")

    # Scenario 1: same key, same request body, sent twice.
    record("\n[1] Same key and same request twice")
    key = "challenge2-replay-key"
    before = gateway_count_now()
    first = payment(booking_ids[0], 500.00, key)
    second = payment(booking_ids[0], 500.00, key)

    record(f"First response:  {first.status_code} {first.text}")
    record(f"Second response: {second.status_code} {second.text}")
    record(f"Responses match: {first.status_code == second.status_code and first.json() == second.json()}")
    record("Expected: same successful result; one payment row for this booking.")

    # Scenario 2: same key, different amount.
    record("\n[2] Same key, different amount")
    first = payment(booking_ids[1], 500.00, "challenge2-different-key")
    second = payment(booking_ids[1], 600.00, "challenge2-different-key")
    record(f"First response:  {first.status_code} {first.text}")
    record(f"Second response: {second.status_code} {second.text}")
    record(f"Different body rejected with 422: {second.status_code == 422}")
    record("Expected error code: IDEMPOTENCY_KEY_REUSED")

    # Scenario 3: concurrent requests with the same key and same body.
    record("\n[3] Two simultaneous requests with the same key")
    start_gate = threading.Barrier(2)

    def concurrent_request():
        start_gate.wait()
        return payment(booking_ids[2], 700.00, "challenge2-race-key")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(concurrent_request) for _ in range(2)]
        responses = [future.result() for future in futures]

    for index, response in enumerate(responses, start=1):
        record(f"Concurrent response {index}: {response.status_code} {response.text}")

    record(
        "Concurrent successful responses: "
        + str(sum(1 for response in responses if response.status_code == 201))
    )
    record("Expected: no more than one gateway charge and one payment row.")

    # Query the actual DB to verify uniqueness and statuses.
    with engine.connect() as conn:
        payment_rows = conn.execute(
            text("""
                SELECT booking_id, amount, status
                FROM payments
                WHERE booking_id LIKE 'challenge2-%'
                ORDER BY booking_id
            """)
        ).mappings().all()

        counts = conn.execute(
            text("""
                SELECT booking_id, COUNT(*) AS row_count
                FROM payments
                WHERE booking_id LIKE 'challenge2-%'
                GROUP BY booking_id
                ORDER BY booking_id
            """)
        ).mappings().all()

    record("\n[Database verification]")
    for row in payment_rows:
        record(f"Payment: {dict(row)}")
    for row in counts:
        record(f"Rows for {row['booking_id']}: {row['row_count']}")

    record("\nNote: the script's process-local counter cannot count requests sent")
    record("by a separate Uvicorn process. Use payment-service logs to verify")
    record("gateway calls; do not treat the process-local counter as proof.")

    dump_database()
    OUTPUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    record(f"\nOutput saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
