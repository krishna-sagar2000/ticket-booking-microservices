"""Settings read from environment variables (see .env.example)."""
import os
from dotenv import load_dotenv

load_dotenv()

PORT = int(os.getenv("PORT", "8002"))
DB_URL = os.getenv("DB_URL", "")
SEAT_SERVICE_URL = os.getenv("SEAT_SERVICE_URL", "http://localhost:8002")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://localhost:8003")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://localhost:8004")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8005")
HOLD_SECONDS = int(os.getenv("HOLD_SECONDS", "30"))
GATEWAY_TIMEOUT_SECONDS = float(os.getenv("GATEWAY_TIMEOUT_SECONDS", "5"))

# --- Seat-service specific settings ----------------------------------------
# How often the background job releases expired holds (BR2).
EXPIRY_INTERVAL_SECONDS = float(os.getenv("EXPIRY_INTERVAL_SECONDS", "5"))
