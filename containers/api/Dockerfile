FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p log

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/v1/health').read()" || exit 1

CMD ["sh", "-c", "mkdir -p /tmp/prom-mp && rm -rf /tmp/prom-mp/* && uvicorn server.app:app --host 0.0.0.0 --port 8000 --workers 4 --loop uvloop"]
