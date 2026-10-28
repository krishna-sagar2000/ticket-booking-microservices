"""Challenge 2 / BR4 at the Booking API: a payment is applied once per booking.

    python scripts/booking_idempotency_demo.py --out evidence/challenge-2-idempotency/booking_output.txt

Needs all services running and TWO free seats (default B1,B2 of event 1).

  a. 10 identical pay requests (same key) at the same moment -> one payment
  b. the same key again later -> the saved response is replayed (Idempotent-Replayed: true)
  c. the same key for a DIFFERENT booking -> 422 IDEMPOTENCY_KEY_REUSED
  d. 10 pay requests with DIFFERENT keys for one booking at the same moment -> one payment
Afterwards check the database (commands are printed at the end).
"""
import argparse
import asyncio
import json
import sys
import uuid
from collections import Counter
from datetime import datetime

import httpx

p = argparse.ArgumentParser()
p.add_argument("--booking", default="http://localhost:8001")
p.add_argument("--payment", default="http://localhost:8003")
p.add_argument("--event", type=int, default=1)
p.add_argument("--seats", default="B1,B2")
p.add_argument("--parallel", type=int, default=10)
p.add_argument("--out")
args = p.parse_args()

SEATS = [s.strip() for s in args.seats.split(",")]
BOOKINGS = f"{args.booking}/api/v1/bookings"
RUN = uuid.uuid4().hex[:6]
out_file = open(args.out, "w", encoding="utf-8") if args.out else None
failures = []


def log(msg=""):
    line = f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}"
    print(line)
    if out_file:
        out_file.write(line + "\n")


def expect(cond, what):
    log(("  PASS  " if cond else "  FAIL  ") + what)
    if not cond:
        failures.append(what)


def summary(r):
    body = r.json()
    return (f"{r.status_code} replayed={r.headers.get('Idempotent-Replayed')} "
            f"{body.get('code') or body.get('status')} paymentId={body.get('paymentId')}")


async def fire(booking_id, keys):
    async with httpx.AsyncClient(timeout=30) as ac:
        calls = [ac.post(f"{BOOKINGS}/{booking_id}/pay",
                         headers={"Idempotency-Key": k, "X-Correlation-Id": f"idem-{RUN}-{i}"})
                 for i, k in enumerate(keys)]
        results = await asyncio.gather(*calls)
    for i, r in enumerate(results):
        log(f"  request {i:2d} key={keys[i]}: {summary(r)}")
    return results


def main():
    with httpx.Client(timeout=30) as c:
        b1 = c.post(BOOKINGS, json={"eventId": args.event, "seats": [SEATS[0]],
                                    "customerEmail": "idem1@example.com"}).json()
        b2 = c.post(BOOKINGS, json={"eventId": args.event, "seats": [SEATS[1]],
                                    "customerEmail": "idem2@example.com"}).json()
        log(f"booking 1: {b1['bookingId']} {b1['status']}")
        log(f"booking 2: {b2['bookingId']} {b2['status']}")
        key = f"idem-{RUN}"

        log(f"\n=== a. {args.parallel} identical requests at the same moment (key {key}) ===")
        results = asyncio.run(fire(b1["bookingId"], [key] * args.parallel))
        codes = Counter(r.status_code for r in results)
        log(f"status codes: {dict(codes)}")
        ok = [r for r in results if r.status_code == 200]
        expect(len({r.json()['paymentId'] for r in ok}) == 1,
               "every 200 carries the SAME paymentId (one charge)")
        expect(all(r.status_code in (200, 409) for r in results),
               "the others are 409 REQUEST_IN_PROGRESS or a replay, never a second charge")

        log("\n=== b. same key again, sequentially ===")
        first = ok[0].json() if ok else None
        r = c.post(f"{BOOKINGS}/{b1['bookingId']}/pay", headers={"Idempotency-Key": key})
        log(f"  repeat: {summary(r)}")
        log("    " + json.dumps(r.json()))
        expect(r.status_code == 200 and r.headers.get("Idempotent-Replayed") == "true"
               and r.json() == first, "identical saved response is replayed")

        log("\n=== c. same key, different request (booking 2) ===")
        r = c.post(f"{BOOKINGS}/{b2['bookingId']}/pay", headers={"Idempotency-Key": key})
        log(f"  {summary(r)}  {r.json().get('message')}")
        expect(r.status_code == 422 and r.json()["code"] == "IDEMPOTENCY_KEY_REUSED",
               "reused key with a different request is rejected with 422")

        log(f"\n=== d. {args.parallel} DIFFERENT keys for booking 2 at the same moment ===")
        keys = [f"idem-{RUN}-d{i}" for i in range(args.parallel)]
        results = asyncio.run(fire(b2["bookingId"], keys))
        codes = Counter(r.status_code for r in results)
        log(f"status codes: {dict(codes)}")
        expect(codes[200] == 1, "exactly one payment succeeds for booking 2")

        try:
            payments = c.get(f"{args.payment}/api/v1/payments").json()
            mine = [p for p in payments if p.get("bookingId") in (b1["bookingId"], b2["bookingId"])]
            log(f"\npayments recorded for these bookings (Payment API): {len(mine)}")
            expect(len(mine) == 2, "one payment per booking")
        except Exception:
            log("\n(Payment service has no list endpoint; check the database instead)")

    log("\nDatabase check (run in MySQL):")
    log(f"  SELECT idem_key, status, response_code FROM booking_db.idempotency_keys "
        f"WHERE idem_key LIKE 'idem-{RUN}%';")
    log(f"  SELECT id, status, payment_id FROM booking_db.bookings WHERE id IN "
        f"('{b1['bookingId']}', '{b2['bookingId']}');")
    log(f"  SELECT * FROM payment_db.payments WHERE booking_id IN "
        f"('{b1['bookingId']}', '{b2['bookingId']}');")
    log("\n" + ("ALL CHECKS PASSED" if not failures else f"{len(failures)} CHECK(S) FAILED"))
    return 1 if failures else 0


if __name__ == "__main__":
    code = main()
    if out_file:
        out_file.close()
    sys.exit(code)
