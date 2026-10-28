"""Seat-service API check: every endpoint, success and failure scenarios, against a running service.

Needs a fresh event 1 (all 10 seats AVAILABLE). Run from the repo root:
    services/seat-service/.venv/Scripts/python evidence/tests/seat_api_check.py
Optional --short-url: a second instance on the SAME database started with HOLD_SECONDS=2 and a
long EXPIRY_INTERVAL_SECONDS, used for the "hold expired but not yet swept" cases:
    (in services/seat-service)  set HOLD_SECONDS=2 & set EXPIRY_INTERVAL_SECONDS=3600 & uvicorn app.main:app --port 8012
    ... seat_api_check.py --short-url http://127.0.0.1:8012
The main instance's background job (HOLD_SECONDS=30) is checked with one real ~40 s wait.
"""
import argparse
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone

import httpx

p = argparse.ArgumentParser()
p.add_argument("--url", default="http://127.0.0.1:8002")  # "localhost" adds ~2 s on Windows
p.add_argument("--short-url", default=None)
p.add_argument("--job-interval", type=float, default=5)
args = p.parse_args()

API = f"{args.url}/api/v1"
client = httpx.Client(timeout=30)
results = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
    return ok


def req(action: str, booking, seats, event=1, base=API, raw=None, **kw) -> httpx.Response:
    body = raw if raw is not None else {"bookingId": booking, "eventId": event, "seats": seats}
    return client.post(f"{base}/seats/{action}", json=body, **kw)


def seats(event=1) -> dict:
    return {s["seatNo"]: s for s in client.get(f"{API}/events/{event}/seats").json()}


def is_error(r: httpx.Response, status: int, code: str, text: str = "") -> bool:
    try:
        b = r.json()
    except ValueError:
        return False
    return (r.status_code == status and b.get("code") == code and "correlationId" in b
            and set(b) == {"code", "message", "correlationId"} and text in b.get("message", ""))


def err(name, r, status, code, text=""):
    return check(name, is_error(r, status, code, text), f"{r.status_code} {r.text[:150]}")


def section(title):
    print(f"\n== {title}")


start = seats()
if len(start) != 10 or any(s["status"] != "AVAILABLE" for s in start.values()):
    print("Event 1 must have 10 AVAILABLE seats. Reset seat_db first (services/seat-service/README.md).")
    sys.exit(2)
print(f"Seat-service API check against {args.url} at {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z")

# ------------------------------------------------------------------------------------------
section("Health, docs, cross-cutting")
r = client.get(f"{args.url}/health")
check("GET /health -> 200 UP", r.status_code == 200 and r.json() == {"status": "UP", "service": "seat-service"})
check("GET /docs -> 200 (Swagger UI)", client.get(f"{args.url}/docs").status_code == 200)
paths = set(client.get(f"{args.url}/openapi.json").json()["paths"])
check("OpenAPI lists all 6 paths", paths == {"/health", "/api/v1/events/{event_id}/seats", "/api/v1/seats/hold",
                                             "/api/v1/seats/confirm", "/api/v1/seats/release",
                                             "/api/v1/seats/expire-holds"}, str(paths))
r = client.get(f"{API}/events/1/seats", headers={"X-Correlation-Id": "trace-42"})
check("X-Correlation-Id echoed on the response", r.headers.get("x-correlation-id") == "trace-42")
r = client.get(f"{API}/events/1/seats")
check("X-Correlation-Id generated when missing", len(r.headers.get("x-correlation-id", "")) == 36)
r = req("hold", "b", ["A1"], event=99, headers={"X-Correlation-Id": "trace-43"})
check("error body carries the request's correlation id", r.json().get("correlationId") == "trace-43")

# ------------------------------------------------------------------------------------------
section("GET /api/v1/events/{id}/seats")
s = seats()
check("event 1 lists A1-A5, B1-B5 in order", list(s) == ["A1", "A2", "A3", "A4", "A5", "B1", "B2", "B3", "B4", "B5"])
check("each seat has seatNo, status, bookingId, holdExpiresAt",
      all(set(v) == {"seatNo", "status", "bookingId", "holdExpiresAt"} for v in s.values()))
err("unknown event -> 404 EVENT_NOT_FOUND", client.get(f"{API}/events/99/seats"), 404, "EVENT_NOT_FOUND")
check("non-numeric event id -> 400", client.get(f"{API}/events/abc/seats").status_code == 400)

# ------------------------------------------------------------------------------------------
section("POST /api/v1/seats/hold (BR1)")
r = req("hold", "h1", ["A1"])
b = r.json()
check("hold one free seat -> 200, full response shape",
      r.status_code == 200 and set(b) == {"bookingId", "eventId", "seats", "status", "holdExpiresAt"}
      and b["status"] == "HELD" and b["seats"] == ["A1"] and b["holdExpiresAt"].endswith("Z"), r.text)
exp = datetime.fromisoformat(b["holdExpiresAt"].replace("Z", "+00:00"))
check("holdExpiresAt is about now + 30 s", 25 <= (exp - datetime.now(timezone.utc)).total_seconds() <= 31)
check("list shows A1 HELD by h1 with the same expiry",
      seats()["A1"] == {"seatNo": "A1", "status": "HELD", "bookingId": "h1", "holdExpiresAt": b["holdExpiresAt"]})
err("same seat, other booking -> 409 SEAT_UNAVAILABLE", req("hold", "h2", ["A1"]), 409, "SEAT_UNAVAILABLE",
    "Seat A1 is already held")
err("same seat, SAME booking again -> 409 (a hold is not repeatable)", req("hold", "h1", ["A1"]), 409,
    "SEAT_UNAVAILABLE")
r = req("hold", "h3", ["A2", "A3"])
check("hold two seats -> 200, both HELD", r.status_code == 200 and seats()["A3"]["bookingId"] == "h3")
err("overlapping multi-seat hold -> 409 naming the taken seat", req("hold", "h4", ["A3", "A4"]), 409,
    "SEAT_UNAVAILABLE", "A3")
check("...and the free seat of that request was NOT held (all or none)", seats()["A4"]["status"] == "AVAILABLE")
err("hold with an unknown seat -> 404 SEAT_NOT_FOUND", req("hold", "h4", ["A4", "Z9"]), 404, "SEAT_NOT_FOUND", "Z9")
check("...and A4 was NOT held", seats()["A4"]["status"] == "AVAILABLE")
err("hold in an unknown event -> 404 EVENT_NOT_FOUND", req("hold", "h4", ["A4"], event=99), 404, "EVENT_NOT_FOUND")
r = req("hold", "h5", [" a4 "])
check("seat numbers are trimmed and upper-cased: ' a4 ' holds A4",
      r.status_code == 200 and r.json()["seats"] == ["A4"] and seats()["A4"]["bookingId"] == "h5", r.text)
r = req("release", "h5", ["a4"])
check("...and 'a4' releases it again", r.json().get("releasedCount") == 1 and seats()["A4"]["status"] == "AVAILABLE")
err("same seat in two cases ['A4','a4'] -> 400 (duplicate)", req("hold", "h5", ["A4", "a4"]), 400, "VALIDATION_ERROR")

# ------------------------------------------------------------------------------------------
section("Validation -> 400 VALIDATION_ERROR (shared error format)")
bad = {
    "empty object": {},
    "missing bookingId": {"eventId": 1, "seats": ["A4"]},
    "missing eventId": {"bookingId": "v", "seats": ["A4"]},
    "missing seats": {"bookingId": "v", "eventId": 1},
    "empty seats list": {"bookingId": "v", "eventId": 1, "seats": []},
    "11 seats (max 10)": {"bookingId": "v", "eventId": 1, "seats": [f"S{i}" for i in range(11)]},
    "repeated seat": {"bookingId": "v", "eventId": 1, "seats": ["A4", "A4"]},
    "empty seat number": {"bookingId": "v", "eventId": 1, "seats": [""]},
    "seat number > 10 chars": {"bookingId": "v", "eventId": 1, "seats": ["A" * 11]},
    "empty bookingId": {"bookingId": "", "eventId": 1, "seats": ["A4"]},
    "bookingId > 64 chars": {"bookingId": "x" * 65, "eventId": 1, "seats": ["A4"]},
    "eventId 0": {"bookingId": "v", "eventId": 0, "seats": ["A4"]},
    "eventId negative": {"bookingId": "v", "eventId": -1, "seats": ["A4"]},
    "eventId text": {"bookingId": "v", "eventId": "x", "seats": ["A4"]},
    "eventId decimal": {"bookingId": "v", "eventId": 1.5, "seats": ["A4"]},
    "seats as a string": {"bookingId": "v", "eventId": 1, "seats": "A4"},
    "seat number as int": {"bookingId": "v", "eventId": 1, "seats": [4]},
    "bookingId as int": {"bookingId": 42, "eventId": 1, "seats": ["A4"]},
}
for name, body in bad.items():
    err(f"hold: {name}", req("hold", None, None, raw=body), 400, "VALIDATION_ERROR")
err("hold: malformed JSON", client.post(f"{API}/seats/hold", content=b"{bad json",
                                        headers={"Content-Type": "application/json"}), 400, "VALIDATION_ERROR")
err("hold: no body", client.post(f"{API}/seats/hold"), 400, "VALIDATION_ERROR")
for action in ("confirm", "release"):
    err(f"{action}: empty object", req(action, None, None, raw={}), 400, "VALIDATION_ERROR")
check("nothing was held by the invalid requests", seats()["A4"]["status"] == "AVAILABLE")

# ------------------------------------------------------------------------------------------
section("POST /api/v1/seats/confirm")
err("confirm by another booking -> 409 HOLD_EXPIRED", req("confirm", "h2", ["A1"]), 409, "HOLD_EXPIRED")
check("...A1 still HELD by h1", seats()["A1"]["bookingId"] == "h1" and seats()["A1"]["status"] == "HELD")
err("confirm incl. a seat this booking never held -> 409 naming it", req("confirm", "h3", ["A2", "A4"]), 409,
    "HOLD_EXPIRED", "A4")
check("...and A2 was NOT sold (all or none)", seats()["A2"]["status"] == "HELD")
r = req("confirm", "h1", ["A1"])
check("confirm own held seat -> 200 SOLD", r.status_code == 200 and r.json()["status"] == "SOLD", r.text)
check("list shows A1 SOLD, booking kept, expiry cleared",
      seats()["A1"] == {"seatNo": "A1", "status": "SOLD", "bookingId": "h1", "holdExpiresAt": None})
r = req("confirm", "h1", ["A1"])
check("confirm again (retry) -> 200 SOLD, no change", r.status_code == 200 and r.json()["status"] == "SOLD")
err("confirm a SOLD seat as another booking -> 409", req("confirm", "h2", ["A1"]), 409, "HOLD_EXPIRED")
err("confirm an AVAILABLE seat -> 409", req("confirm", "h2", ["B5"]), 409, "HOLD_EXPIRED")
err("hold a SOLD seat -> 409 'already sold'", req("hold", "h2", ["A1"]), 409, "SEAT_UNAVAILABLE", "already sold")
err("confirm an unknown seat -> 404", req("confirm", "h1", ["Z9"]), 404, "SEAT_NOT_FOUND")
err("confirm in an unknown event -> 404", req("confirm", "h1", ["A1"], event=99), 404, "EVENT_NOT_FOUND")
r = req("confirm", "h3", ["A2", "A3"])
check("confirm two held seats together -> 200 SOLD", r.status_code == 200 and seats()["A3"]["status"] == "SOLD")

# ------------------------------------------------------------------------------------------
section("POST /api/v1/seats/release")
req("hold", "r1", ["B1", "B2"])
r = req("release", "r1", ["B1", "B2"])
check("release own held seats -> 200, releasedCount 2",
      r.status_code == 200 and r.json()["releasedCount"] == 2 and r.json()["status"] == "AVAILABLE", r.text)
check("...both AVAILABLE with booking cleared",
      all(seats()[x] == {"seatNo": x, "status": "AVAILABLE", "bookingId": None, "holdExpiresAt": None}
          for x in ("B1", "B2")))
r = req("release", "r1", ["B1", "B2"])
check("release again -> 200, releasedCount 0", r.status_code == 200 and r.json()["releasedCount"] == 0)
r = req("release", "h1", ["A1"])
check("release a SOLD seat -> 200, releasedCount 0 (BR2)", r.status_code == 200 and r.json()["releasedCount"] == 0)
check("...A1 still SOLD", seats()["A1"]["status"] == "SOLD")
req("hold", "r2", ["B1"])
r = req("release", "r3", ["B1"])
check("release another booking's seat -> releasedCount 0", r.json()["releasedCount"] == 0)
check("...B1 still HELD by r2", seats()["B1"]["bookingId"] == "r2")
r = req("release", "r2", ["B1", "B2"])
check("release a mix of own-held and free seats -> frees only own (1)", r.json()["releasedCount"] == 1)
err("release an unknown seat -> 404", req("release", "r2", ["Z9"]), 404, "SEAT_NOT_FOUND")
err("release in an unknown event -> 404", req("release", "r2", ["B1"], event=99), 404, "EVENT_NOT_FOUND")
req("hold", "r4", ["B1"])
req("release", "r4", ["B1"])
check("released seat can be held by a new booking", req("hold", "r5", ["B1"]).status_code == 200)
req("release", "r5", ["B1"])

# ------------------------------------------------------------------------------------------
section("Concurrency (BR1, Challenge 1)")


def parallel(n, fn):
    barrier, out = threading.Barrier(n), [None] * n

    def run(i):
        with httpx.Client(timeout=30) as c:
            barrier.wait()
            out[i] = fn(c, i)
    ts = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


hold_body = lambda b, ss: {"bookingId": b, "eventId": 1, "seats": ss}
codes = parallel(20, lambda c, i: c.post(f"{API}/seats/hold", json=hold_body(f"p{i}", ["B2"])).status_code)
cnt = Counter(codes)
winner = seats()["B2"]["bookingId"]
check("20 parallel holds on one seat -> exactly 1 x 200, 19 x 409", cnt == Counter({200: 1, 409: 19}), str(cnt))
check("...seat HELD by the single winner", seats()["B2"]["status"] == "HELD" and codes[int(winner[1:])] == 200)
confirm_codes = parallel(10, lambda c, i: c.post(f"{API}/seats/confirm", json=hold_body(winner, ["B2"])).status_code)
check("10 parallel confirms by the winner -> all 200, seat SOLD",
      set(confirm_codes) == {200} and seats()["B2"]["status"] == "SOLD", str(Counter(confirm_codes)))

ring = ["A4", "A5", "B1", "B3", "B4"]
want = {i: [ring[i % 5], ring[(i + 1) % 5]] for i in range(20)}
codes = parallel(20, lambda c, i: c.post(f"{API}/seats/hold", json=hold_body(f"o{i}", want[i])).status_code)
after = seats()
winners = [i for i, code in enumerate(codes) if code == 200]
ok = (all(after[x]["bookingId"] == f"o{i}" for i in winners for x in want[i])
      and not any(after[x]["bookingId"] == f"o{i}" for i in range(20) if i not in winners for x in want[i]))
check(f"20 parallel overlapping 2-seat holds -> winners hold both, losers none ({len(winners)} won)",
      ok and set(codes) <= {200, 409}, str(Counter(codes)))
rel = parallel(len(winners) * 2, lambda c, i: c.post(f"{API}/seats/release",
                                                    json=hold_body(f"o{winners[i // 2]}",
                                                                   want[winners[i // 2]])).json()["releasedCount"])
check("parallel duplicate releases free each seat exactly once", sum(rel) == len(winners) * 2, str(rel))
check("...ring seats all AVAILABLE again", all(seats()[x]["status"] == "AVAILABLE" for x in ring))

# ------------------------------------------------------------------------------------------
section("Expiry (BR2)")
r = client.post(f"{API}/seats/expire-holds")
check("POST /seats/expire-holds with nothing expired -> 200 {expiredCount: 0}",
      r.status_code == 200 and r.json() == {"expiredCount": 0}, r.text)
if args.short_url:
    SHORT = f"{args.short_url}/api/v1"
    r = req("hold", "s1", ["A4"], base=SHORT)
    check("[2 s hold instance] hold -> 200", r.status_code == 200, r.text)
    r = req("confirm", "s1", ["A4"], base=SHORT)
    check("[2 s hold] confirm while still valid -> 200 SOLD", r.status_code == 200, r.text)
    req("hold", "s2", ["A5"], base=SHORT)
    time.sleep(3)
    err("[2 s hold] confirm after expiry, before any sweep -> 409 HOLD_EXPIRED", req("confirm", "s2", ["A5"]),
        409, "HOLD_EXPIRED")
    check("...seat was NOT sold", seats()["A5"]["status"] != "SOLD")
    client.post(f"{API}/seats/expire-holds")
    check("...and the sweep frees it", seats()["A5"]["status"] == "AVAILABLE")
else:
    print("  (skipped expired-before-sweep cases: no --short-url)")

r = req("hold", "j1", ["B3", "B4"])
exp = datetime.fromisoformat(r.json()["holdExpiresAt"].replace("Z", "+00:00"))
check("hold B3+B4 for the background-job check", r.status_code == 200)
wait = (exp - datetime.now(timezone.utc)).total_seconds() + args.job_interval + 2
print(f"  ...waiting {wait:.0f} s for the hold to expire; nobody calls the sweep")
time.sleep(wait)
now = seats()
check("background job released B3+B4 on its own",
      all(now[x]["status"] == "AVAILABLE" and now[x]["bookingId"] is None for x in ("B3", "B4")))
check("SOLD seats untouched by the job (A1, A2, A3, B2)", all(now[x]["status"] == "SOLD" for x in ("A1", "A2", "A3", "B2")))
err("expired booking can no longer confirm -> 409", req("confirm", "j1", ["B3", "B4"]), 409, "HOLD_EXPIRED")
first, second = client.post(f"{API}/seats/expire-holds").json(), client.post(f"{API}/seats/expire-holds").json()
check("manual sweep twice afterwards -> 0, 0", first == second == {"expiredCount": 0})

# ------------------------------------------------------------------------------------------
section("Shared error format outside the seat routes (framework defaults)")
r = client.get(f"{API}/does-not-exist")
check("unknown route -> 404", r.status_code == 404)
print(f"  INFO  unknown route body: {r.text}")
r = client.get(f"{API}/seats/hold")
check("wrong method (GET /seats/hold) -> 405", r.status_code == 405)
print(f"  INFO  wrong method body: {r.text}")

print(f"\nTOTAL: {sum(results)} passed, {len(results) - sum(results)} failed, {len(results)} checks")
sys.exit(0 if all(results) else 1)
