#!/usr/bin/env bash
# One-command demo start. Builds the slim image if needed, brings up the service,
# tails the logs until the API is responsive, then prints the URL.

set -euo pipefail

PORT="${DEMO_PORT:-8080}"
COMPOSE_FILE="docker-compose.demo.yaml"
SERVICE="demo"

cd "$(dirname "$0")/.."

echo "→ building demo image (first run only)"
docker compose -f "$COMPOSE_FILE" build "$SERVICE"

echo "→ starting demo on port $PORT"
docker compose -f "$COMPOSE_FILE" up -d "$SERVICE"

echo -n "→ waiting for /healthz "
for _ in $(seq 1 30); do
  if curl -sf "http://localhost:$PORT/healthz" >/dev/null 2>&1; then
    echo " ok"
    echo ""
    echo "  open:  http://localhost:$PORT/"
    echo "  api:   http://localhost:$PORT/api/generate?schema=smoke&count=5&chaos_ops=truncate"
    echo "  logs:  docker compose -f $COMPOSE_FILE logs -f $SERVICE"
    echo "  down:  scripts/demo-down.sh"
    exit 0
  fi
  echo -n "."
  sleep 1
done

echo ""
echo "✗ demo did not become healthy in 30s. Recent logs:"
docker compose -f "$COMPOSE_FILE" logs --tail 50 "$SERVICE"
exit 1
