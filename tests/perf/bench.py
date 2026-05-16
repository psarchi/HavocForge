"""Single-core full-deployment bench for Havocforge.

Three measurements:
  A) REST burst       — N concurrent requests, count=K each
  B) REST single big  — one request, count=K
  C) WebSocket stream — sustained throughput, max_events=M

API is constrained to 1 CPU + 1 uvicorn worker (docker-compose.bench.yaml).
Pregen worker pre-fills the Redis queue, so this measures hot-path throughput.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from typing import Any

import httpx
from websockets.asyncio.client import connect

BASE = "http://localhost:8100"
WS_BASE = "ws://localhost:8100"


def fmt_table(rows: list[dict[str, Any]]) -> str:
    """Format a list of dict rows as a markdown table."""
    if not rows:
        return ""
    keys = list(rows[0].keys())
    widths = [max(len(str(k)), max(len(str(r.get(k, ""))) for r in rows)) for k in keys]
    head = "| " + " | ".join(k.ljust(w) for k, w in zip(keys, widths)) + " |"
    sep = "| " + " | ".join("-" * w for w in widths) + " |"
    body = [
        "| " + " | ".join(str(r.get(k, "")).ljust(w) for k, w in zip(keys, widths)) + " |"
        for r in rows
    ]
    return "\n".join([head, sep, *body])


# ── A) REST burst ────────────────────────────────────────────────────────────


async def bench_rest_burst(schema: str, count: int, concurrency: int, total: int):
    """Fire `total` requests with up to `concurrency` in flight, count=K each."""
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    ok = 0
    errors = 0

    async with httpx.AsyncClient(timeout=30) as client:
        async def one():
            nonlocal ok, errors
            async with sem:
                t = time.perf_counter()
                try:
                    r = await client.get(
                        f"{BASE}/v1/schemas/{schema}/generate",
                        params={"count": count, "persist": "false"},
                    )
                    elapsed = time.perf_counter() - t
                    latencies.append(elapsed)
                    if r.status_code == 200:
                        ok += 1
                    else:
                        errors += 1
                except Exception:
                    errors += 1

        wall_t0 = time.perf_counter()
        await asyncio.gather(*[one() for _ in range(total)])
        wall = time.perf_counter() - wall_t0

    items_total = ok * count
    latencies_sorted = sorted(latencies)
    return {
        "schema": schema,
        "concurrency": concurrency,
        "requests": total,
        "count_per_req": count,
        "ok": ok,
        "errors": errors,
        "wall_s": round(wall, 3),
        "items_total": items_total,
        "items_per_sec": int(items_total / wall) if wall > 0 else 0,
        "req_per_sec": round(total / wall, 1) if wall > 0 else 0,
        "p50_ms": round(statistics.median(latencies) * 1000, 1) if latencies else 0,
        "p95_ms": round(latencies_sorted[int(len(latencies_sorted) * 0.95)] * 1000, 1) if latencies else 0,
        "p99_ms": round(latencies_sorted[int(len(latencies_sorted) * 0.99)] * 1000, 1) if latencies else 0,
    }


# ── B) REST single big request ───────────────────────────────────────────────


async def bench_rest_single_big(schema: str, count: int):
    async with httpx.AsyncClient(timeout=60) as client:
        t = time.perf_counter()
        r = await client.get(
            f"{BASE}/v1/schemas/{schema}/generate",
            params={"count": count, "persist": "false"},
        )
        elapsed = time.perf_counter() - t
        items = len(r.json().get("items", [])) if r.status_code == 200 else 0
        return {
            "schema": schema,
            "count": count,
            "status": r.status_code,
            "items_received": items,
            "wall_s": round(elapsed, 3),
            "items_per_sec": int(items / elapsed) if elapsed > 0 else 0,
        }


# ── C) WebSocket stream ──────────────────────────────────────────────────────


async def bench_ws_stream(schema: str, max_events: int, count_per_pop: int):
    uri = f"{WS_BASE}/v1/schemas/{schema}/stream?max_events={max_events}&count={count_per_pop}"
    received = 0
    t0 = time.perf_counter()
    first_event_t = None
    try:
        async with connect(uri, max_size=2**26) as ws:
            while True:
                try:
                    m = await asyncio.wait_for(ws.recv(), timeout=10)
                except asyncio.TimeoutError:
                    break
                msg = json.loads(m)
                t = msg.get("type")
                if t == "event":
                    if first_event_t is None:
                        first_event_t = time.perf_counter()
                    received += 1
                elif t == "error":
                    break
    except Exception:
        pass
    wall = time.perf_counter() - t0
    sustained = (received / (time.perf_counter() - first_event_t)) if first_event_t else 0
    return {
        "schema": schema,
        "max_events": max_events,
        "received": received,
        "wall_s": round(wall, 3),
        "items_per_sec_total": int(received / wall) if wall > 0 else 0,
        "items_per_sec_after_first": int(sustained),
    }


# ── Driver ───────────────────────────────────────────────────────────────────


async def main():
    print("→ warming up (5 requests, ignored)")
    async with httpx.AsyncClient(timeout=10) as client:
        await asyncio.gather(*[
            client.get(f"{BASE}/v1/schemas/smoke/generate", params={"count": 10, "persist": "false"})
            for _ in range(5)
        ])

    print()
    print("──────────────────────────────────────────────────────────────────────")
    print("A) REST burst — smoke schema, count=10/req, 50 concurrent, 500 total")
    print("──────────────────────────────────────────────────────────────────────")
    a1 = await bench_rest_burst("smoke", count=10, concurrency=50, total=500)
    print(fmt_table([a1]))

    print()
    print("──────────────────────────────────────────────────────────────────────")
    print("A2) REST burst — ga4 schema (heavier), count=10/req, 50 concurrent, 500 total")
    print("──────────────────────────────────────────────────────────────────────")
    a2 = await bench_rest_burst("ga4", count=10, concurrency=50, total=500)
    print(fmt_table([a2]))

    print()
    print("──────────────────────────────────────────────────────────────────────")
    print("A3) REST burst — concurrency sweep, smoke, count=10/req, 200 total")
    print("──────────────────────────────────────────────────────────────────────")
    sweeps = []
    for c in (1, 5, 10, 25, 50, 100):
        r = await bench_rest_burst("smoke", count=10, concurrency=c, total=200)
        sweeps.append({
            "concurrency": c, "items/sec": r["items_per_sec"],
            "req/sec": r["req_per_sec"], "p50_ms": r["p50_ms"],
            "p95_ms": r["p95_ms"], "p99_ms": r["p99_ms"],
        })
    print(fmt_table(sweeps))

    print()
    print("──────────────────────────────────────────────────────────────────────")
    print("B) REST single big request — count=1000")
    print("──────────────────────────────────────────────────────────────────────")
    b1 = await bench_rest_single_big("smoke", count=1000)
    b2 = await bench_rest_single_big("ga4", count=1000)
    print(fmt_table([b1, b2]))

    print()
    print("──────────────────────────────────────────────────────────────────────")
    print("C) WebSocket stream — max_events=20000, count=500/pop")
    print("──────────────────────────────────────────────────────────────────────")
    c1 = await bench_ws_stream("smoke", max_events=20000, count_per_pop=500)
    c2 = await bench_ws_stream("ga4", max_events=20000, count_per_pop=500)
    print(fmt_table([c1, c2]))

    print()
    print("──────────────────────────────────────────────────────────────────────")
    print("DONE")


asyncio.run(main())
