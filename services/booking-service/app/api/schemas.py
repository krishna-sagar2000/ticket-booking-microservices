"""Request and response shapes (they also become the Swagger / OpenAPI docs).

JSON uses camelCase (eventId, customerEmail), like the gateway and the error format.
snake_case (event_id, customer_email) is also accepted, so either team convention works.
"""
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CreateBookingRequest(_CamelModel):
    event_id: int = Field(gt=0, examples=[1])
    seats: list[str] = Field(min_length=1, examples=[["A1", "A2"]])
    customer_email: str = Field(max_length=255, pattern=EMAIL_PATTERN,
                                examples=["asha@example.com"])


class BookingResponse(_CamelModel):
    booking_id: str
    event_id: int
    seats: list[str]
    customer_email: str
    amount: float
    status: str = Field(description="HELD | CONFIRMED | CANCELLED | EXPIRED")
    hold_expires_at: str | None
    payment_id: str | None = None
    created_at: str | None


class ExpireResponse(_CamelModel):
    expired_count: int


class ErrorResponse(BaseModel):
    code: str
    message: str
    correlationId: str
