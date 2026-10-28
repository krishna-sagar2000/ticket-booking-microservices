# Mock Payment Gateway - Dockerfile
# Build:  docker build -t mock-gateway -f services/mock-gateway/Dockerfile services/mock-gateway
# Run:    docker run -p 8005:8005 --env-file services/mock-gateway/.env mock-gateway
#
# Configuration (PORT) is supplied entirely through environment variables at run time
# (see .env.example) - nothing is hard-coded here. This service has no database and
# no secrets to protect.

FROM python:3.11-slim

WORKDIR /app

# Install dependencies first so Docker can cache this layer when only app code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY app ./app

# Run as a non-root user.
RUN useradd --create-home appuser
USER appuser

# Default port; actual value always comes from the PORT env var at run time.
EXPOSE 8005

# `exec` inside sh -c lets ${PORT} expand from the environment at container start
# (with 8005 as the fallback), while still replacing the shell process with uvicorn
# so SIGTERM/SIGINT reach the application directly for a clean shutdown.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8005}"]
