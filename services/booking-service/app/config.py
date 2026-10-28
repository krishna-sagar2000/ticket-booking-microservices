"""Settings read from environment variables (see .env.example)."""
import os
from dotenv import load_dotenv

load_dotenv()

PORT = int(os.getenv("PORT", "8001"))
DB_URL = os.getenv("DB_URL", "")
SEAT_SERVICE_URL = os.getenv("SEAT_SERVICE_URL", "http://localhost:8002")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://localhost:8003")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://localhost:8004")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8005")
HOLD_SECONDS = int(os.getenv("HOLD_SECONDS", "30"))
GATEWAY_TIMEOUT_SECONDS = float(os.getenv("GATEWAY_TIMEOUT_SECONDS", "5"))

# --- Booking-service specific settings -------------------------------------
# Price of one seat. The price is decided by the server, never sent by the client.
SEAT_PRICE = float(os.getenv("SEAT_PRICE", "250.00"))
# Upper limit on seats in one booking (input validation).
MAX_SEATS_PER_BOOKING = int(os.getenv("MAX_SEATS_PER_BOOKING", "6"))
# Timeout for calls to Seat and Notification.
SERVICE_TIMEOUT_SECONDS = float(os.getenv("SERVICE_TIMEOUT_SECONDS", "3"))
# Timeout for the call to Payment. Must be LONGER than Payment's own gateway
# timeout (GATEWAY_TIMEOUT_SECONDS), otherwise Booking gives up while Payment
# may still succeed.
PAYMENT_TIMEOUT_SECONDS = float(os.getenv("PAYMENT_TIMEOUT_SECONDS", "8"))
# A payment lock older than this is treated as abandoned (e.g. the process crashed mid-payment).
PAY_LOCK_TTL_SECONDS = int(os.getenv("PAY_LOCK_TTL_SECONDS", "60"))
