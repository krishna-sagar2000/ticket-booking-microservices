"""One error format for every service: {"code", "message", "correlationId"}."""
from fastapi import Request
from fastapi.responses import JSONResponse
from .logging_setup import correlation_id_var


class AppError(Exception):
    """Raise this from business code, e.g. AppError(409, "SEAT_UNAVAILABLE", "Seat already taken")."""

    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message


def error_body(code: str, message: str) -> dict:
    return {"code": code, "message": message, "correlationId": correlation_id_var.get()}


async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message))


async def validation_error_handler(request: Request, exc):
    return JSONResponse(status_code=400, content=error_body("VALIDATION_ERROR", "Request is not valid"))


async def unhandled_error_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content=error_body("INTERNAL_ERROR", "Something went wrong"))
