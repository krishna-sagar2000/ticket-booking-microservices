"""Seat routes under /api/v1. Thin layer: validate input, call rules, return the result."""
import asyncio
from contextlib import asynccontextmanager, suppress
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints, field_validator

from .. import db, expiry_job, rules


@asynccontextmanager
async def lifespan(app):
    """On startup: create + seed the tables, then start the expiry job (merged in by include_router)."""
    if db.engine is None:  # no DB_URL (e.g. baseline tests): nothing to set up
        yield
        return
    db.init_db()
    job = asyncio.create_task(expiry_job.run_forever())
    yield
    job.cancel()
    with suppress(asyncio.CancelledError):
        await job


router = APIRouter(prefix="/api/v1", tags=["seats"], lifespan=lifespan)

# Upper-cased so " a1 " and "A1" are the same seat on every database (MySQL compares
# case-insensitively, SQLite does not) and the duplicate check below sees them as one.
SeatNo = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=10)]


class SeatRequest(BaseModel):
    """Body of hold / confirm / release: which seats of which event, for which booking."""
    bookingId: str = Field(min_length=1, max_length=64, examples=["b-123"])
    eventId: int = Field(ge=1, examples=[1])
    seats: list[SeatNo] = Field(min_length=1, max_length=10, examples=[["A1", "A2"]])

    @field_validator("seats")
    @classmethod
    def no_duplicates(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("seats must not repeat")
        return v


@router.get("/events/{event_id}/seats", summary="List the seats of an event and their status")
def list_seats(event_id: int):
    return rules.list_seats(event_id)


@router.post("/seats/hold", summary="Hold seats for a booking, all or none (BR1)")
def hold(body: SeatRequest):
    return rules.hold_seats(body.bookingId, body.eventId, body.seats)


@router.post("/seats/confirm", summary="Turn this booking's held seats into SOLD")
def confirm(body: SeatRequest):
    return rules.confirm_seats(body.bookingId, body.eventId, body.seats)


@router.post("/seats/release", summary="Free this booking's held seats (SOLD seats are never freed)")
def release(body: SeatRequest):
    return rules.release_seats(body.bookingId, body.eventId, body.seats)


@router.post("/seats/expire-holds", summary="Run the BR2 expiry sweep now (the background job also runs it)")
def expire_holds():
    return rules.expire_holds()
