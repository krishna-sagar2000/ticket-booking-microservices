"""DEV ONLY - stand-ins for Seat, Payment and Notification, so the Booking owner can run
and demo the full flow before the real services are merged. In-memory, no database.
NOT part of the submitted system. Stop using a stub as soon as the real service works.

Run each in its own terminal, from services/booking-service (venv active):
    uvicorn dev.stubs:seat_app         --port 8002
    uvicorn dev.stubs:payment_app      --port 8003
    uvicorn dev.stubs:notification_app --port 8004
and the real mock gateway from services/mock-gateway:
    uvicorn app.main:app --port 8005

They follow the request shapes Booking sends (see app/clients.py):
    Seat    POST /api/v1/seats/{hold|confirm|release}  {"bookingId","eventId","seats":[..]}
    Payment POST /api/v1/payments  header Idempotency-Key, {"bookingId","amount"}
    Notif.  POST /api/v1/notifications {"bookingId","type","message","recipient"}
"""
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

HOLD_SECONDS = int(os.getenv("HOLD_SECONDS", "30"))
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8005")
GATEWAY_TIMEOUT_SECONDS = float(os.getenv("GATEWAY_TIMEOUT_SECONDS", "5"))


def _err(status, code, message, request: Request):
    return JSONResponse(status_code=status, content={
        "code": code, "message": message,
        "correlationId": request.headers.get("X-Correlation-Id", "-")})


def _now():
    return datetime.now(timezone.utc)


# ===================================================================== Seat
seat_app = FastAPI(title="Seat Service STUB")
_seat_lock = threading.Lock()
# event 1 has seats A1-A5 and B1-B5
_seats = {(1, f"{r}{n}"): {"status": "AVAILABLE", "booking": None, "until": None}
          for r in "AB" for n in range(1, 6)}


def _expire_holds():
    """BR2 stand-in: a HELD seat past its time becomes AVAILABLE; SOLD is never touched."""
    for s in _seats.values():
        if s["status"] == "HELD" and s["until"] <= _now():
            s.update(status="AVAILABLE", booking=None, until=None)


@seat_app.get("/health")
def seat_health():
    return {"status": "UP", "service": "seat-service-STUB"}


@seat_app.get("/api/v1/events/{event_id}/seats")
def list_seats(event_id: int):
    with _seat_lock:
        _expire_holds()
        return [{"seatNo": k[1], "status": v["status"], "bookingId": v["booking"]}
                for k, v in sorted(_seats.items()) if k[0] == event_id]


@seat_app.post("/api/v1/seats/hold")
async def hold(request: Request):
    b = await request.json()
    keys = [(b["eventId"], s) for s in b["seats"]]
    with _seat_lock:                      # check-and-set under one lock = atomic
        _expire_holds()
        for k in keys:
            if k not in _seats:
                return _err(404, "SEAT_NOT_FOUND", f"Seat {k[1]} does not exist", request)
            if _seats[k]["status"] != "AVAILABLE":
                return _err(409, "SEAT_UNAVAILABLE", f"Seat {k[1]} is already taken", request)
        until = _now() + timedelta(seconds=HOLD_SECONDS)
        for k in keys:                    # all or none
            _seats[k].update(status="HELD", booking=b["bookingId"], until=until)
    return {"bookingId": b["bookingId"], "seats": b["seats"], "status": "HELD",
            "holdExpiresAt": until.isoformat()}


@seat_app.post("/api/v1/seats/confirm")
async def confirm(request: Request):
    b = await request.json()
    keys = [(b["eventId"], s) for s in b["seats"]]
    with _seat_lock:
        _expire_holds()
        for k in keys:
            s = _seats.get(k)
            ok = s and s["booking"] == b["bookingId"] and s["status"] in ("HELD", "SOLD")
            if not ok:
                return _err(409, "HOLD_EXPIRED", f"Seat {k[1]} is not held by this booking",
                            request)
        for k in keys:                    # idempotent: SOLD by the same booking stays SOLD
            _seats[k].update(status="SOLD", until=None)
    return {"bookingId": b["bookingId"], "seats": b["seats"], "status": "SOLD"}


@seat_app.post("/api/v1/seats/release")
async def release(request: Request):
    b = await request.json()
    with _seat_lock:
        for s in b["seats"]:
            seat = _seats.get((b["eventId"], s))
            if seat and seat["booking"] == b["bookingId"] and seat["status"] == "HELD":
                seat.update(status="AVAILABLE", booking=None, until=None)
    return {"bookingId": b["bookingId"], "seats": b["seats"], "status": "AVAILABLE"}


# ================================================================== Payment
payment_app = FastAPI(title="Payment Service STUB")
_pay_lock = threading.Lock()
_by_key: dict[str, dict] = {}          # Idempotency-Key -> {"hash", "state", "response"}
_payments: list[dict] = []


@payment_app.get("/health")
def payment_health():
    return {"status": "UP", "service": "payment-service-STUB"}


@payment_app.get("/api/v1/payments")
def list_payments():
    return _payments


@payment_app.post("/api/v1/payments")
async def create_payment(request: Request,
                         idem_key: str | None = Header(default=None, alias="Idempotency-Key")):
    body = await request.json()
    fingerprint = f"{body.get('bookingId')}|{body.get('amount')}"
    if not idem_key:
        return _err(400, "VALIDATION_ERROR", "Idempotency-Key header is required", request)
    with _pay_lock:
        seen = _by_key.get(idem_key)
        if seen:
            if seen["hash"] != fingerprint:
                return _err(422, "IDEMPOTENCY_KEY_REUSED", "Key used with another body", request)
            if seen["state"] == "IN_PROGRESS":
                return _err(409, "REQUEST_IN_PROGRESS", "Same key still running", request)
            return JSONResponse(status_code=201, content=seen["response"])
        _by_key[idem_key] = {"hash": fingerprint, "state": "IN_PROGRESS", "response": None}

    try:
        async with httpx.AsyncClient(timeout=GATEWAY_TIMEOUT_SECONDS) as http:
            r = await http.post(
                f"{GATEWAY_URL}/charge",
                json={"bookingId": body["bookingId"], "amount": body["amount"]},
                headers={"X-Correlation-Id": request.headers.get("X-Correlation-Id", "-")})
        ok = r.status_code == 200
    except httpx.HTTPError:
        ok = False
    if not ok:
        with _pay_lock:
            del _by_key[idem_key]         # transient failure: allow retry with same key
        return _err(503, "PAYMENT_GATEWAY_UNAVAILABLE", "Payment gateway is down or slow",
                    request)

    response = {"paymentId": str(uuid.uuid4()), "bookingId": body["bookingId"],
                "amount": body["amount"], "status": "APPROVED"}
    with _pay_lock:
        _by_key[idem_key].update(state="DONE", response=response)
        _payments.append(response)
    return JSONResponse(status_code=201, content=response)


# ============================================================= Notification
notification_app = FastAPI(title="Notification Service STUB")
_notes: list[dict] = []


@notification_app.get("/health")
def notification_health():
    return {"status": "UP", "service": "notification-service-STUB"}


@notification_app.post("/api/v1/notifications", status_code=201)
async def record(request: Request):
    body = await request.json()
    _notes.append({**body, "createdAt": _now().isoformat()})
    return {"notificationId": len(_notes)}


@notification_app.get("/api/v1/notifications/{booking_id}")
def for_booking(booking_id: str):
    return [n for n in _notes if n.get("bookingId") == booking_id]
