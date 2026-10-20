
"""Payment API routes."""
from decimal import Decimal

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from ..rules import process_payment

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


class PaymentRequest(BaseModel):
    bookingId: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


@router.post("", status_code=201)
def create_payment(
    body: PaymentRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1),
):
    return process_payment(
        booking_id=body.bookingId,
        amount=body.amount,
        idempotency_key=idempotency_key,
    )
