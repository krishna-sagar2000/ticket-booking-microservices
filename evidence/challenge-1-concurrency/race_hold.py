"""Challenge 1 / BR1: fire N parallel POST /hold requests at ONE seat; exactly one may win.

Run (seat-service on :8002, from the repo root, using the seat-service venv):
    services/seat-service/.venv/Scripts/python evidence/challenge-1-concurrency/race_hold.py
    ... --seat 5 --n 50 --url http://127.0.0.1:8002

All requests are started at the same instant (threading.Barrier), each with its own bookingId.
Expected: 1 x 200 and N-1 x 409 SEAT_UNAVAILABLE, and the seat is HELD by the single winner.
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
    p.add_argument("--seat", type=int, default=5)
    p.add_argument("--n", type=int, default=20)
    args = p.parse_args()
    seats = f"{args.url}/api/v1/seats"

    def seat_state() -> dict:
        return next(s for s in httpx.get(seats).json() if s["seatId"] == args.seat)

    # Precondition: the seat must be AVAILABLE. Release a leftover hold from a previous run.
    before = seat_state()
    if before["status"] == "HELD":
        httpx.post(f"{seats}/{args.seat}/release", json={"bookingId": before["bookingId"]})
        before = seat_state()
    if before["status"] != "AVAILABLE":
        print(f"Seat {args.seat} is {before['status']}; pick another one with --seat")
        return 2
    print(f"Seat {args.seat} before the race: {before}")

    barrier = threading.Barrier(args.n)
    results = [None] * args.n

    def worker(i: int) -> None:
        booking_id = f"race-{i:02d}"
        with httpx.Client(timeout=30) as client:
            barrier.wait()  # every thread releases its request at the same moment
            t0 = time.perf_counter()
            r = client.post(f"{seats}/{args.seat}/hold", json={"bookingId": booking_id},
                            headers={"X-Correlation-Id": f"race-{args.seat}-{i:02d}"})
            results[i] = (booking_id, r.status_code, r.json(), (time.perf_counter() - t0) * 1000)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(args.n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print(f"\n{args.n} parallel POST {seats}/{args.seat}/hold:")
    for booking_id, status, body, ms in results:
        detail = body.get("holdExpiresAt") if status == 200 else body.get("code")
        print(f"  {booking_id}  ->  {status}  {detail}  ({ms:.0f} ms)")

    codes = Counter(status for _, status, _, _ in results)
    winners = [b for b, status, _, _ in results if status == 200]
    after = seat_state()
    print(f"\nStatus counts: {dict(codes)}")
    print(f"Winner(s): {winners}")
    print(f"Seat {args.seat} after the race: {after}")

    ok = (codes[200] == 1 and codes[409] == args.n - 1
          and after["status"] == "HELD" and after["bookingId"] == winners[0])
    print("\nRESULT:", "PASS - exactly one booking holds the seat" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
