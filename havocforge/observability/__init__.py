from __future__ import annotations

import os

from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry
from prometheus_client import make_asgi_app, multiprocess

registry = CollectorRegistry()
if os.getenv("PROMETHEUS_MULTIPROC_DIR"):
    multiprocess.MultiProcessCollector(registry)


http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "schema", "status_code"],
    registry=registry,
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint", "schema"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=registry,
)

http_request_size_bytes = Histogram(
    "http_request_size_bytes",
    "HTTP request payload size",
    ["method", "endpoint"],
    buckets=[100, 1000, 10000, 100000, 1000000],
    registry=registry,
)

http_response_size_bytes = Histogram(
    "http_response_size_bytes",
    "HTTP response payload size",
    ["endpoint", "schema"],
    buckets=[1000, 10000, 100000, 1000000, 10000000, 100000000],
    registry=registry,
)

generation_duration_seconds = Histogram(
    "generation_duration_seconds",
    "Data generation duration",
    ["schema", "count_bucket"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
    registry=registry,
)

items_generated_total = Counter(
    "items_generated_total",
    "Total items generated",
    ["schema", "source"],
    registry=registry,
)

seed_source_total = Counter(
    "seed_source_total", "Seed source distribution", ["source"], registry=registry
)

generator_invocations_total = Counter(
    "generator_invocations_total",
    "Generator invocations by type",
    ["generator", "schema"],
    registry=registry,
)

generator_duration_seconds = Histogram(
    "generator_duration_seconds",
    "Individual generator execution time",
    ["generator", "schema"],
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5],
    registry=registry,
)

chaos_op_executions_total = Counter(
    "chaos_op_executions_total",
    "Chaos operation executions",
    ["op", "schema", "applied"],
    registry=registry,
)

chaos_items_affected_total = Counter(
    "chaos_items_affected_total",
    "Items affected by chaos ops",
    ["op", "schema"],
    registry=registry,
)

chaos_op_duration_seconds = Histogram(
    "chaos_op_duration_seconds",
    "Chaos operation duration",
    ["op", "schema"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
    registry=registry,
)

temporal_tracker_elapsed_seconds = Gauge(
    "temporal_tracker_elapsed_seconds",
    "Elapsed time since first timestamp",
    ["schema"],
    registry=registry,
)

temporal_tracker_current_timestamp = Gauge(
    "temporal_tracker_current_timestamp",
    "Current timestamp (epoch microseconds)",
    ["schema"],
    registry=registry,
)

temporal_tracker_resets_total = Counter(
    "temporal_tracker_resets_total", "Timeline resets", ["schema"], registry=registry
)

persistence_writes_total = Counter(
    "persistence_writes_total",
    "Total datasets persisted",
    ["schema", "status"],
    registry=registry,
)

persistence_reads_total = Counter(
    "persistence_reads_total",
    "Total dataset retrievals",
    ["schema", "source"],
    registry=registry,
)

persistence_cache_hits_total = Counter(
    "persistence_cache_hits_total", "Redis cache hits", ["schema"], registry=registry
)

persistence_cache_misses_total = Counter(
    "persistence_cache_misses_total",
    "Redis cache misses (PostgreSQL fallback)",
    ["schema"],
    registry=registry,
)

persistence_errors_total = Counter(
    "persistence_errors_total",
    "Persistence operation errors",
    ["operation", "error_type"],
    registry=registry,
)

persistence_sync_lag_seconds = Histogram(
    "persistence_sync_lag_seconds",
    "Time lag between Redis write and PostgreSQL sync",
    ["schema"],
    buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0],
    registry=registry,
)

persistence_dataset_size_bytes = Histogram(
    "persistence_dataset_size_bytes",
    "Size of persisted datasets",
    ["schema"],
    buckets=[1000, 10000, 100000, 1000000, 10000000],
    registry=registry,
)

persistence_redis_writes_total = Counter(
    "persistence_redis_writes_total",
    "Total writes to Redis cache",
    ["schema", "status"],
    registry=registry,
)

persistence_postgres_writes_total = Counter(
    "persistence_postgres_writes_total",
    "Total writes to PostgreSQL",
    ["schema", "status"],
    registry=registry,
)

persistence_redis_cache_size_mb = Gauge(
    "persistence_redis_cache_size_mb",
    "Total Redis cache size by schema (MB)",
    ["schema"],
    registry=registry,
)

persistence_postgres_cache_size_mb = Gauge(
    "persistence_postgres_cache_size_mb",
    "Total PostgreSQL storage size by schema (MB)",
    ["schema"],
    registry=registry,
)

persistence_batch_sync_datasets_synced = Counter(
    "persistence_batch_sync_datasets_synced",
    "Total datasets synced by batch sync job",
    registry=registry,
)

persistence_batch_sync_bytes_synced = Counter(
    "persistence_batch_sync_bytes_synced",
    "Total bytes synced by batch sync job",
    registry=registry,
)

persistence_batch_sync_last_run_timestamp = Gauge(
    "persistence_batch_sync_last_run_timestamp",
    "Timestamp of last batch sync run (epoch seconds)",
    registry=registry,
)

websocket_connections_total = Counter(
    "websocket_connections_total",
    "Total WebSocket connections",
    ["schema", "status"],
    registry=registry,
)

websocket_stream_duration_seconds = Histogram(
    "websocket_stream_duration_seconds",
    "WebSocket stream duration",
    ["schema"],
    buckets=[0.01, 0.1, 1.0, 10.0, 60.0, 300.0, 600.0, 1800.0, 3600.0],
    registry=registry,
)

websocket_bytes_sent_total = Counter(
    "websocket_bytes_sent_total",
    "Total bytes sent over WebSocket",
    ["schema"],
    registry=registry,
)

websocket_events_streamed_total = Counter(
    "websocket_events_streamed_total",
    "Total events streamed over WebSocket",
    ["schema"],
    registry=registry,
)

websocket_active_connections = Gauge(
    "websocket_active_connections",
    "Current active WebSocket connections",
    ["schema"],
    registry=registry,
)

pregen_queue_size = Gauge(
    "pregen_queue_size",
    "Pre-generation queue size by schema",
    ["schema"],
    registry=registry,
)

pregen_generation_rate = Gauge(
    "pregen_generation_rate",
    "Pre-generation items per second by schema",
    ["schema"],
    registry=registry,
)

chaos_active_operations = Gauge(
    "chaos_active_operations",
    "Currently active chaos operations",
    ["op", "schema"],
    registry=registry,
)

config_enabled = Gauge(
    "config_enabled",
    "Configuration flags (1=enabled, 0=disabled)",
    ["config_key"],
    registry=registry,
)


def get_count_bucket(count: int) -> str:
    """Bucket count into ranges for labels."""
    if count <= 10:
        return "1-10"
    elif count <= 100:
        return "11-100"
    elif count <= 1000:
        return "101-1000"
    elif count <= 10000:
        return "1001-10000"
    else:
        return "10000+"


def get_metrics_app():
    """Get ASGI app for /metrics endpoint."""
    return make_asgi_app(registry=registry)
