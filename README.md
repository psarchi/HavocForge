# Havocforge — Chaos-injectable synthetic data engine for FastAPI

[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.117-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D.svg?logo=redis&logoColor=white)](https://redis.io/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED.svg?logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![Tests](https://img.shields.io/badge/tests-45_passing-brightgreen.svg)](#testing)

YAML-defined schemas, 19 chaos operations, WebSocket streaming, dual-layer persistence. Built for stress-testing the things downstream of fake data — ETL jobs, stream consumers, dashboards, alerting rules — under realistic failure conditions.

```bash
# Generate 1000 GA4 events with truncation, latency, and schema drift
curl "http://localhost:8000/v1/schemas/ga4/generate?count=1000&chaos_ops=truncate,latency,schema_drift"
```

## Use cases

- **Stress-test data pipelines** that consume Kafka / Pub/Sub / REST without a real producer.
- **Populate staging environments** with millions of correlated records (same `customer_id` consistent across `orders`, `payments`, `events`).
- **Reproduce production incidents** in CI: encoding corruption, late arrivals, partial loads, schema drift across revisions.
- **Develop dashboards & alerting rules** against streamed events without waiting for real traffic.
- **Demo data** for SaaS prototypes and customer-facing previews — deterministic seeded output, persistable to retrieve later.

## Havocforge vs alternatives

|                              | **Havocforge**            | Faker          | Mockaroo            | polyfactory         | Mostly AI            |
| ---------------------------- | ------------------------- | -------------- | ------------------- | ------------------- | -------------------- |
| Schema definition            | YAML contracts            | Python code    | GUI form            | Pydantic models     | learned from real data |
| Output                       | REST + WebSocket          | in-process     | CSV/JSON/SQL via UI | in-process          | CSV / Parquet         |
| Fault injection / chaos      | **19 ops, schema drift**  | —              | —                   | —                   | —                     |
| Cross-record correlation     | **pools, `bound_to`**     | manual         | limited             | manual              | implicit              |
| Per-user state (monotonic)   | **yes (Redis-backed)**    | manual         | —                   | manual              | —                     |
| High-throughput streaming    | **pre-generated queue**   | n/a            | n/a                 | n/a                 | n/a                   |
| Self-hosted                  | **Docker Compose**        | library        | SaaS only           | library             | both                  |
| Built-in observability       | **Prometheus + Grafana**  | —              | —                   | —                   | —                     |

Havocforge is the only one of these that ships chaos as a first-class feature, exposes everything over an API, and treats correlation across schemas as a primitive rather than something you bolt on.

## Quickstart

```bash
git clone https://github.com/<your-username>/havocforge.git
cd havocforge
make up      # auto-generates .env from config/default/*.yaml, brings up the stack

curl http://localhost:8000/v1/health
# {"status":"ok","ts":"..."}
```

Stack: API (8000), Grafana (3000), Prometheus (9090), Redis (6379), PostgreSQL (5432).

## Architecture

```
                     HTTP / WebSocket
   ┌──────────┐ ─────────────────────▶ ┌────────────────────────────────┐
   │  Client  │                        │  FastAPI server (uvicorn)      │
   └──────────┘ ◀───────────────────── │  ┌──────────┐  ┌─────────────┐ │
                                       │  │ /schemas │  │ /streaming/ │ │
                                       │  │ /data    │  │   handler   │ │
                                       │  │ /publish │  │   state     │ │
                                       │  │ /admin/* │  │   chaos     │ │
                                       │  └────┬─────┘  └──────┬──────┘ │
                                       └───────┼───────────────┼────────┘
                                               ▼               ▼
                                  ┌──────────────────┐  ┌────────────────┐
                                  │ Generator        │  │ Chaos manager  │
                                  │ pipeline (sync,  │◀─│ 19 ops + drift │
                                  │ via to_thread)   │  │ coordinator    │
                                  └────────┬─────────┘  └────────────────┘
                                           │
                          ┌────────────────┼─────────────────┐
                          ▼                ▼                 ▼
                  ┌──────────────┐  ┌────────────┐  ┌──────────────────┐
                  │   Redis      │  │ PostgreSQL │  │ Kafka / Pub/Sub  │
                  │ hot cache +  │  │ durable    │  │ batch publishers │
                  │ pregen queue │  │ datasets   │  │                  │
                  └──────┬───────┘  └────────────┘  └──────────────────┘
                         ▲
                         │ enqueue batches
                  ┌──────┴────────┐
                  │ pre-generation│
                  │ workers (N)   │
                  └───────────────┘
```

The pre-generation worker continuously fills a Redis-backed queue per schema. WebSocket streams pop from it for low-latency delivery and fall back to live generation when empty. REST generation goes through the same pipeline but synchronously — wrapped in `asyncio.to_thread()` because the cross-schema correlation lookup uses a sync Redis client (see [Architectural notes](#architectural-notes)).

## API tour

### List schemas

```bash
curl http://localhost:8000/v1/schemas
# {"schemas":["ga4","patient","pool_order","pool_user","smoke","smoke_cross_schema","stream_events"],"count":7}
```

### Generate

```bash
# single record
curl http://localhost:8000/v1/schemas/smoke/generate

# batch of 100
curl "http://localhost:8000/v1/schemas/smoke/generate?count=100"

# deterministic (same seed = same output for non-stateful fields)
curl "http://localhost:8000/v1/schemas/smoke/generate?seed=42&count=10"

# persist returns an id you can retrieve later
ID=$(curl -s "http://localhost:8000/v1/schemas/ga4/generate?count=50" | jq -r .id)
curl "http://localhost:8000/v1/data/$ID/items"
```

### Define a schema

```yaml
# schemas/user.yaml
type: object
fields:
  user_id:
    type: string
    template: "user-{nnnn}"
  email:
    type: string
    string_type: "internet.email"
  age:
    type: int
    min: 18
    max: 90
  is_active:
    type: bool
    p_true: 0.8
  registered_at:
    type: timestamp
    start: "2024-01-01T00:00:00Z"
    end: "2025-12-31T23:59:59Z"
```

`make restart api` and it's live at `/v1/schemas/user/generate`. Bootstrap from a JSON sample with `tools/json_to_schema.py`.

### Inject chaos

Force specific ops via `chaos_ops=`:

```bash
curl "http://localhost:8000/v1/schemas/smoke/generate?count=10&chaos_ops=schema_field_nulling,latency,truncate&include_metadata=true"
```

The 19 ops, by category:

| Category   | Ops                                                                                              |
| ---------- | ------------------------------------------------------------------------------------------------ |
| Body       | `truncate`, `schema_field_nulling`, `schema_bloat`, `duplicate_items`, `list_shuffle`, `late_arrival`, `time_skew`, `schema_time_skew`, `encoding_corrupt`, `partial_load` |
| Status     | `http_error`, `http_mismatch`, `auth_fault`                                                      |
| Server     | `latency`                                                                                        |
| Header     | `header_anomaly`, `random_header_case`                                                           |
| Network    | `burst` (signals streaming rate-limiter)                                                         |
| Drift      | `schema_drift`, `data_drift` (via `/v1/schemas/generate-preview`)                                |

Default behavior is probabilistic — configure rates and budgets in `config/default/chaos.yaml`. See [`docs/chaos.md`](docs/chaos.md) for what each op does.

### Stream

```python
import asyncio, json, websockets

async def stream():
    uri = "ws://localhost:8000/v1/schemas/user/stream?count=100&max_events=1000"
    async with websockets.connect(uri) as ws:
        async for msg in ws:
            event = json.loads(msg)
            if event.get("type") == "event":
                print(event["seq"], event["data"])

asyncio.run(stream())
```

Resume per-user state across reconnects with `?user_id=<id>`. Force chaos per-stream with `?forced_chaos=truncate,encoding_corrupt`.

## Agents (LLM-assisted authoring)

Two agents under [`agents/`](agents/README.md), backed by any LiteLLM-supported model (default: local `ollama_chat/qwen3:8b`, also tested with Anthropic / OpenAI):

```bash
# natural-language → valid Havocforge YAML schema, with validation loop + sample records
python -m agents.cli schema "a user with email, age 18-90, signup date in 2024"

# natural-language → chaos.yaml profile via multi-step tool calling
python -m agents.cli chaos "stress test Black Friday checkout — bursts, latency, schema drift"
```

The schema agent runs single-tool structured output (one `emit_schema` call, validated via the engine's own `build_schema` and retried on error). The chaos agent runs multi-step tool calling with discrete tools (`enable_op`, `set_budget`, `set_selection`, `finalize`) and validates against the live op registry before emitting YAML. See [`agents/README.md`](agents/README.md) for the model matrix, config precedence (CLI > env > `~/.havocforge/agent.toml` > default), and programmatic API.

## Tech stack

`Python 3.11` · `FastAPI` · `uvicorn` · `Pydantic v2` · `asyncio` · `WebSockets` ·
`Redis 7` (hot cache + pregen queue) · `PostgreSQL 16` (durable storage) ·
`asyncpg` · `aiokafka` · `google-cloud-pubsub` ·
`Faker` · `exrex` · `orjson` · `uvloop` ·
`Prometheus` (metrics) · `Grafana` (dashboards) · `structlog` ·
`Docker Compose` · `pytest` · `ruff` · `mypy`

## Performance

Single-instance benchmark on AMD Ryzen 7 5800X (≈ 2× a typical cloud vCPU,
so budget VPS will see 40–60 % of these). Headline numbers below; **full
30-cell matrix with latency p50/p95/p99, worker scaling, chaos / Prometheus
cost, schema complexity, and pre-generation worker throughput in
[`docs/performance.md`](docs/performance.md)** plus reproduction commands.

| What                                                         | items/sec     |
| ------------------------------------------------------------ | ------------- |
| REST burst, `WORKERS=8`, batch=10, c=50, smoke               | **7,278**     |
| REST single big request, `count=1000`, smoke                 | 4,190         |
| WebSocket sustained, one connection, from pre-gen queue      | 3,601         |
| Pre-generation worker, combined smoke + ga4, single CPU      | 1,403         |
| Schema with 8 `bound_to` fields (`patient`)                  | 757           |

Three things worth knowing without reading the full report:

- **REST throughput scales near-linearly to `WORKERS=4`**, then drops to ~30 % gain at 8 (GIL pressure on the generator path).
- **Prometheus metrics middleware halves single-core throughput** (887 → 417 items/sec). For load-sensitive deployments, scrape `/metrics` from a sidecar and disable the per-request middleware.
- **`bound_to` correlation costs you** — one sync Redis GET per bound field per record. The `patient` schema hits 757 items/sec instead of ~5,000 because every field is `bound_to: patient_id`. Trade-off for "same id always gets the same name."

Reproduce with `python3 tests/perf/bench_matrix.py` after `docker compose -f docker-compose.yaml -f docker-compose.bench.yaml up -d`. Full instructions in [`docs/performance.md`](docs/performance.md#reproduce-these-numbers).

## Architectural notes

A few non-obvious things worth knowing if you're hacking on this:

- **Generation is sync, called from async handlers.** `server/routers/schemas.py` and the streaming live-fallback path off-load generation via `asyncio.to_thread()` because the cross-schema correlation lookup uses a sync Redis client (the lookup runs *inside* `havocforge/generators/composites/object.py` where async is impractical). Don't replace `to_thread` with a direct call — it'll freeze the event loop.
- **Publishers are constructed at lifespan start, not per-request.** Kafka / Pub/Sub publisher objects live on `app.state` and are built in `init_publishers_from_config()`. The previous module-level lazy-init had a race between concurrent first-requests; do not reintroduce it.
- **Streaming endpoint is a package, not a file.** `server/routers/streaming/` decomposes a previously-793-line god file into `handler.py` (WebSocket lifecycle), `state.py` (per-user state), `chaos_apply.py`, `live.py`, `profiler.py`. Router re-exported from `__init__.py`.
- **Config is YAML-only.** `ConfigManager.get_value()` reads from `config/default/*.yaml`. The `.env` file is for docker-compose port/URL injection, *not* for app behavioral config.
- **Drift ops use a separate coordinator.** `schema_drift` and `data_drift` mutate the registered schema across revisions instead of mutating output items; they're invoked through `/v1/schemas/generate-preview` which has the special handling.

## Configuration

YAML in `config/default/`. Override by creating `config/<file>.yaml` (gitignored).

| File              | Purpose                                                                  |
| ----------------- | ------------------------------------------------------------------------ |
| `server.yaml`     | API server, persistence, observability, streaming, profiler, security    |
| `generation.yaml` | RNG, generator defaults, pre-generation worker                           |
| `chaos.yaml`      | Chaos op enable/probability/budgets                                      |

## Testing

```bash
make test                   # full pytest suite (45 unit tests, ~6 skipped)
make test ARGS='-m integration'   # integration suite — requires running stack
```

End-to-end smoke verified by curl-sweeping all 49 HTTP endpoints + 19 chaos ops via `tests/smoke/curl_sweep.sh` — see `CHANGELOG.md` for the full list of bugs surfaced and fixed during validation.

## Repository layout

```
havocforge/
├── havocforge/          # Core engine
│   ├── chaos/           # 19 chaos ops + drift coordinators
│   ├── contracts/       # Typed schema specifications (Pydantic)
│   ├── generators/      # Leaf, composite, and stateful generators
│   ├── persistence/     # Redis + PostgreSQL clients, batch sync, metrics collector
│   ├── pregeneration/   # Background pre-gen worker
│   ├── schema/          # YAML loader, validator, registry
│   └── observability/   # Prometheus instrumentation
├── server/              # FastAPI application
│   ├── routers/         # /v1 endpoints (schemas, data, streaming/, publish, admin/*, users)
│   ├── middleware/      # Correlation IDs, metrics, chaos response
│   └── publishers/      # Kafka + Pub/Sub adapters
├── schemas/             # YAML data contracts (ships with smoke + ga4 + a few examples)
├── config/default/      # server.yaml / generation.yaml / chaos.yaml
├── containers/          # Per-service Dockerfiles + Grafana / Prometheus configs
├── migrations/          # PostgreSQL schema migrations
├── tools/               # json_to_schema converter
├── scripts/             # Misc CLI helpers (env generation)
├── tests/               # Unit + integration tests
└── docs/                # API / chaos / configuration / quickstart reference
```

## Tools

### `tools/json_to_schema.py`

Bootstrap a YAML schema from a JSON sample:

```bash
curl https://api.example.com/user | python tools/json_to_schema.py > schemas/user.yaml
python tools/json_to_schema.py examples.json --infer-arrays --sample-size 100
```

See [`tools/README.md`](tools/README.md) for the type-detection rules.

## Known limitations

- `havocforge/generators/composites/object.py` and `havocforge/context.py` are large. Splitting them is on a separate scoped branch — the cross-schema correlation pass has a subtle ordering invariant that's easy to break.
- ~190 broad `except Exception` blocks remain. The two most dangerous (silent correlation failures and silent stateful-field discovery) have been narrowed and now log with full tracebacks; the rest are mostly graceful degradation around best-effort writes.
- `containers/grafana/dashboards/` ships with two dashboards renamed from the upstream project; field labels inside the JSON may still show the old wording. They render correctly; the rename is cosmetic.

## Status

Pre-1.0. Public APIs may change between minor versions. Suitable for development, testing, and CI; not for production traffic.

## License

MIT — see [LICENSE](LICENSE). All generated data is synthetic and intended for development and testing purposes only.
