# `demo/` — slim public-facing playground

A single-page comparison view that calls the Havocforge engine in-process to
show clean vs chaos-corrupted output side-by-side. Stripped of everything that
needs persistence, brokers, or background workers:

- ❌ no Redis, no Postgres, no Kafka/Pub/Sub
- ❌ no streaming, no pre-generation worker
- ❌ no admin endpoints, no auth, no metrics surface
- ✅ in-memory only, single process, hard caps on count + per-IP rate

## Run locally

```bash
scripts/demo-up.sh                  # build + up + wait for health
open http://localhost:8080/         # the page
scripts/demo-down.sh                # stop
```

Or by hand:

```bash
docker compose -f docker-compose.demo.yaml up -d
```

## What's exposed

| Method | Path                                       | What                                                                  |
| ------ | ------------------------------------------ | --------------------------------------------------------------------- |
| `GET`  | `/`                                        | The page                                                              |
| `GET`  | `/healthz`                                 | `{"status":"ok"}`                                                     |
| `GET`  | `/api/schemas`                             | List of preset schemas (smoke, ga4, patient, stream_events)           |
| `GET`  | `/api/ops`                                 | Categorised chaos-op catalog with demo-availability flags             |
| `GET`  | `/api/generate?schema=…&count=…&chaos_ops=…` | The headline endpoint — runs both clean + chaos, returns both halves |

`count` is capped at 50. Per-IP rate limit is 30 req/min (in-memory; resets on
container restart). Three ops are advertised but reject server-side with a
helpful error: `burst`, `schema_drift`, `data_drift` — they need real WS or
Redis-backed state to be meaningful.

## Structure

```
demo/
├── app.py              # FastAPI: serves /, /api/*; uses havocforge engine in-process
├── rate_limit.py       # in-memory per-IP token bucket
├── requirements.txt    # slim deps — no asyncpg/aiokafka/google-cloud-pubsub/redis
├── Dockerfile          # python:3.11-slim, single-process uvicorn
├── static/
│   ├── index.html      # the page
│   ├── style.css       # archils.dev-aligned aesthetic, dark default + light toggle
│   └── app.js          # vanilla JS — no build step, no node_modules
├── cloudflared/
│   ├── config.yml.example
│   └── README.md       # how to wire up havoc.archils.dev when you're ready
└── README.md           # (this file)
```

## Going public

When you want the demo on the internet, see [`cloudflared/README.md`](cloudflared/README.md).
The TL;DR: install `cloudflared`, `cloudflared tunnel create havocforge-demo`,
copy `cloudflared/config.yml.example` to `~/.cloudflared/config.yml`, fill in
the UUID, `cloudflared tunnel route dns havocforge-demo havoc.archils.dev`,
install as a systemd service. The demo container itself doesn't change.

## Iterating on the page

The `static/` directory is bind-mounted read-only into the container at runtime
(see `docker-compose.demo.yaml`), so editing HTML/CSS/JS doesn't require a
rebuild — just hard-refresh the browser. `app.py` and `rate_limit.py` are also
mounted, so a `docker compose -f docker-compose.demo.yaml restart demo` is
enough to pick up Python changes.

## What it's not

- It is **not** the full project. It's a CV / showcase surface with a small
  blast radius. The full deployment (`make up`) is in the repo root.
- It is **not** a load-test target. Per-IP rate limiting is in-memory and
  trivial to bypass with multiple IPs. Don't run benchmarks against the public
  URL — clone and run locally instead.
- It does **not** persist anything. Every request is fresh. Drift ops are
  marked unavailable for that reason.
