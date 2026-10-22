"""Challenge 3B / BR2, seat-service side: holds expire, a paid (BOOKED) seat is never released.

Run (seat-service on :8002, from the repo root, using the seat-service venv):
    services/seat-service/.venv/Scripts/python evidence/challenge-3b-holds/seat_hold_expiry.py

Steps, all through the public API:
  1. hold seat X for an unpaid booking; hold seat Y and confirm it (paid)
  2. expire-holds before the hold time is up  -> 0 (an unexpired hold is kept)
  3. wait until past holdExpiresAt (HOLD_SECONDS, 30 s by default)
  4. expire-holds                             -> 1: X is AVAILABLE again, Y is still BOOKED
  5. expire-holds again                       -> 0 (safe to run twice)
  6. a new booking can now hold X
The booking-service half (booking -> EXPIRED) is added by the booking/notification owners.
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
    args = p.parse_args()
    seats = f"{args.url}/api/v1/seats"
    client = httpx.Client(timeout=10, headers={"X-Correlation-Id": "challenge-3b-seat"})
    checks = []

    def check(name: str, ok: bool) -> None:
        checks.append(ok)
        print(f"    {'PASS' if ok else 'FAIL'}  {name}")

    def state(seat_id: int) -> dict:
        return next(s for s in client.get(seats).json() if s["seatId"] == seat_id)

    def post(path: str, body: dict | None = None) -> httpx.Response:
        r = client.post(f"{seats}{path}", json=body)
        log(f"POST {path} {body or ''} -> {r.status_code} {r.json()}")
        return r

    free = [s["seatId"] for s in client.get(seats).json() if s["status"] == "AVAILABLE"]
    if len(free) < 2:
        print("Need 2 AVAILABLE seats; reset seat_db first")
        return 2
    unpaid, paid = free[0], free[1]
    log(f"Using seat {unpaid} (unpaid hold) and seat {paid} (paid)")

    print("\n1. Create the holds")
    held = post(f"/{unpaid}/hold", {"bookingId": "exp-unpaid"}).json()
    post(f"/{paid}/hold", {"bookingId": "exp-paid"})
    post(f"/{paid}/confirm", {"bookingId": "exp-paid"})
    expires_at = datetime.fromisoformat(held["holdExpiresAt"].replace("Z", "+00:00"))

    print("\n2. Sweep before the hold time is up")
    check("unexpired hold is kept (expiredCount 0)", post("/expire-holds").json()["expiredCount"] == 0)
    check(f"seat {unpaid} still HELD", state(unpaid)["status"] == "HELD")

    wait = (expires_at - utc_now()).total_seconds() + 2
    print(f"\n3. Waiting {wait:.0f} s until past holdExpiresAt {held['holdExpiresAt']}")
    time.sleep(max(wait, 0))

    print("\n4. Sweep after expiry")
    check("exactly the unpaid hold expired (expiredCount 1)", post("/expire-holds").json()["expiredCount"] == 1)
    s_unpaid, s_paid = state(unpaid), state(paid)
    log(f"seat {unpaid}: {s_unpaid}")
    log(f"seat {paid}: {s_paid}")
    check(f"seat {unpaid} released -> AVAILABLE, booking cleared",
          s_unpaid["status"] == "AVAILABLE" and s_unpaid["bookingId"] is None)
    check(f"paid seat {paid} still BOOKED by exp-paid",
          s_paid["status"] == "BOOKED" and s_paid["bookingId"] == "exp-paid")

    print("\n5. Sweep again")
    check("second sweep is a no-op (expiredCount 0)", post("/expire-holds").json()["expiredCount"] == 0)

    print("\n6. The expired booking can no longer use the seat; a new booking can")
    check("old booking cannot confirm (409)",
          post(f"/{unpaid}/confirm", {"bookingId": "exp-unpaid"}).status_code == 409)
    check("new booking can hold the released seat (200)",
          post(f"/{unpaid}/hold", {"bookingId": "exp-new"}).status_code == 200)
    post(f"/{unpaid}/release", {"bookingId": "exp-new"})  # clean up

    print(f"\nRESULT: {'PASS' if all(checks) else 'FAIL'} ({sum(checks)}/{len(checks)} checks)")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
