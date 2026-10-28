"""Challenge 1 / BR1: many parallel POST /api/v1/seats/hold requests for the same seats.

Run (seat-service on :8002, from the repo root, using the seat-service venv):
    services/seat-service/.venv/Scripts/python evidence/challenge-1-concurrency/race_hold.py
    ... --n 50 --seat B2                   one seat, 50 bookings
    ... --mode overlap --n 20              each booking asks for TWO neighbouring seats of B1..B5

All requests are started at the same instant (threading.Barrier), each with its own bookingId.
  single : exactly 1 x 200, N-1 x 409 SEAT_UNAVAILABLE, seat HELD by the single winner
  overlap: no seat held twice, every winner holds BOTH its seats, every loser holds NONE
           (the all-or-nothing hold under real concurrency)
"""
import argparse
import sys
import threading
import time
from collections import Counter

import httpx


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8002")  # "localhost" adds ~2 s on Windows (tries IPv6 first)
    p.add_argument("--event", type=int, default=1)
    p.add_argument("--mode", choices=["single", "overlap"], default="single")
    p.add_argument("--seat", default="B1", help="single mode: the contended seat")
    p.add_argument("--ring", default="B1,B2,B3,B4,B5", help="overlap mode: seats to fight over")
    p.add_argument("--n", type=int, default=20)
    args = p.parse_args()
    api = f"{args.url}/api/v1"
    ring = args.ring.split(",")

    if args.mode == "single":
        wanted = {i: [args.seat] for i in range(args.n)}
    else:  # booking i wants seats i and i+1 of the ring, so every seat is wanted by two bookings
        wanted = {i: [ring[i % len(ring)], ring[(i + 1) % len(ring)]] for i in range(args.n)}
    involved = sorted({s for seats in wanted.values() for s in seats})

    def seat_states() -> dict:
        return {s["seatNo"]: s for s in httpx.get(f"{api}/events/{args.event}/seats").json()}

    # Precondition: every involved seat AVAILABLE. Release leftover holds from a previous run.
    for seat_no, s in seat_states().items():
        if seat_no in involved and s["status"] == "HELD":
            httpx.post(f"{api}/seats/release",
                       json={"bookingId": s["bookingId"], "eventId": args.event, "seats": [seat_no]})
    before = seat_states()
    not_free = [s for s in involved if before[s]["status"] != "AVAILABLE"]
    if not_free:
        print(f"Seats {not_free} are not AVAILABLE (SOLD?). Reset seat_db, see services/seat-service/README.md")
        return 2
    print(f"Mode {args.mode}: {args.n} parallel POST {api}/seats/hold, event {args.event}")
    print(f"Before: {', '.join(f'{s}={before[s]['status']}' for s in involved)}")

    barrier = threading.Barrier(args.n)
    results = {}

    def worker(i: int) -> None:
        booking_id = f"race-{i:02d}"
        with httpx.Client(timeout=30) as client:
            barrier.wait()  # every thread releases its request at the same moment
            t0 = time.perf_counter()
            r = client.post(f"{api}/seats/hold",
                            json={"bookingId": booking_id, "eventId": args.event, "seats": wanted[i]},
                            headers={"X-Correlation-Id": f"race-{args.mode}-{i:02d}"})
            results[i] = (booking_id, r.status_code, r.json(), (time.perf_counter() - t0) * 1000)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(args.n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print()
    for i in range(args.n):
        booking_id, status, body, ms = results[i]
        detail = body.get("holdExpiresAt") if status == 200 else f"{body.get('code')}: {body.get('message')}"
        print(f"  {booking_id} wants {'+'.join(wanted[i]):6} -> {status}  {detail}  ({ms:.0f} ms)")

    codes = Counter(status for _, status, _, _ in results.values())
    winners = {booking_id: wanted[i] for i, (booking_id, status, _, _) in results.items() if status == 200}
    losers = {booking_id: wanted[i] for i, (booking_id, status, _, _) in results.items() if status != 200}
    after = seat_states()
    holders = {s: after[s]["bookingId"] for s in involved}

    print(f"\nStatus counts: {dict(codes)}")
    print(f"Winners: {winners}")
    print(f"After:  {', '.join(f'{s}={after[s]['status']}({holders[s]})' for s in involved)}")

    ok = codes[200] + codes[409] == args.n and all(after[s]["status"] in ("HELD", "AVAILABLE") for s in involved)
    ok &= all(holders[s] == b for b, seats in winners.items() for s in seats)       # winners hold ALL their seats
    ok &= not any(holders[s] == b for b, seats in losers.items() for s in seats)    # losers hold NONE
    if args.mode == "single":
        ok &= codes[200] == 1 and codes[409] == args.n - 1
    print("\nRESULT:", "PASS - no seat over-allocated, every hold all-or-nothing" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
