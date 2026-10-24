"""Routes for notification-service, under /api/v1/...

Endpoints:
    POST /api/v1/notifications              -> record a notification
    GET  /api/v1/notifications/{bookingId}  -> list notifications for a booking
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import db
from ..errors import AppError
from ..logging_setup import setup_logging
from ..rules import validate_type

log = setup_logging("notification-service")

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


class NotificationCreate(BaseModel):
    bookingId: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1)


class NotificationOut(BaseModel):
    id: int
    bookingId: str
    type: str
    message: str
    createdAt: str


def _to_out(row: db.Notification) -> NotificationOut:
    return NotificationOut(
        id=row.id,
        bookingId=row.booking_id,
        type=row.type,
        message=row.message,
        createdAt=row.created_at.isoformat(),
    )


@router.post("", status_code=201)
def create_notification(body: NotificationCreate):
    if not validate_type(body.type):
        raise AppError(400, "VALIDATION_ERROR", "type must be a non-empty string up to 64 chars")

    session = db.SessionLocal()
    try:
        row = db.Notification(
            booking_id=body.bookingId,
            type=body.type,
            message=body.message,
        )
        session.add(row)
        session.commit()
        session.refresh(row)

        # "Sending" the notification = logging it. No real email/SMS, by design (out of scope).
        log.info(
            "notification recorded id=%s bookingId=%s type=%s",
            row.id, row.booking_id, row.type,
        )

        return {"notificationId": row.id}
    finally:
        session.close()


@router.get("/{booking_id}", response_model=list[NotificationOut])
def list_notifications(booking_id: str):
    session = db.SessionLocal()
    try:
        rows = (
            session.query(db.Notification)
            .filter(db.Notification.booking_id == booking_id)
            .order_by(db.Notification.created_at.asc())
            .all()
        )
        return [_to_out(r) for r in rows]
    finally:
        session.close()
