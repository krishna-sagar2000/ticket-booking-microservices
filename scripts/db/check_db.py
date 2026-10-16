"""Checks that all four service databases can be reached with their own credentials.

Run from the repo root:  python scripts/db/check_db.py
Needs:  pip install sqlalchemy pymysql cryptography
"""
from sqlalchemy import create_engine, text

URLS = {
    "booking_db": "mysql+pymysql://booking_user:booking_pass@localhost:3306/booking_db",
    "seat_db": "mysql+pymysql://seat_user:seat_pass@localhost:3306/seat_db",
    "payment_db": "mysql+pymysql://payment_user:payment_pass@localhost:3306/payment_db",
    "notification_db": "mysql+pymysql://notification_user:notification_pass@localhost:3306/notification_db",
}

ok = True
for name, url in URLS.items():
    try:
        with create_engine(url).connect() as c:
            c.execute(text("SELECT 1"))
        print(f"OK    {name}")
    except Exception as e:
        ok = False
        print(f"FAIL  {name}: {e}")
raise SystemExit(0 if ok else 1)
