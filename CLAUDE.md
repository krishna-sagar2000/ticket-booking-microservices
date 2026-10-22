# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Ticket booking system for a university assignment (SEZG583): four FastAPI services plus a mock payment gateway, Python 3.11+, MySQL 8, one database per service. The repo is currently a scaffold. Each service has `/health` and the shared infrastructure, and the business routes and rules are still TODO.

| Service | Port | Database |
|---|---|---|
| booking-service | 8001 | booking_db |
| seat-service | 8002 | seat_db |
| payment-service | 8003 | payment_db |
| notification-service | 8004 | notification_db |
| mock-gateway | 8005 | none |

## Commands

Each service is a separate Python project with its own `.venv`, `requirements.txt` and `pytest.ini` (`pythonpath = .`). Run commands from inside `services/<name>/`, not from the repo root.

```
# Database (MySQL in Docker, creates the 4 DBs and users via init.sql)
cd scripts/db && docker compose up -d
python scripts/db/check_db.py          # from repo root; expect 4 x OK

# Per service (from services/<name>/)
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --port <port> --reload   # Swagger at /docs

pytest                                        # all tests for this service
pytest tests/test_baseline.py::test_health_is_up   # single test

# All services at once (repo root, PowerShell; opens one window each, needs each .venv to exist)
.\scripts\run_all.ps1
```

## Architecture

**Duplicated, not shared, infrastructure.** Each of the four DB-backed services has the same copies of `app/errors.py`, `app/logging_setup.py`, `app/db.py` and `app/config.py`. Only the service name and default `PORT` differ. There is no shared library. A change to the cross-cutting behaviour has to be made in all four copies. mock-gateway is a separate minimal app without this infrastructure.

**Request flow in `app/main.py`:** an HTTP middleware reads `X-Correlation-Id` (or generates a UUID), stores it in the `correlation_id_var` ContextVar, and echoes it in the response header. The JSON logger and the error handlers read the same ContextVar, so every log line and error body carries the correlation ID automatically. When one service calls another (via httpx), forward this header.

**Errors:** raise `AppError(status, CODE, message)` from business code. The registered handlers render every error, including validation errors (mapped to **400**, not FastAPI's default 422) and unhandled exceptions (500), as `{"code", "message", "correlationId"}`. Do not change this format.

**Where new code goes in each service:** routes under `/api/v1/...` in `app/api/` (include the router in `main.py`), business rules in `app/rules.py`, DB access in `app/db.py`. `db.engine` is `None` when `DB_URL` is unset, so the baseline tests run without MySQL. A service may only touch its own database. Cross-service data goes over HTTP using the `*_SERVICE_URL` env vars.

**mock-gateway** keeps its mode in memory (`state["mode"]`). `POST /admin/mode` with `ok` / `down` (returns 503) / `slow` (sleeps 10 s, longer than `GATEWAY_TIMEOUT_SECONDS=5`) is used to exercise payment failure and timeout paths.

## Team contracts (frozen — see `docs/shared-contracts.md`)

- Booking states: `HELD -> CONFIRMED / CANCELLED / EXPIRED`. Any other transition returns `409 INVALID_STATE_CHANGE`.
- `Idempotency-Key` header on pay. Allowed status codes: 200, 201, 400, 404, 409, 422, 503.
- Env var names are fixed: PORT, DB_URL, SEAT_SERVICE_URL, PAYMENT_SERVICE_URL, NOTIFICATION_SERVICE_URL, GATEWAY_URL, HOLD_SECONDS (30), GATEWAY_TIMEOUT_SECONDS (5).

## Business rules and traceability

Rules BR1–BR4 are defined in `docs/business-rules.md` (seat exclusivity, 30 s hold expiry, payable only while HELD, idempotent payment), along with the expected error codes and the test names. When implementing a rule:
- tag the code with a `# BR<n>: ...` comment in `app/rules.py`
- name its test `test_BR<n>_...` (use the exact names listed in `business-rules.md`)
- update the rule → code → test → evidence row in `evidence/traceability.md`. Evidence for the concurrency, idempotency and hold challenges goes in the matching `evidence/` subfolders.

## Workflow

**Never run `git commit` or `git push` (or anything else that creates commits or updates a remote, such as `git merge` or `git rebase`) in this repo.** The user makes every commit themselves, because commit history counts toward individual marks. Leave changes uncommitted in the working tree and tell the user what is ready to commit.

Each team member owns a service and works on a `<name>/<service>` branch, opening a PR into `main` for review. Never commit `.env` files.
