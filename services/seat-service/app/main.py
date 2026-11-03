"""Seat Service - entry point.

Run:  uvicorn app.main:app --port 8002 --reload
Docs: http://localhost:8002/docs
"""
import uuid
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from . import config
from .errors import (AppError, app_error_handler, validation_error_handler,
                     unhandled_error_handler)
from .logging_setup import correlation_id_var, setup_logging

SERVICE_NAME = "seat-service"
log = setup_logging(SERVICE_NAME)

app = FastAPI(title="Seat Service", version="1.0.0")
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


from .api.seats import router as seats_router  # noqa: E402

app.include_router(seats_router)


def openapi_without_422():
    """Validation errors are returned as 400 VALIDATION_ERROR (errors.py), so drop FastAPI's default 422."""
    if app.openapi_schema is None:
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        for ops in schema["paths"].values():
            for op in ops.values():
                op["responses"].pop("422", None)
        for name in ("HTTPValidationError", "ValidationError"):
            schema.get("components", {}).get("schemas", {}).pop(name, None)
        app.openapi_schema = schema
    return app.openapi_schema


app.openapi = openapi_without_422
