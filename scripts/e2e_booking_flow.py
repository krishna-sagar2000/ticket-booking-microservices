"""End-to-end test of the main transaction, through the Booking service only.

    python scripts/e2e_booking_flow.py                       # all scenarios except the 30 s wait
    python scripts/e2e_booking_flow.py --with-expiry         # also waits for a hold to expire
    python scripts/e2e_booking_flow.py --out evidence/tests/e2e_output.txt

Needs all five services running (booking 8001, seat 8002, payment 8003,
notification 8004, gateway 8005) and FIVE free seats in one event (default A1..A5
of event 1). Re-seed the Seat service before running it again.

Scenarios
  1. Happy path      : create -> pay -> CONFIRMED (Seat SOLD, notification recorded)
  2. Contended seat  : 20 parallel bookings of one seat -> exactly 1 x 201, 19 x 409
  3. Failure path    : gateway DOWN -> 503, booking stays HELD -> gateway OK -> same key -> 200
  4. Slow dependency : gateway SLOW -> Payment times out -> 503, booking stays HELD
  5. Cancel          : cancel -> CANCELLED, cancel again -> 409, pay -> 409
  6. Expiry (opt.)   : wait > HOLD_SECONDS -> pay -> 409 HOLD_EXPIRED; expire job safe twice
"""
import argparse
import asyncio
import json
import sys
import time
import uuid
from collections import Counter
from datetime import datetime

import httpx

p = argparse.ArgumentParser()
p.add_argument("--booking", default="http://localhost:8001")
p.add_argument("--gateway", default="http://localhost:8005")
p.add_argument("--event", type=int, default=1)
p.add_argument("--seats", default="A1,A2,A3,A4,A5", help="five free seats, comma separated")
p.add_argument("--with-expiry", action="store_true")
p.add_argument("--hold-seconds", type=int, default=30)
p.add_argument("--out", help="also write the output to this file")
args = p.parse_args()

SEATS = [s.strip() for s in args.seats.split(",")]
BOOKINGS = f"{args.booking}/api/v1/bookings"
RUN = uuid.uuid4().hex[:6]
out_file = open(args.out, "w", encoding="utf-8") if args.out else None
failures = []


def log(msg=""):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    if out_file:
        out_file.write(line + "\n")


def show(label, r: httpx.Response):
    log(f"{label}: HTTP {r.status_code}  X-Correlation-Id={r.headers.get('X-Correlation-Id')}")
    log("    " + json.dumps(r.json()))


def expect(cond, what):
    log(("  PASS  " if cond else "  FAIL  ") + what)
    if not cond:
        failures.append(what)


def cid(name):
    return {"X-Correlation-Id": f"e2e-{RUN}-{name}"}


def create(client, seat, name):
    return client.post(BOOKINGS, headers=cid(name),
                       json={"eventId": args.event, "seats": [seat],
                             "customerEmail": f"{name}@example.com"})


def pay(client, booking_id, key, name):
    return client.post(f"{BOOKINGS}/{booking_id}/pay",
                       headers={**cid(name), "Idempotency-Key": key})


def gateway_mode(client, mode):
    r = client.post(f"{args.gateway}/admin/mode", json={"mode": mode})
    log(f"gateway mode -> {r.json()}")


def main():
    log(f"E2E run {RUN} against {args.booking}, event {args.event}, seats {SEATS}")
    with httpx.Client(timeout=20) as c:
        for port in (8001, 8002, 8003, 8004, 8005):
            try:
                log(f"health {port}: {c.get(f'http://localhost:{port}/health').json()}")
            except httpx.HTTPError as exc:
                log(f"health {port}: NOT REACHABLE ({type(exc).__name__})")
        gateway_mode(c, "ok")

        log("\n=== 1. Happy path ===")
        r = create(c, SEATS[0], "happy")
        show("POST /bookings", r)
        expect(r.status_code == 201 and r.json()["status"] == "HELD", "booking created as HELD")
        bid = r.json()["bookingId"]
        r = pay(c, bid, f"pay-{RUN}-1", "happy")
        show("POST /pay", r)
        expect(r.status_code == 200 and r.json()["status"] == "CONFIRMED", "booking CONFIRMED")
        r = c.get(f"{BOOKINGS}/{bid}")
        show("GET /bookings/{id}", r)

        log("\n=== 2. Contended seat: 20 parallel bookings of one seat ===")
        codes = asyncio.run(parallel_creates(SEATS[1], 20))
        log(f"results: {dict(Counter(codes))}")
        expect(codes.count(201) == 1 and codes.count(409) == 19,
               "exactly 1 booking won the seat, 19 got 409 SEAT_UNAVAILABLE")

        log("\n=== 3. Failure path: payment gateway DOWN ===")
        r = create(c, SEATS[2], "failure")
        bid = r.json()["bookingId"]
        show("POST /bookings", r)
        gateway_mode(c, "down")
        key = f"pay-{RUN}-3"
        r = pay(c, bid, key, "failure")
        show("POST /pay (gateway down)", r)
        expect(r.status_code == 503, "client gets a clean 503, not a crash or hang")
        r = c.get(f"{BOOKINGS}/{bid}")
        expect(r.json()["status"] == "HELD", "booking stays HELD, nothing sold")
        gateway_mode(c, "ok")
        r = pay(c, bid, key, "failure-retry")
        show("POST /pay (retry, same key)", r)
        expect(r.status_code == 200 and r.json()["status"] == "CONFIRMED",
               "retry with the same key succeeds once the gateway is back")

        log("\n=== 4. Slow dependency: gateway SLOW (10 s) vs 5 s timeout ===")
        r = create(c, SEATS[3], "slow")
        bid = r.json()["bookingId"]
        gateway_mode(c, "slow")
        t0 = time.time()
        r = pay(c, bid, f"pay-{RUN}-4", "slow")
        show(f"POST /pay (gateway slow, took {time.time() - t0:.1f}s)", r)
        expect(r.status_code == 503, "timeout becomes 503")
        expect(c.get(f"{BOOKINGS}/{bid}").json()["status"] == "HELD", "booking stays HELD")
        gateway_mode(c, "ok")

        log("\n=== 5. Cancel ===")
        r = c.post(f"{BOOKINGS}/{bid}/cancel", headers=cid("cancel"))
        show("POST /cancel", r)
        expect(r.status_code == 200 and r.json()["status"] == "CANCELLED", "booking CANCELLED")
        r = c.post(f"{BOOKINGS}/{bid}/cancel", headers=cid("cancel-again"))
        show("POST /cancel again", r)
        expect(r.status_code == 409 and r.json()["code"] == "INVALID_STATE_CHANGE",
               "second cancel is 409 INVALID_STATE_CHANGE")
        r = pay(c, bid, f"pay-{RUN}-5", "cancel-pay")
        show("POST /pay on cancelled", r)
        expect(r.status_code == 409 and r.json()["code"] == "BOOKING_NOT_PAYABLE",
               "cancelled booking cannot be paid (BR3)")
        r = create(c, SEATS[3], "rebook")
        expect(r.status_code == 201, "cancelled seat can be booked again")

        if args.with_expiry:
            log(f"\n=== 6. Hold expiry: waiting {args.hold_seconds + 2}s ===")
            r = create(c, SEATS[4], "expiry")
            bid = r.json()["bookingId"]
            show("POST /bookings", r)
            time.sleep(args.hold_seconds + 2)
            r = c.post(f"{BOOKINGS}/expire")
            show("POST /bookings/expire (1st run)", r)
            r2 = c.post(f"{BOOKINGS}/expire")
            show("POST /bookings/expire (2nd run)", r2)
            expect(r2.json()["expiredCount"] == 0, "expiry job is safe to run twice")
            r = pay(c, bid, f"pay-{RUN}-6", "expiry")
            show("POST /pay after expiry", r)
            expect(r.status_code == 409 and r.json()["code"] == "HOLD_EXPIRED",
                   "expired booking cannot be paid (BR3)")

    log("\n" + ("ALL CHECKS PASSED" if not failures else f"{len(failures)} CHECK(S) FAILED:"))
    for f in failures:
        log("  - " + f)
    return 1 if failures else 0


async def parallel_creates(seat, n):
    async with httpx.AsyncClient(timeout=20) as ac:
        calls = [ac.post(BOOKINGS, headers=cid(f"race-{i}"),
                         json={"eventId": args.event, "seats": [seat],
                               "customerEmail": f"user{i}@example.com"}) for i in range(n)]
        results = await asyncio.gather(*calls)
    for i, r in enumerate(results):
        log(f"  request {i:2d}: {r.status_code} {r.json().get('code', r.json().get('status'))}")
    return [r.status_code for r in results]


if __name__ == "__main__":
    code = main()
    if out_file:
        out_file.close()
    sys.exit(code)
