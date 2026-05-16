# Configuration

The engine is configured through three YAML files covering the server, data generation, and chaos behavior. You probably won't need to touch most of it - the defaults are reasonable for local use. But when you do need to change something (different Redis URL, higher pregen queue, more aggressive chaos), this is where you do it.

Defaults live in `config/default/` - you override them by creating matching files in `config/` (gitignored). Environment variables override everything.

```
config/
  default/
    server.yaml      ← committed defaults
    generation.yaml
    chaos.yaml
  server.yaml        ← your local overrides (gitignored)
  generation.yaml
  chaos.yaml
```

The config reloads automatically when files change (SHA1-based detection) so you usually don't need to restart.

---

## server.yaml

### Server

| Key | Default | Description |
|-----|---------|-------------|
| `server.port` | `8000` | HTTP port |
| `server.workers` | `8` | Uvicorn worker count |
| `server.debug.enabled` | `false` | FastAPI debug mode |

### Persistence

| Key | Default | Description |
|-----|---------|-------------|
| `server.persistence.enabled` | `true` | Turn off to skip all Redis/PostgreSQL writes |
| `server.persistence.persist_by_default` | `true` | Persist every request unless `?persist=false` |
| `server.persistence.redis.url` | `redis://redis:6379` | Redis connection URL |
| `server.persistence.redis.ttl_hours` | `24` | How long datasets live in Redis |
| `server.persistence.redis.maxmemory` | `10gb` | Redis max memory |
| `server.persistence.redis.maxmemory_policy` | `allkeys-lru` | Eviction policy |
| `server.persistence.postgres.url` | `postgresql://havocforge:havocforge@postgres:5432/havocforge` | Postgres connection URL |
| `server.persistence.postgres.retention_days` | `30` | How long datasets live in Postgres |

### Streaming

| Key | Default | Description |
|-----|---------|-------------|
| `server.streaming.batch_pop_size` | `5000` | Items popped from Redis per WebSocket iteration |
| `server.streaming.rate_limit_enabled` | `false` | Enable streaming rate limiter |
| `server.streaming.base_rate` | `1000` | Items/sec cap (if rate limiting is on) |
| `server.streaming.increment_mode` | `sequential` | Stateful field mode: `sequential` or `wallclock` |
| `server.streaming.apply_chaos_in_consumer` | `true` | Apply chaos ops in streaming consumer |

### Observability

| Key | Default | Description |
|-----|---------|-------------|
| `server.observability.logging.enabled` | `false` | Structured logging on/off |
| `server.observability.logging.level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `server.observability.logging.format` | `json` | `json` or `console` |
| `server.observability.metrics_enabled` | `false` | Expose `/metrics` Prometheus endpoint |

### Security

| Key | Default | Description |
|-----|---------|-------------|
| `server.security.mode` | `none` | Auth mode: `none`, `basic`, or `jwt` |
| `server.security.pii_mode` | `passthrough` | PII handling: `passthrough`, `mask`, `tokenize`, `redact` |

---

## generation.yaml

Controls how data gets generated and cached.

| Key | Default | Description |
|-----|---------|-------------|
| `generation.seed_mode` | `fixed` | `auto` (random seed each request) or `fixed` (always same seed) |
| `generation.fixed_seed` | `123` | The fixed seed value (only used when `seed_mode=fixed`) |
| `generation_meta.enabled` | `true` | Include `__meta` block in responses |
| `generation_meta.include_gen_ms` | `true` | Include generation time in meta |
| `generation_meta.include_e2e_ms` | `true` | Include end-to-end handler time in meta |

### Pre-generation

Background workers that pre-fill a Redis queue so high-throughput requests don't block on generation.

| Key | Default | Description |
|-----|---------|-------------|
| `pregeneration.enabled` | `true` | Consume from pre-gen cache |
| `pregeneration.fallback_to_live` | `true` | If cache is empty, generate on the fly |
| `pregeneration.require_cache` | `false` | If true and cache is empty, return an error instead of falling back |
| `pregeneration.schemas` | `[ga4, smoke]` | Which schemas get pre-generated |
| `pregeneration.queue_size` | `100000` | Target queue depth per schema |
| `pregeneration.batch_size` | `100` | Items the worker pushes per batch |
| `pregeneration.global_max_items` | `null` | Global cap across all schemas (null = unlimited) |

### Temporal

Controls how `stateful_timestamp` and `stateful_datetime` fields advance.

| Key | Default | Description |
|-----|---------|-------------|
| `temporal.default_mode` | `actual_time_based` | `actual_time_based` (advance with real time) or `per_generation` (fixed step per record) |
| `temporal.time_multiplier` | `1.0` | Speed multiplier for `actual_time_based` - `2.0` = double speed, `0.5` = half speed |

---

## chaos.yaml

### Global settings

| Key | Default | Description |
|-----|---------|-------------|
| `chaos.enabled` | `true` | Master kill switch for all chaos |
| `chaos.selection.min_ops` | `0` | Min ops to apply per request when chaos fires |
| `chaos.selection.max_ops` | `9999` | Max ops to apply per request |
| `chaos.selection.ensure_at_least_one_when_any_enabled` | `true` | Force one op when chaos is requested but none activate probabilistically |
| `chaos.budgets.max_added_latency_ms` | `1500` | Total latency budget per request |
| `chaos.budgets.max_faults_per_request` | `999` | Max fault ops per request |

### Per-op config

Every op has the same three base settings plus op-specific params:

```yaml
chaos:
  ops:
    latency:
      enabled: false   # toggle this op
      p: 0.1           # 0.0–1.0 activation probability
      weight: 5.26     # relative selection weight
      min_ms: 60       # op-specific
      max_ms: 300
```

See [Chaos Engineering](chaos.md) for what each op does and its specific params.

---

## Common overrides

**Disable persistence entirely:**
```yaml
# config/server.yaml
server:
  persistence:
    enabled: false
```

**Use random seeds (different output every request):**
```yaml
# config/generation.yaml
generation:
  seed_mode: auto
```

**Crank up pre-gen queue for high throughput:**
```yaml
# config/generation.yaml
pregeneration:
  queue_size: 500000
  batch_size: 500
  schemas: [ga4, smoke, your_schema]
```

**Enable logging in console format (easier during dev):**
```yaml
# config/server.yaml
server:
  observability:
    logging:
      enabled: true
      format: console
      level: DEBUG
```

**Make chaos more aggressive:**
```yaml
# config/chaos.yaml
chaos:
  ops:
    schema_field_nulling:
      enabled: true
      p: 0.3   # 30% of requests
    latency:
      enabled: true
      p: 0.2
      min_ms: 200
      max_ms: 1000
```

---

## Environment variables

Every config key maps to an env var - replace dots with underscores and uppercase. Some common ones:

```bash
SERVER_PORT=8000
SERVER_WORKERS=4
PERSISTENCE_REDIS_URL=redis://localhost:6379
PERSISTENCE_POSTGRES_URL=postgresql://user:pass@localhost:5432/havocforge
PREGENERATION_ENABLED=true
SERVER_OBSERVABILITY_LOGGING_ENABLED=true
SERVER_OBSERVABILITY_LOGGING_FORMAT=console
```

Env vars win over both `config/` and `config/default/`.
