#!/usr/bin/env bash
# Stop the demo. Doesn't remove the image — re-up is fast.

set -euo pipefail

cd "$(dirname "$0")/.."

docker compose -f docker-compose.demo.yaml down
echo "→ demo stopped. Image preserved; run scripts/demo-up.sh to bring it back."
