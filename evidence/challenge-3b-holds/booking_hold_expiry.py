"""Challenge 3B / BR2 + BR3, booking-service side: an unpaid booking expires, a paid one never does.

Run from the repo root with MySQL and ALL services running (booking 8001, seat 8002,
payment 8003, notification 8004, gateway 8005), HOLD_SECONDS=30 in booking and seat:
    services/booking-service/.venv/bin/python evidence/challenge-3b-holds/booking_hold_expiry.py \
        --out evidence/challenge-3b-holds/booking_hold_expiry_output.txt \
        --dump evidence/challenge-3b-holds/booking_db_dump.txt
(Windows: services\\booking-service\\.venv\\Scripts\\python ...)  Takes about 40 s.

Steps, all through Booking's public API (the client only talks to Booking):
  1. booking UNPAID holds one seat; booking PAID holds one seat and is paid (CONFIRMED)
  2. before the hold ends: POST /bookings/expire changes nothing, UNPAID is still HELD
  3. wait past UNPAID's holdExpiresAt: POST /bookings/expire -> UNPAID EXPIRED, PAID still CONFIRMED
  4. POST /bookings/expire again -> expiredCount 0 (safe to run twice)
  5. paying UNPAID now -> 409 HOLD_EXPIRED; paying or cancelling PAID -> 409 (it is final)
  6. Seat agrees: UNPAID's seat AVAILABLE again, PAID's seat SOLD; the freed seat can be booked again
booking_db rows are dumped before and after (read-only SELECTs, for evidence only).
"""
import argparse
import sys
import time
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import bindparam, create_engine, text

p = argparse.ArgumentParser()
p.add_argument("--booking", default="http://127.0.0.1:8001")
p.add_argument("--seat", default="http://127.0.0.1:8002")
p.add_argument("--event", type=int, default=1)
p.add_argument("--db-url", default="mysql+pymysql://booking_user:booking_pass@127.0.0.1:3306/booking_db",
               help="booking_db, read-only use for the before/after dump")
p.add_argument("--out", help="also write the output to this file")
p.add_argument("--dump", help="write the booking_db before/after dump to this file")
args = p.parse_args()

BOOKINGS = f"{args.booking}/api/v1/bookings"
SEATS = f"{args.seat}/api/v1"
RUN = uuid.uuid4().hex[:6]
lines, dump_lines, checks = [], [], []
client = httpx.Client(timeout=15)


def log(msg=""):
    line = f"[{datetime.now(timezone.utc):%H:%M:%S}Z] {msg}"
    print(line)
    lines.append(line)


def check(name, ok):
    checks.append(ok)
    log(f"    {'PASS' if ok else 'FAIL'}  {name}")


def call(method, url, cid, **kw):
    r = client.request(method, url, headers={"X-Correlation-Id": f"c3b-{RUN}-{cid}",
                                             **kw.pop("headers", {})}, **kw)
    short = url.replace(args.booking, "").replace(args.seat, "")
    log(f"{method} {short} -> {r.status_code} {r.text}")
    return r


def seat_states():
    return {s["seatNo"]: s for s in client.get(f"{SEATS}/events/{args.event}/seats").json()}


def dump(label, ids):
    """Read booking_db directly (evidence only; the services never do this)."""
    engine = create_engine(args.db_url)
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, status, hold_expires_at, payment_id, pay_lock, updated_at "
            "FROM bookings WHERE id IN :ids ORDER BY created_at").bindparams(
            bindparam("ids", expanding=True)), {"ids": ids}).all()
        seats = conn.execute(text(
            "SELECT booking_id, seat_no FROM booking_seats WHERE booking_id IN :ids").bindparams(
            bindparam("ids", expanding=True)), {"ids": ids}).all()
        now = conn.execute(text("SELECT UTC_TIMESTAMP()")).scalar()
    engine.dispose()
    seat_of = {b: s for b, s in seats}
    out = [f"--- booking_db.bookings {label} (DB UTC time {now}) ---",
           f"{'id':38} {'seat':5} {'status':10} {'hold_expires_at':20} {'payment_id':12} {'pay_lock':9} updated_at"]
    for r in rows:
        out.append(f"{r.id:38} {seat_of.get(r.id, ''):5} {r.status:10} {str(r.hold_expires_at):20} "
                   f"{str(r.payment_id):12} {str(r.pay_lock):9} {r.updated_at}")
    for line in out:
        log("  " + line)
    dump_lines.extend(out + [""])
    return {r.id: r.status for r in rows}


def main():
    log(f"Challenge 3B booking side, run {RUN}")
    for name, url in (("booking", args.booking), ("seat", args.seat)):
        log(f"health {name}: {client.get(f'{url}/health').json()}")

    # Clear old overdue bookings from earlier runs, so the counts below are only ours.
    log(f"clean-up of earlier runs: {client.post(f'{BOOKINGS}/expire').json()}")

    free = [s for s, v in seat_states().items() if v["status"] == "AVAILABLE"]
    if len(free) < 2:
        log(f"need 2 AVAILABLE seats in event {args.event}, found {free}; reset the seats first")
        return 1
    unpaid_seat, paid_seat = free[0], free[1]

    log("\n=== 1. one unpaid booking, one paid booking ===")
    unpaid = call("POST", BOOKINGS, "unpaid", json={
        "eventId": args.event, "seats": [unpaid_seat], "customerEmail": "unpaid@example.com"}).json()
    paid = call("POST", BOOKINGS, "paid", json={
        "eventId": args.event, "seats": [paid_seat], "customerEmail": "paid@example.com"}).json()
    r = call("POST", f"{BOOKINGS}/{paid['bookingId']}/pay", "paid-pay",
             headers={"Idempotency-Key": f"c3b-{RUN}-paid"})
    check("paid booking is CONFIRMED", r.status_code == 200 and r.json()["status"] == "CONFIRMED")
    ids = [unpaid["bookingId"], paid["bookingId"]]
    log(f"UNPAID = {ids[0]} seat {unpaid_seat}, holdExpiresAt {unpaid['holdExpiresAt']}")
    log(f"PAID   = {ids[1]} seat {paid_seat}")
    state = dump("BEFORE expiry", ids)
    check("UNPAID is HELD, PAID is CONFIRMED",
          state == {ids[0]: "HELD", ids[1]: "CONFIRMED"})

    log("\n=== 2. expire before the hold ends ===")
    r = call("POST", f"{BOOKINGS}/expire", "expire-early")
    check("expiredCount 0 before HOLD_SECONDS", r.json() == {"expiredCount": 0})
    check("UNPAID still HELD", dump("after early expire", ids)[ids[0]] == "HELD")

    hold_end = datetime.fromisoformat(unpaid["holdExpiresAt"].replace("Z", "+00:00"))
    wait = max(0.0, (hold_end - datetime.now(timezone.utc)).total_seconds()) + 2
    log(f"\n=== 3. waiting {wait:.0f} s, past UNPAID's holdExpiresAt ===")
    time.sleep(wait)
    r = call("POST", f"{BOOKINGS}/expire", "expire-1")
    check("expiredCount 1: only UNPAID expired", r.json() == {"expiredCount": 1})
    state = dump("AFTER expiry", ids)
    check("UNPAID is EXPIRED", state[ids[0]] == "EXPIRED")
    check("PAID is still CONFIRMED (never touched by expiry)", state[ids[1]] == "CONFIRMED")

    log("\n=== 4. expire again ===")
    r = call("POST", f"{BOOKINGS}/expire", "expire-2")
    check("second run: no error, expiredCount 0", r.status_code == 200 and r.json() == {"expiredCount": 0})

    log("\n=== 5. expired and paid bookings are final ===")
    r = call("POST", f"{BOOKINGS}/{ids[0]}/pay", "pay-expired",
             headers={"Idempotency-Key": f"c3b-{RUN}-late"})
    check("paying the EXPIRED booking -> 409 HOLD_EXPIRED (BR3)",
          r.status_code == 409 and r.json()["code"] == "HOLD_EXPIRED")
    r = call("POST", f"{BOOKINGS}/{ids[1]}/pay", "pay-again",
             headers={"Idempotency-Key": f"c3b-{RUN}-again"})
    check("paying the CONFIRMED booking again -> 409 BOOKING_NOT_PAYABLE",
          r.status_code == 409 and r.json()["code"] == "BOOKING_NOT_PAYABLE")
    r = call("POST", f"{BOOKINGS}/{ids[1]}/cancel", "cancel-paid")
    check("cancelling the CONFIRMED booking -> 409 INVALID_STATE_CHANGE",
          r.status_code == 409 and r.json()["code"] == "INVALID_STATE_CHANGE")

    log("\n=== 6. Seat service agrees ===")
    call("POST", f"{SEATS}/seats/expire-holds", "seat-sweep")
    seats = seat_states()
    for s in (unpaid_seat, paid_seat):
        log(f"  seat {s}: {seats[s]['status']:9} booking={seats[s]['bookingId']}")
    check(f"seat {unpaid_seat} (UNPAID) is AVAILABLE again", seats[unpaid_seat]["status"] == "AVAILABLE")
    check(f"seat {paid_seat} (PAID) is still SOLD to the paid booking",
          seats[paid_seat]["status"] == "SOLD" and seats[paid_seat]["bookingId"] == ids[1])
    r = call("POST", BOOKINGS, "rebook", json={
        "eventId": args.event, "seats": [unpaid_seat], "customerEmail": "next@example.com"})
    check(f"seat {unpaid_seat} can be booked again", r.status_code == 201)
    if r.status_code == 201:   # tidy up: give the seat back
        call("POST", f"{BOOKINGS}/{r.json()['bookingId']}/cancel", "rebook-cancel")

    dump("FINAL", ids)
    passed = sum(checks)
    log(f"\nRESULT: {'PASS' if all(checks) else 'FAIL'}, {passed}/{len(checks)} checks")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    code = main()
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    if args.dump:
        with open(args.dump, "w", encoding="utf-8") as f:
            f.write("\n".join(dump_lines))
    sys.exit(code)
