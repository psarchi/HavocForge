# Changelog

All notable changes to this project are documented here. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); pre-1.0 versions may
include breaking changes between minor versions.

## [0.2.0] — 2026-05-16

LLM-assisted authoring: two agents that turn natural language into valid
Havocforge config.

### Added

- **`agents/` package** — two provider-agnostic agents on top of
  [LiteLLM](https://docs.litellm.ai/) (one interface, 100+ providers):
  - **Schema designer** (`agents/schema/designer.py`) — single-tool pattern.
    Model emits a schema via the `emit_schema` tool; agent validates via
    `havocforge.schema.builder.build_schema`, retries up to 3× on error with
    the validation message fed back, then runs a sample generation.
  - **Chaos designer** (`agents/chaos/designer.py`) — multi-step tool calling.
    Discrete tools (`enable_op`, `set_budget`, `set_selection`, `finalize`)
    build a chaos profile incrementally; agent validates every enabled op
    against the live registry (`Registry.get_all(BaseChaosOp)`) before
    emitting YAML.
- **CLI** — `python -m agents.cli {schema|chaos} "..."` with `--model`,
  `--api-base`, `--temperature`, `--out`, `-v` flags. Config precedence:
  CLI > env (`HAVOCFORGE_AGENT_MODEL`) > `~/.havocforge/agent.toml` > default
  (`ollama_chat/qwen3:8b`).
- **System prompts as versionable Markdown** (`agents/prompts/*.md`) — the
  schema prompt catalogues every generator type + parameter; the chaos prompt
  catalogues all 19 ops grouped by category with heuristics for common
  scenarios ("Q4 traffic", "schema migration", etc.).
- New optional dependency: `litellm>=1.84.0`. Pulled in only when the
  `agents/` package is used.

### Verified

- End-to-end with local `ollama_chat/qwen3:8b` (Ollama, 5.2 GB, free): both
  agents complete in 1 turn on representative prompts. Schema agent produced
  valid configs for simple user / nested e-commerce order on first attempt;
  chaos agent picked the right op set + probabilities for "Black Friday
  checkout" and "botched schema migration" prompts.

### Known limitations

- Smaller open models (8B class) occasionally hallucinate field types
  (`integer` instead of `int`). The validation loop catches these; bigger
  cloud models nail it first try.
- Schema agent's cross-schema correlation support (`bound_to`, `pool`) is
  mentioned in the prompt but produces mixed results on small models. Reliable
  on Claude / GPT-4 / Gemini.

---

## [0.1.0] — 2026-05-16

Renamed and architecturally hardened from the upstream `mock-data-engine-api`
codebase. Single big commit covering the rebrand, structural cleanup, bug fixes
surfaced during the audit, a new demo playground, and a full benchmark report.

### Added

- **`havocforge` Python package** (was `mock_engine`). `Havocforge` and
  `HavocforgeError` API symbols (were `MockEngine` / `MockEngineError`).
- **`server/routers/streaming/` package**, decomposed from a 793-line god file
  into `handler.py`, `state.py`, `chaos_apply.py`, `live.py`, `profiler.py`.
  Router re-exported from `__init__.py` so the wiring in `server/app.py` is
  unchanged.
- **`init_publishers_from_config()` lifespan hook** so Kafka / Pub/Sub publishers
  are constructed eagerly on app startup instead of via a racy lazy global. They
  live on `app.state` and are reachable through FastAPI `Depends`.
- **`demo/`** — slim public-facing playground:
  - FastAPI service (`demo/app.py`) exposing `/`, `/api/schemas`, `/api/ops`,
    `/api/generate` with per-IP rate limiting and a `count<=50` cap
  - Single-page UI (`demo/static/{index.html,style.css,app.js}`) with the
    neumorphism palette ported from [archils.dev](https://archils.dev) (light
    default + dark toggle, DM Sans / Nunito fonts, burnt-orange accent)
  - `docker-compose.demo.yaml` and `scripts/demo-{up,down}.sh`
  - `demo/cloudflared/` scaffold (config template + 7-step Cloudflare Tunnel
    setup walkthrough) for going public at a custom URL
- **`docs/performance.md`** — full 30-cell single-instance benchmark matrix:
  worker scaling × batch size, chaos/metrics feature cost, concurrency sweep,
  WebSocket sustained throughput, schema-complexity comparison, pre-generation
  worker fill rate. Includes methodology + reproduction commands.
- **`tests/perf/bench.py`** — single-config bench (REST burst + sweep + WS).
- **`tests/perf/bench_matrix.py`** — full matrix orchestrator: reconfigures the
  api container between rows (workers/cpus, chaos via hot-reload, metrics via
  recreate), runs all benches, saves incrementally so a mid-matrix failure
  preserves partial data.
- **`docker-compose.bench.yaml`** — compose override pinning the api container
  to `cpus: N` + `mem_limit: N×2g` + `WORKERS=N` so the perf numbers are
  honest single-instance baselines.

### Fixed

- **Sync Redis blocking the event loop.** REST and preview generation endpoints
  now wrap synchronous `gen.generate()` calls in `asyncio.to_thread()`.
  Previously the sync Redis correlation lookups inside
  `ObjectGenerator._generate_impl()` could freeze the event loop for hundreds
  of milliseconds per request, blocking unrelated traffic.
- **WebSocket dropped the last 4–9 events on `max_events`.** Added a 50 ms
  drain before `websocket.close()` in the `finally` block — without it the
  close frame interrupted in-flight `send_text` calls. Verified: `max_events=N`
  now reliably delivers exactly N events.
- **Four chaos ops were defined but never registered.** `auth_fault`,
  `header_anomaly`, `random_header_case` were missing the
  `@Registry.register(BaseChaosOp)` decorator; `burst` was decorated but
  unreachable because `havocforge/chaos/ops/network/__init__.py` didn't exist
  so `pkgutil.walk_packages` couldn't auto-discover it. Decorators added,
  package init created. All 19 chaos ops now appear in the registry and fire
  end-to-end via curl.
- **`time_skew`, `schema_time_skew`, `late_arrival` only fired through the
  preview endpoint.** `_patch_mgr_for_body_ops` (auto-detects datetime fields
  + seeds the temporal tracker) was preview-only. Refactored to accept a
  `schema_name` argument and now called from the regular
  `/v1/schemas/{name}/generate` route too.
- **`GET /v1/admin/chaos/test` returned 500 on every call.** Endpoint was
  calling `ChaosManager.apply()` with stale keyword arguments (`response=`,
  `meta_enabled=`, `names=`) that the manager no longer accepts. Updated to
  the current signature (`body=`, `schema_name=`, `forced_activation=`).
- **Docker compose port mapping broken when `PORT != 8000`.** Old form passed
  `--port ${PORT:-8000}` to uvicorn while mapping `${PORT:-8000}:8000` —
  uvicorn listened on the host-side port, the container-side mapping pointed
  to 8000 with nothing there. Uvicorn now binds the container port
  unconditionally; the env var only shifts the host-side port.
- **Two dangerous silent excepts** narrowed to expected error types with
  `logger.exception(...)` for full tracebacks: the correlation lookup in
  `havocforge/generators/composites/object.py` (narrowed to
  `RedisError | json.JSONDecodeError | ValueError`) and
  `_discover_stateful_fields()` in `havocforge/pregeneration/worker.py`
  (schema-missing is a warning, anything else logs the exception).

### Changed

- Docker network: `mock-engine` → `havocforge`.
- Container names: `mock-engine-*` → `havocforge-*`.
- PostgreSQL default DB / user: `mock_engine` / `mock_user` →
  `havocforge` / `havocforge`.
- Grafana dashboards renamed + provisioning entry updated.
- README rewritten around the chaos-engineering value proposition: H1 with
  category + framework, 7 tech-stack badges, use-cases section, vs-alternatives
  table (Faker / Mockaroo / polyfactory / Mostly AI), ASCII architecture
  diagram, categorised chaos-op table, "Performance" highlights linking out
  to the full matrix. Down from sales copy to engineer-to-engineer prose.
- `pytest.ini`: added `testpaths = tests` + `norecursedirs = _old_for_deletion
  .venv .git ...` so quarantined files don't break test collection.
- `.gitignore`: excludes `_old_for_deletion/` (rebrand quarantine) and
  `_GITHUB_SETTINGS.md` (personal notes about repo Topics / About).

### Removed

- **Dead `mock_engine/chaos/registry.py`** (87-line singleton, zero imports —
  fully superseded by the unified registry in `havocforge/registry.py`).
- **Module-level publisher globals** (`_kafka_publisher` / `_pubsub_publisher`)
  from `server/routers/publish.py`. Eliminated the lazy-init race window.
- **Six stale files** surfaced by the rebrand audit (≈ 350 lines of unreferenced
  code), all moved to `_old_for_deletion/stale_from_rebrand_audit/` for manual
  review before final deletion:
  - `server/middleware/chaos_response.py` (empty file)
  - `server/middleware/meta.py` (1-line placeholder)
  - `server/middleware/route_pipeline.py` (1-line placeholder)
  - `server/models.py` (86 lines, zero inbound imports — `admin_generators.py`
    defines its own `GenerateRequest` locally)
  - `havocforge/pregeneration/temporal_gen.py` (76-line `TemporalGenerator`
    class with zero references; superseded by `havocforge/generators/stateful/`)
  - `tests/test_generators.py` (near-duplicate of `tests/ci/test_generators.py`,
    3-line trivial diff)

### Known limitations

- `havocforge/generators/composites/object.py` and `havocforge/context.py` are
  large. Splitting them is on a separate scoped branch — the cross-schema
  correlation pass has a subtle ordering invariant that's easy to break.
- ~190 broad `except Exception` blocks remain in the codebase. The two most
  dangerous (silent correlation failures and silent stateful-field discovery)
  have been narrowed; the rest are mostly graceful degradation around
  best-effort writes.
- `containers/grafana/dashboards/` JSON files have been renamed at the
  filesystem level but internal panel titles may still show old wording.
  Cosmetic only — dashboards render correctly.

### Verified

- Full pytest suite collects cleanly (50 unit + ~115 deselected integration).
- All 49 HTTP endpoints exercised end-to-end via curl sweep (response status,
  body, headers).
- All 19 chaos ops fire and produce the documented behaviour
  (body mutation / status override / latency injection / header anomaly).
- Full performance matrix run on AMD Ryzen 7 5800X, single-instance, with the
  numbers checked into `docs/performance.md`.
