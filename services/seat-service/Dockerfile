# Seat Service image. Settings (DB_URL, PORT, HOLD_SECONDS, ...) come from environment
# variables at run time; no .env file or password is baked into the image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8002

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# init_db() runs schema.sql and seed.sql from the folder above app/ on startup.
COPY schema.sql seed.sql ./
COPY app ./app

RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8002

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=2)"

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
