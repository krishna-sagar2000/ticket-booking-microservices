"""HTTP calls from Booking to Seat, Payment and Notification.

Rules for every call (shared contracts):
  * the URL comes from config (.env), never hard-coded
  * every call has a timeout
  * X-Correlation-Id is passed on
  * a failure becomes a defined AppError (usually 503), never a crash or a hang

If the team changes another service's request shape, only this file changes.
"""
import logging

import httpx

from . import config
from .errors import AppError
from .logging_setup import correlation_id_var

log = logging.getLogger("booking-service")

API = "/api/v1"


class SeatConfirmRejected(Exception):
    """Seat refused to confirm (e.g. the hold expired at the Seat service)."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message


def _headers(extra: dict | None = None) -> dict:
    headers = {"X-Correlation-Id": correlation_id_var.get()}
    if extra:
        headers.update(extra)
    return headers


def _post(service: str, url: str, body: dict, timeout: float,
          extra_headers: dict | None = None) -> httpx.Response:
    """POST with a timeout. Network problems become 503 <SERVICE>_UNAVAILABLE."""
    unavailable = f"{service.upper()}_SERVICE_UNAVAILABLE"
    try:
        return httpx.post(url, json=body, headers=_headers(extra_headers), timeout=timeout)
    except httpx.TimeoutException:
        log.warning("call to %s timed out after %ss", service, timeout,
                    extra={"target": url})
        raise AppError(503, unavailable, f"{service} service did not answer in time")
    except httpx.HTTPError as exc:
        log.warning("call to %s failed: %s", service, type(exc).__name__, extra={"target": url})
        raise AppError(503, unavailable, f"{service} service is not reachable")


def _error_of(resp: httpx.Response, default_code: str) -> tuple[str, str]:
    try:
        body = resp.json()
        return body.get("code", default_code), body.get("message", resp.text)
    except ValueError:
        return default_code, resp.text or f"HTTP {resp.status_code}"


# ------------------------------------------------------------------ Seat
def _seat_body(booking_id: str, event_id: int, seats: list[str]) -> dict:
    return {"bookingId": booking_id, "eventId": event_id, "seats": seats}


def hold_seats(booking_id: str, event_id: int, seats: list[str]) -> dict:
    """Ask Seat to hold all seats for this booking (all or none)."""
    resp = _post("seat", f"{config.SEAT_SERVICE_URL}{API}/seats/hold",
                 _seat_body(booking_id, event_id, seats), config.SERVICE_TIMEOUT_SECONDS)
    if resp.is_success:
        return resp.json()
    code, message = _error_of(resp, "SEAT_UNAVAILABLE")
    if resp.status_code in (400, 404, 409):
        raise AppError(resp.status_code, code, message)   # pass Seat's answer on
    raise AppError(503, "SEAT_SERVICE_UNAVAILABLE", f"Seat service answered {resp.status_code}")


def confirm_seats(booking_id: str, event_id: int, seats: list[str]) -> None:
    """Ask Seat to turn this booking's held seats into SOLD."""
    resp = _post("seat", f"{config.SEAT_SERVICE_URL}{API}/seats/confirm",
                 _seat_body(booking_id, event_id, seats), config.SERVICE_TIMEOUT_SECONDS)
    if resp.is_success:
        return
    code, message = _error_of(resp, "SEAT_CONFIRM_REJECTED")
    if resp.status_code in (404, 409):
        raise SeatConfirmRejected(code, message)
    raise AppError(503, "SEAT_SERVICE_UNAVAILABLE", f"Seat service answered {resp.status_code}")


def release_seats(booking_id: str, event_id: int, seats: list[str]) -> bool:
    """Best effort: free this booking's held seats. Seat's expiry job is the safety net."""
    try:
        resp = _post("seat", f"{config.SEAT_SERVICE_URL}{API}/seats/release",
                     _seat_body(booking_id, event_id, seats), config.SERVICE_TIMEOUT_SECONDS)
    except AppError:
        log.warning("could not release seats; Seat expiry job will free them",
                    extra={"bookingId": booking_id})
        return False
    if not resp.is_success:
        log.warning("seat release answered %s", resp.status_code, extra={"bookingId": booking_id})
    return resp.is_success


# --------------------------------------------------------------- Payment
APPROVED_STATUSES = {"APPROVED", "SUCCESS", "SUCCEEDED", "PAID", "CAPTURED"}


def charge(booking_id: str, amount: float, idem_key: str) -> dict:
    """Ask Payment to charge the booking. The SAME Idempotency-Key is passed on,
    so a retry of this call can never charge twice (Payment de-duplicates it)."""
    resp = _post("payment", f"{config.PAYMENT_SERVICE_URL}{API}/payments",
                 {"bookingId": booking_id, "amount": amount},
                 config.PAYMENT_TIMEOUT_SECONDS, {"Idempotency-Key": idem_key})
    if resp.is_success:
        body = resp.json()
        status = str(body.get("status", "APPROVED")).upper()
        if status not in APPROVED_STATUSES:
            raise AppError(409, "PAYMENT_DECLINED", f"Payment was not approved ({status})")
        return body
    code, message = _error_of(resp, "PAYMENT_FAILED")
    if resp.status_code in (409, 422):
        raise AppError(resp.status_code, code, message)   # REQUEST_IN_PROGRESS / IDEMPOTENCY_KEY_REUSED
    if resp.status_code == 503:
        raise AppError(503, code or "PAYMENT_GATEWAY_UNAVAILABLE", message)
    if resp.status_code == 400:
        raise AppError(400, code, message)
    raise AppError(503, "PAYMENT_SERVICE_UNAVAILABLE", f"Payment service answered {resp.status_code}")


# ---------------------------------------------------------- Notification
def notify(booking_id: str, kind: str, message: str, recipient: str) -> bool:
    """Best effort. A Notification failure is logged and never fails the booking."""
    try:
        resp = _post("notification", f"{config.NOTIFICATION_SERVICE_URL}{API}/notifications",
                     {"bookingId": booking_id, "type": kind, "message": message,
                      "recipient": recipient},
                     config.SERVICE_TIMEOUT_SECONDS)
    except AppError:
        log.warning("notification not recorded (service down); booking unaffected",
                    extra={"bookingId": booking_id, "type": kind})
        return False
    if not resp.is_success:
        log.warning("notification answered %s; booking unaffected", resp.status_code,
                    extra={"bookingId": booking_id, "type": kind})
    return resp.is_success
