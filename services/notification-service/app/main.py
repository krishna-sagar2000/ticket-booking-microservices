"""Notification Service - entry point.

Run:  uvicorn app.main:app --port 8004 --reload
Docs: http://localhost:8004/docs
"""
import uuid
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from . import config
from .errors import (AppError, app_error_handler, validation_error_handler,
                     unhandled_error_handler)
from .logging_setup import correlation_id_var, setup_logging

SERVICE_NAME = "notification-service"
log = setup_logging(SERVICE_NAME)

app = FastAPI(title="Notification Service", version="1.0.0")
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


# TODO (owner): add your routes under /api/v1/... in app/api/ and include the router here.
# TODO (owner): put business rules in app/rules.py and database code in app/db.py.
