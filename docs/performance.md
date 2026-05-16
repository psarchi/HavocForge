# Performance

Full single-instance bench matrix for Havocforge. 30 cells across worker
scaling, feature cost, concurrency, WebSocket streaming, schema complexity,
and pre-generation worker fill rate. Reproducible — bench scripts and
compose override are checked in.

## Test methodology

All measurements taken on the same host with the API container pinned to
`cpus: N` + `mem_limit: N×2g` and uvicorn `WORKERS=N` (matches a self-hosted
single-instance deployment with N cores allocated).

**Host:** AMD Ryzen 7 5800X · 31 GB host RAM · client and server on the same
host (client CPU unconstrained, on different cores). **5800X is roughly 2× a
typical cloud vCPU** — budget VPS will see ≈ 40–60 % of these numbers.

**Schemas tested:**

- `smoke` — 15 root fields, exercises all 14 generator types
- `ga4` — nested `device` / `geo` / `event_params` / `items`, heavier
- `patient` — 9 fields, 8 of them `bound_to: patient_id` for cross-schema
  correlation (exercises the sync Redis lookup path)
- `stream_events` — lightweight event records, simplest of the four

## A. Worker scaling × batch size

`smoke` schema, chaos off, metrics off. Concurrency=50 for `batch≤10`,
concurrency=1 for `batch=1000`. 500 requests per cell (5 for `batch=1000`).

| Workers | Batch | items/sec | req/sec | p50    | p95    | p99    |
| ------- | ----- | --------- | ------- | ------ | ------ | ------ |
| 1       | 1     | 376       | 384     | 123 ms | 173 ms | 177 ms |
| 1       | 10    | 892       | 92      | 319 ms | 2.65 s | 2.68 s |
| 1       | 1000  | **4,190** | 4.2     | 240 ms | 246 ms | 246 ms |
| 2       | 1     | 663       | 696     | 62 ms  | 135 ms | 140 ms |
| 2       | 10    | 3,062     | 318     | 145 ms | 299 ms | 327 ms |
| 2       | 1000  | 4,241     | 4.2     | 237 ms | 239 ms | 239 ms |
| 4       | 1     | 874       | 894     | 51 ms  | 74 ms  | 78 ms  |
| 4       | 10    | 5,575     | 575     | 76 ms  | 181 ms | 209 ms |
| 4       | 1000  | 4,281     | 4.3     | 233 ms | 238 ms | 238 ms |
| 8       | 1     | 842       | 873     | 53 ms  | 72 ms  | 89 ms  |
| 8       | 10    | **7,278** | 750     | 48 ms  | 160 ms | 173 ms |
| 8       | 1000  | 4,172     | 4.2     | 239 ms | 246 ms | 246 ms |

- `batch=10` scales near-linearly through 4 workers, then drops to ~30 % gain
  at 8 — GIL pressure on the generator + threadpool contention.
- `batch=1` is HTTP/serialization bound; even 8 workers can't push it past
  ~870 items/sec.
- `batch=1000` is bottlenecked by a single generator (one big request can't
  be parallelised across workers), so the number is flat ~4,200 regardless
  of `WORKERS`.

## B. Feature cost (chaos × metrics)

`WORKERS=1`, smoke, batch=10, concurrency=20, 500 requests per cell:

| Chaos | Metrics | items/sec | non‑2xx | p50    | p95    |
| ----- | ------- | --------- | ------- | ------ | ------ |
| off   | off     | **887**   | 16      | 124 ms | 189 ms |
| off   | on      | 417       | 18      | 370 ms | 447 ms |
| on    | off     | 898       | 10      | 124 ms | 207 ms |
| on    | on      | 437       | 17      | 361 ms | 466 ms |

- **Metrics middleware costs ~50 % of single-core throughput.** Prometheus
  histogram observations on every request are not free. For load-sensitive
  deployments, push metrics to a sidecar via `/metrics` scrape only — keep
  middleware off the hot path.
- Chaos at default probabilities (`p=0.01` per op) is effectively free — the
  decision-tree sampler is cheap when most ops don't fire.

## C. Concurrency sweep at `WORKERS=4`

smoke, batch=10, 300 requests per cell:

| Concurrency | items/sec | req/sec | p50    | p95     | p99     |
| ----------- | --------- | ------- | ------ | ------- | ------- |
| 1           | 1,861     | 189     | 5 ms   | 6 ms    | 7 ms    |
| 5           | **6,311** | 653     | 7 ms   | 12 ms   | 15 ms   |
| 10          | 5,254     | 540     | 20 ms  | 29 ms   | 35 ms   |
| 50          | 5,588     | 576     | 68 ms  | 133 ms  | 162 ms  |
| 100         | 1,014     | 102     | 146 ms | 2.6 s   | 2.6 s   |
| 200         | 2,402     | 245     | 673 ms | 981 ms  | 1.0 s   |

Sweet spot at `c=5`. Throughput collapses at `c=100` (likely threadpool
saturation — `asyncio.to_thread` default pool size is ~`min(32, cpu+4)`).
Production should rate-limit upstream to keep concurrency below the knee.

## D. WebSocket sustained throughput

`smoke`, `max_events=20000`, `pop_size=500`, one WS connection per row:

| Workers | items/sec sustained |
| ------- | ------------------- |
| 1       | **3,601**           |
| 2       | 2,569               |
| 4       | 3,616               |

A single WS connection sticks to one worker, so `WORKERS>1` doesn't help one
stream — these rows essentially measure the same single-worker path with
queue-state variance (the W=2 dip happened when the pre-gen queue had drained
and the path fell back to live generation). The takeaway is the per-connection
ceiling of ~3,600 items/sec from the pre-gen queue (LPOP + orjson + WS
framing). Multi-worker scaling kicks in when you have many concurrent
connections.

## E. Schema complexity

`WORKERS=4`, batch=10, concurrency=50, 200 requests per cell, chaos off:

| Schema          | items/sec | p50    | p95     | Notes                                           |
| --------------- | --------- | ------ | ------- | ----------------------------------------------- |
| `stream_events` | **6,561** | 63 ms  | 106 ms  | Lightweight events — fastest                    |
| `smoke`         | 5,072     | 64 ms  | 206 ms  | All 14 generator types — middle                 |
| `ga4`           | 4,159     | 84 ms  | 241 ms  | Nested device/geo/event_params — heavier        |
| `patient`       | **757**   | 82 ms  | 2.56 s  | **8 `bound_to` fields × per-record Redis GET**  |

`patient` is **slow by design**, not a bug. It uses cross-schema correlation:
every field is `bound_to: patient_id`, so each generated record triggers 8
sync Redis lookups inside `ObjectGenerator._generate_impl()`. The price you
pay for "same `patient_id` always gets the same name". Schemas without
correlation are 5–10× faster.

## F. Pre-generation worker fill rate

Single gen-worker process pinned to `cpus: 1.0` + `mem_limit: 2g`. Both
`smoke` and `ga4` are pregen targets (per `config/default/generation.yaml`).
Both queues drained, then `LLEN` sampled every second for 60 s:

| Schema | Fill rate           |
| ------ | ------------------- |
| smoke  | 691 items/sec       |
| ga4    | 711 items/sec       |
| **combined** | **1,403 items/sec** |

This is the ceiling for "WebSocket streaming sustained throughput" — the WS
consumer is fast enough that the pre-gen worker is the bottleneck on a single
core. Running 2× gen-worker processes (`GEN_WORKERS=2`) roughly doubles the
ceiling.

## Reproduce these numbers

```bash
# Start support services (redis, postgres, generation-worker)
docker compose -f docker-compose.yaml -f docker-compose.bench.yaml up -d \
    redis postgres generation-worker

# Full matrix — the script orchestrates api recreations for each (workers, chaos, metrics) combo
python3 tests/perf/bench_matrix.py > bench_results.md

# Or just the single-config bench (no orchestration)
docker compose -f docker-compose.yaml -f docker-compose.bench.yaml up -d --force-recreate api
python3 tests/perf/bench.py
```

Output is markdown — paste directly into a fresh perf report. Raw JSON is
also saved to `/tmp/bench_results.json` for further analysis.

The bench scripts (`tests/perf/bench.py` + `tests/perf/bench_matrix.py`) and
the override compose file (`docker-compose.bench.yaml`) are checked in. The
matrix script handles all reconfiguration — edits `chaos.yaml` / `server.yaml`
between rows automatically. To customise: edit the matrix definitions in
`bench_matrix.py` (the rows are explicit, not generated).
