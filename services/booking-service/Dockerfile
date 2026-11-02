# Booking service image (Assignment 2).
# Build:  docker build -t ticket-booking/booking-service:1.0 services/booking-service
# All settings (DB_URL, service URLs, HOLD_SECONDS, ...) come from environment variables
# at run time. No .env file and no password is copied into the image (see .dockerignore).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8001

WORKDIR /app

# Dependencies first: this layer is reused until requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Application code and the schema files only (no tests, dev stubs or .env).
COPY app ./app
COPY schema.sql seed.sql ./

# Do not run as root inside the container.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8001

# Docker marks the container healthy only when GET /health answers.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8001'), timeout=2)"]

# 0.0.0.0, not 127.0.0.1: inside a container, 127.0.0.1 is unreachable from other containers.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
