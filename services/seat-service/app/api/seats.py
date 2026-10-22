"""Seat routes under /api/v1/seats. Thin layer: validate input, call rules, return the result."""
from contextlib import asynccontextmanager

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from .. import db, rules


@asynccontextmanager
async def lifespan(app):
    """Create + seed the seats table on startup (merged into the app by include_router)."""
    if db.engine is not None:
        db.init_db()
    yield


router = APIRouter(prefix="/api/v1/seats", tags=["seats"], lifespan=lifespan)


class SeatAction(BaseModel):
    # booking-service ids are INTs in its own DB; accept 42 as well as "42"
    model_config = ConfigDict(coerce_numbers_to_str=True)

    bookingId: str = Field(min_length=1, max_length=64)


@router.get("")
def list_seats():
    return rules.list_seats()


@router.post("/expire-holds")
def expire_holds():
    return rules.expire_holds()


@router.post("/{seat_id}/hold")
def hold(seat_id: int, body: SeatAction):
    return rules.hold(seat_id, body.bookingId)


@router.post("/{seat_id}/confirm")
def confirm(seat_id: int, body: SeatAction):
    return rules.confirm(seat_id, body.bookingId)


@router.post("/{seat_id}/release")
def release(seat_id: int, body: SeatAction):
    return rules.release(seat_id, body.bookingId)
