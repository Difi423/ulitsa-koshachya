FROM python:3.12.16-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SHELTER_HOST=0.0.0.0 \
    SHELTER_PORT=8000 \
    SHELTER_DB=/app/data/shelter.sqlite3

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 shelter \
    && useradd --uid 10001 --gid 10001 --no-log-init --create-home shelter \
    && mkdir -p /app/data \
    && chown 10001:10001 /app/data

COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY scripts/healthcheck.py ./scripts/healthcheck.py
COPY weather_backend.py serve.py manage.py start.py ./

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=4 \
    CMD ["python", "scripts/healthcheck.py"]
CMD ["python", "serve.py"]
