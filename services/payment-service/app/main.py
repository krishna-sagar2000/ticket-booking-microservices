"""Payment Service - entry point.

Run:  uvicorn app.main:app --port 8003 --reload
Docs: http://localhost:8003/docs
"""
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from . import config, db
from .api.payments import router as payments_router
from .errors import (AppError, app_error_handler, validation_error_handler,
                     unhandled_error_handler)
from .logging_setup import correlation_id_var, setup_logging

SERVICE_NAME = "payment-service"
log = setup_logging(SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Creates payment_db tables from schema.sql if missing. Safe to run every
    # startup (CREATE TABLE IF NOT EXISTS) - a fresh clone needs no manual
    # `mysql ... < schema.sql` step, matching seat-service and
    # notification-service.
    db.init_db()
    log.info("payment_db tables ensured")
    yield


app = FastAPI(title="Payment Service", version="1.0.0", lifespan=lifespan)
app.include_router(payments_router)
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
