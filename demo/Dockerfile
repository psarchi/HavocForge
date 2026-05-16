FROM python:3.11-slim

WORKDIR /app

# Slim demo deps only — no asyncpg/aiokafka/google-cloud-pubsub/redis/prometheus.
COPY demo/requirements.txt /app/demo/requirements.txt
RUN pip install --no-cache-dir -r /app/demo/requirements.txt

# Bring in the engine (read-only at runtime via volume in compose).
COPY havocforge /app/havocforge
COPY schemas /app/schemas
COPY config /app/config
COPY demo /app/demo

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HAVOCFORGE_DEMO=1

EXPOSE 8000

CMD ["uvicorn", "demo.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
