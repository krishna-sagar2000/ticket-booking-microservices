"""Challenge 3B / BR2, seat-service side: holds expire on their own, a paid (SOLD) seat never does.

Run (seat-service on :8002, from the repo root, using the seat-service venv):
    services/seat-service/.venv/Scripts/python evidence/challenge-3b-holds/seat_hold_expiry.py

Steps, all through the public API (nobody calls the sweep until step 5):
  1. booking exp-unpaid holds two seats; booking exp-paid holds one and confirms it (SOLD);
     booking exp-cancel holds one and releases it straight away (cancel frees at once)
  2. before HOLD_SECONDS: the unpaid seats are still HELD
  3. wait past holdExpiresAt + one EXPIRY_INTERVAL_SECONDS: the BACKGROUND JOB frees them
  4. the paid seat is still SOLD; the expired booking can no longer confirm (409 HOLD_EXPIRED)
  5. running the sweep by hand twice changes nothing (expiredCount 0, 0)
The booking-service half (booking -> EXPIRED / CANCELLED) is added by the booking/notification owners.
"""
import argparse
import sys
import time
from datetime import datetime, timezone

import httpx


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def log(msg: str) -> None:
    print(f"[{utc_now():%H:%M:%S}Z] {msg}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8002")  # "localhost" adds ~2 s on Windows
    p.add_argument("--event", type=int, default=1)
    p.add_argument("--job-interval", type=float, default=5, help="seat-service EXPIRY_INTERVAL_SECONDS")
    args = p.parse_args()
    api = f"{args.url}/api/v1"
    client = httpx.Client(timeout=10, headers={"X-Correlation-Id": "challenge-3b-seat"})
    checks = []

    def check(name: str, ok: bool) -> None:
        checks.append(ok)
        print(f"    {'PASS' if ok else 'FAIL'}  {name}")

    def states() -> dict:
        return {s["seatNo"]: s for s in client.get(f"{api}/events/{args.event}/seats").json()}

    def post(action: str, booking: str | None = None, seats: list | None = None) -> httpx.Response:
        body = {"bookingId": booking, "eventId": args.event, "seats": seats} if booking else None
        r = client.post(f"{api}/seats/{action}", json=body)
        log(f"POST /seats/{action} {booking or ''} {seats or ''} -> {r.status_code} {r.json()}")
        return r

    def show(seat_nos: list) -> dict:
        now = states()
        for s in seat_nos:
            log(f"  {s}: {now[s]['status']:9} booking={now[s]['bookingId']} holdExpiresAt={now[s]['holdExpiresAt']}")
        return now

    free = [s for s, v in states().items() if v["status"] == "AVAILABLE"]
    if len(free) < 4:
        print("Need 4 AVAILABLE seats; reset seat_db (services/seat-service/README.md)")
        return 2
    unpaid, paid, cancel = free[0:2], [free[2]], [free[3]]
    used = unpaid + paid + cancel
    log(f"Event {args.event}: unpaid hold {unpaid}, paid {paid}, cancelled {cancel}")

    print("\n1. Create the holds")
    held = post("hold", "exp-unpaid", unpaid).json()
    post("hold", "exp-paid", paid)
    post("confirm", "exp-paid", paid)
    post("hold", "exp-cancel", cancel)
    r = post("release", "exp-cancel", cancel)
    check("cancel frees the seat at once (releasedCount 1)", r.json().get("releasedCount") == 1)

    print("\n2. Before the hold time is up")
    now = show(used)
    check("unpaid seats still HELD", all(now[s]["status"] == "HELD" for s in unpaid))

    expires_at = datetime.fromisoformat(held["holdExpiresAt"].replace("Z", "+00:00"))
    wait = (expires_at - utc_now()).total_seconds() + args.job_interval + 2
    print(f"\n3. Waiting {wait:.0f} s (past holdExpiresAt {held['holdExpiresAt']} + one job interval);"
          " nobody calls the sweep")
    time.sleep(max(wait, 0))
    now = show(used)
    check("background job released the unpaid seats -> AVAILABLE, booking cleared",
          all(now[s]["status"] == "AVAILABLE" and now[s]["bookingId"] is None for s in unpaid))

    print("\n4. Paid seat and the expired booking")
    check("paid seat still SOLD by exp-paid", now[paid[0]]["status"] == "SOLD" and now[paid[0]]["bookingId"] == "exp-paid")
    r = post("confirm", "exp-unpaid", unpaid)
    check("expired booking cannot confirm (409 HOLD_EXPIRED)", r.status_code == 409 and r.json()["code"] == "HOLD_EXPIRED")

    print("\n5. Sweep by hand, twice")
    first, second = post("expire-holds").json(), post("expire-holds").json()
    check("sweep is safe to run again (expiredCount 0, 0)", first["expiredCount"] == 0 and second["expiredCount"] == 0)
    check("paid seat still SOLD after the sweeps", states()[paid[0]]["status"] == "SOLD")

    print(f"\nRESULT: {'PASS' if all(checks) else 'FAIL'} ({sum(checks)}/{len(checks)} checks)")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
