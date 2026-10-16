# Ticket Booking - Microservices (SEZG583 Assignment 1)

Four services + a mock payment gateway. Python 3.11+ / FastAPI / MySQL 8. Database per service.

| Service | Port | Database | Owner |
|---|---|---|---|
| booking-service | 8001 | booking_db | ________ |
| seat-service | 8002 | seat_db | ________ |
| payment-service | 8003 | payment_db | ________ |
| notification-service | 8004 | notification_db | ________ |
| mock-gateway | 8005 | none | ________ |

## First-time setup (everyone)
1. Install Python 3.11+, Git, Docker Desktop.
2. Clone the repo and open it in VS Code.
3. Start the database (once per day):
   ```
   cd scripts/db
   docker compose up -d
   cd ../..
   ```
4. Check the databases: `pip install sqlalchemy pymysql cryptography` then `python scripts/db/check_db.py` (expect 4 x OK).
5. Go to your service folder and follow its README.

## Working rules
- Work on your own branch: `git checkout -b <yourname>/<service>`; small commits under your own name.
- Open a pull request into `main`; your review partner approves it.
- `git pull origin main` every morning.
- Never commit `.env` or real passwords (the passwords here are fake, local only).
- Everything the team agreed is in `docs/shared-contracts.md` and `docs/business-rules.md`.
