# Quickstart

No config required to get started. Clone the repo, run one command, and you're generating data. This walks you through the basics - starting the stack, hitting the API, writing your first schema, and trying out chaos injection.

## Prerequisites

- Docker + Docker Compose
- `curl` or any HTTP client

## 1. Clone and start

```bash
git clone https://github.com/<your-org>/havocforge.git
cd havocforge
make up
```

`make up` auto-generates a `.env` from the config files and boots everything. First run takes a bit longer - it's pulling images.

Services that come up:

| Service | Port |
|---------|------|
| API | 8000 |
| Redis | 6379 |
| PostgreSQL | 5432 |
| Prometheus | 9090 |
| Grafana | 3000 |

## 2. Check it's alive

```bash
curl http://localhost:8000/v1/health
```

```json
{"status": "ok", "ts": "2025-01-12T10:30:45.123456Z"}
```

## 3. See what schemas are available

Two schemas ship with the repo out of the box:

```bash
curl http://localhost:8000/v1/schemas
```

```json
{"schemas": ["ga4", "smoke"], "count": 2}
```

- **smoke** - a test schema covering every generator type. Good for kicking the tires.
- **ga4** - Google Analytics 4 event shape. More realistic, nested structure.

## 4. Generate some data

```bash
# single item
curl http://localhost:8000/v1/schemas/smoke/generate

# 10 items
curl "http://localhost:8000/v1/schemas/smoke/generate?count=10"

# deterministic - same seed always gives same output
curl "http://localhost:8000/v1/schemas/smoke/generate?seed=42&count=5"
```

## 5. Add your own schema

Create a YAML file in `schemas/`:

```yaml
# schemas/user.yaml
type: object
fields:
  user_id:
    type: string
    template: "user-{nnnn}"
    n_type: numeric
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
  created_at:
    type: timestamp
    start: '2024-01-01T00:00:00+00:00'
    end: '2025-12-31T23:59:59+00:00'
```

Restart the API to pick it up:

```bash
make restart api
curl http://localhost:8000/v1/schemas/user/generate
```

Already have JSON data? You can bootstrap a schema from it - see the [Schema Guide](schema-guide.md#json-to-yaml-converter).

## 6. Try chaos injection

Force chaos ops via the `chaos_ops` param - comma-separated list of op names:

```bash
curl "http://localhost:8000/v1/schemas/smoke/generate?count=10&chaos_ops=schema_field_nulling,latency"
```

You'll get null fields, added latency, corrupt payloads - depending on which ops you pass. Full list in [Chaos Engineering](chaos.md).

## Common commands

```bash
make up             # start everything
make down           # stop everything
make restart api    # restart API (pick up schema changes)
make logs           # tail all logs
make health         # check service status
make clean          # stop + remove containers
```

## Troubleshooting

**Port already in use** - edit `docker-compose.yaml` and change the host port mapping.

**Schema not found after adding a file** - run `make restart api`. Schemas load on startup.

**Slow first request** - the pre-generation worker is warming up the cache in the background. Subsequent requests will be fast.
