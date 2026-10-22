"""Contrast demo: what goes wrong with "SELECT then UPDATE" in application code.

This is NOT how seat-service works. It runs the anti-pattern directly against seat_db so the
report can show the failure next to the correct, atomic version (race_hold.py).

Run (from the repo root, MySQL running, seat-service NOT required):
    services/seat-service/.venv/Scripts/python evidence/challenge-1-concurrency/naive_select_then_update.py
"""
import argparse
import os
import sys
import threading
import time

from sqlalchemy import create_engine, text

DEFAULT_DB_URL = "mysql+pymysql://seat_user:seat_pass@localhost:3306/seat_db"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db-url", default=os.getenv("DB_URL", DEFAULT_DB_URL))
    p.add_argument("--seat", type=int, default=10)
    p.add_argument("--n", type=int, default=20)
    args = p.parse_args()
    engine = create_engine(args.db_url, pool_size=args.n, max_overflow=0)

    def reset() -> None:
        with engine.begin() as c:
            c.execute(text("UPDATE seats SET status='AVAILABLE', booking_id=NULL, held_until=NULL WHERE id=:id"),
                      {"id": args.seat})

    reset()
    barrier = threading.Barrier(args.n)
    believed_winners = []
    lock = threading.Lock()

    def naive_hold(i: int) -> None:
        booking_id = f"naive-{i:02d}"
        barrier.wait()
        with engine.begin() as c:
            # Step 1: check
            status = c.execute(text("SELECT status FROM seats WHERE id=:id"), {"id": args.seat}).scalar()
            if status != "AVAILABLE":
                return
            time.sleep(0.05)  # any real work (validation, logging, a network call) widens this gap
            # Step 2: act - nothing re-checks the status, so a stale read wins
            c.execute(text("UPDATE seats SET status='HELD', booking_id=:b WHERE id=:id"),
                      {"b": booking_id, "id": args.seat})
        with lock:
            believed_winners.append(booking_id)

    threads = [threading.Thread(target=naive_hold, args=(i,)) for i in range(args.n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with engine.connect() as c:
        final = c.execute(text("SELECT id, status, booking_id FROM seats WHERE id=:id"), {"id": args.seat}).one()
    reset()

    print(f"{args.n} concurrent SELECT-then-UPDATE holds on seat {args.seat}")
    print(f"Requests told 'you got the seat': {len(believed_winners)}")
    for b in believed_winners:
        print(f"  {b}")
    print(f"Row actually stored: id={final.id} status={final.status} booking_id={final.booking_id}")
    print(f"=> {len(believed_winners) - 1} bookings were told they hold a seat that belongs to someone else"
          if len(believed_winners) > 1 else "=> no overlap this run (timing dependent); run again")
    return 0


if __name__ == "__main__":
    sys.exit(main())
