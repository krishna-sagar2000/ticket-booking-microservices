"""Booking endpoints under /api/v1. They read the request, call the flow, return JSON.
No business logic here: rules are in app/rules.py, orchestration in app/booking_flow.py.
"""
import re

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from .. import booking_flow
from ..errors import AppError
from .schemas import BookingResponse, CreateBookingRequest, ErrorResponse, ExpireResponse

router = APIRouter(prefix="/api/v1", tags=["bookings"])

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.]{1,100}$")


def _errors(*codes: int) -> dict:
    return {c: {"model": ErrorResponse} for c in codes}


@router.post("/bookings", status_code=201, response_model=BookingResponse,
             responses=_errors(400, 404, 409, 503),
             summary="Create a booking and hold its seats (state HELD)")
def create_booking(body: CreateBookingRequest):
    return booking_flow.create_booking(body.event_id, body.seats, body.customer_email)


@router.get("/bookings/{booking_id}", response_model=BookingResponse,
            responses=_errors(404), summary="Read a booking")
def get_booking(booking_id: str):
    return booking_flow.get_booking(booking_id)


@router.post("/bookings/{booking_id}/pay", response_model=BookingResponse,
             responses=_errors(400, 404, 409, 422, 503),
             summary="Pay for a HELD booking (Idempotency-Key header required)")
def pay_booking(booking_id: str,
                idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    if not idempotency_key:
        raise AppError(400, "VALIDATION_ERROR", "Idempotency-Key header is required")
    if not _KEY_PATTERN.match(idempotency_key):
        raise AppError(400, "VALIDATION_ERROR",
                       "Idempotency-Key must be 1-100 characters: letters, digits, - _ : .")
    status, body, replayed = booking_flow.pay_with_idempotency(
        booking_id, idempotency_key, f"/api/v1/bookings/{booking_id}/pay")
    headers = {"Idempotent-Replayed": "true" if replayed else "false"}
    return JSONResponse(status_code=status, content=body, headers=headers)


@router.post("/bookings/{booking_id}/cancel", response_model=BookingResponse,
             responses=_errors(404, 409), summary="Cancel a HELD booking and release its seats")
def cancel_booking(booking_id: str):
    return booking_flow.cancel(booking_id)


@router.post("/bookings/expire", response_model=ExpireResponse,
             summary="Mark HELD bookings whose hold has passed as EXPIRED (safe to run twice)")
def expire_bookings():
    return booking_flow.expire_due()
