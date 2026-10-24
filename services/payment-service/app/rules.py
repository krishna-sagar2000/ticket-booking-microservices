
"""Payment business rules, including BR4 idempotency."""
import hashlib
import json
import logging
from decimal import Decimal

import httpx
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from . import config
from .db import engine
from .errors import AppError
from .logging_setup import correlation_id_var

log = logging.getLogger("payment-service")


def _json(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def process_payment(
    booking_id: str,
    amount: Decimal,
    idempotency_key: str,
) -> dict:
    """BR4: replay identical requests; reject key reuse with a different body."""
    if engine is None:
        raise AppError(503, "DATABASE_UNAVAILABLE", "Payment database is not configured")

    request_body = {
        "bookingId": booking_id,
        "amount": format(amount, ".2f"),
    }
    request_hash = hashlib.sha256(_json(request_body).encode()).hexdigest()

    # Claim the key using its database primary key. A concurrent request with
    # the same key will be handled by the duplicate-key path below.
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO idempotency_keys
                        (idem_key, request_hash, status)
                    VALUES (:key, :request_hash, 'IN_PROGRESS')
                """),
                {"key": idempotency_key, "request_hash": request_hash},
            )
    except IntegrityError:
        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT request_hash, status, response_code, response_body
                    FROM idempotency_keys
                    WHERE idem_key = :key
                """),
                {"key": idempotency_key},
            ).mappings().first()

        if row is None:
            raise AppError(503, "PAYMENT_STATE_UNAVAILABLE", "Could not read payment state")

        if row["request_hash"] != request_hash:
            raise AppError(
                422,
                "IDEMPOTENCY_KEY_REUSED",
                "Idempotency-Key was already used with a different request",
            )

        if row["status"] == "IN_PROGRESS":
            raise AppError(
                409,
                "REQUEST_IN_PROGRESS",
                "A request with this Idempotency-Key is still processing",
            )

        
        saved_body = row["response_body"]
        if isinstance(saved_body, str):
            saved_body = json.loads(saved_body)

        response_code = int(row["response_code"])

        if response_code >= 400:
            raise AppError(
                response_code,
                saved_body.get("code", "PAYMENT_FAILED"),
                saved_body.get("message", "Payment failed"),
            )

        log.info("Idempotent payment replay for booking %s", booking_id)
        return saved_body


    # Prevent another idempotency key from charging the same booking.
    # Reserve the booking before contacting the gateway.
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO payments (booking_id, amount, status)
                    VALUES (:booking_id, :amount, 'PROCESSING')
                """),
                {"booking_id": booking_id, "amount": amount},
            )
    except IntegrityError:
        body = {
            "code": "PAYMENT_ALREADY_EXISTS",
            "message": "A payment already exists for this booking",
        }
        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE idempotency_keys
                    SET status = 'DONE', response_code = 409, response_body = :body
                    WHERE idem_key = :key
                """),
                {"key": idempotency_key, "body": _json(body)},
            )
        raise AppError(409, body["code"], body["message"])

    cid = correlation_id_var.get()
    gateway_url = config.GATEWAY_URL.rstrip("/") + "/charge"

    try:
        response = httpx.post(
            gateway_url,
            json={"bookingId": booking_id, "amount": float(amount)},
            headers={"X-Correlation-Id": cid},
            timeout=config.GATEWAY_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        gateway_body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Payment gateway unavailable: %s", type(exc).__name__)
        body = {
            "code": "PAYMENT_GATEWAY_UNAVAILABLE",
            "message": "Payment gateway is unavailable",
        }
        with engine.begin() as conn:
            # The gateway being down is retryable: do NOT mark the idempotency
            # key as DONE, and remove the payment reservation. Otherwise a
            # retry with the SAME key after the gateway recovers would be
            # replayed forever as the cached 503 and could never succeed.
            # Compare to booking-service's db.idem_drop() for the same pattern.
            conn.execute(
                text("DELETE FROM payments WHERE booking_id = :booking_id"),
                {"booking_id": booking_id},
            )
            conn.execute(
                text("DELETE FROM idempotency_keys WHERE idem_key = :key"),
                {"key": idempotency_key},
            )
        raise AppError(503, body["code"], body["message"])

    result = {
        "bookingId": booking_id,
        "amount": format(amount, ".2f"),
        "status": gateway_body.get("status", "APPROVED"),
    }
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE payments
                SET status = 'CONFIRMED', gateway_response = :gateway_response
                WHERE booking_id = :booking_id
            """),
            {
                "booking_id": booking_id,
                "gateway_response": _json(gateway_body),
            },
        )
        conn.execute(
            text("""
                UPDATE idempotency_keys
                SET status = 'DONE', response_code = 201, response_body = :body
                WHERE idem_key = :key
            """),
            {"key": idempotency_key, "body": _json(result)},
        )

    return result
