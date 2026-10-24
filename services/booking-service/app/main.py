"""Booking Service - entry point.

Run:  uvicorn app.main:app --port 8001 --reload
Docs: http://localhost:8001/docs
"""
import uuid
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from . import config
from .errors import (AppError, app_error_handler, validation_error_handler,
                     unhandled_error_handler)
from .logging_setup import correlation_id_var, setup_logging

SERVICE_NAME = "booking-service"
log = setup_logging(SERVICE_NAME)

app = FastAPI(title="Booking Service", version="1.0.0")
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    cid = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
    correlation_id_var.set(cid)
    log.info("request %s %s", request.method, request.url.path)
    response = await call_next(request)
    response.headers["X-Correlation-Id"] = cid
    log.info("response %s", response.status_code)
    return response


@app.get("/health", tags=["health"])
def health():
    return {"status": "UP", "service": SERVICE_NAME}


# Owner: booking routes live in app/api/bookings.py, rules in app/rules.py,
# the cross-service flow in app/booking_flow.py and SQL in app/db.py.
from .api.bookings import router as bookings_router  # noqa: E402

app.include_router(bookings_router)
