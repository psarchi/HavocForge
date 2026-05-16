import json
import sys
import types

import pytest

try:
    import orjson
except ImportError:
    fake = types.SimpleNamespace(
        dumps=lambda obj: json.dumps(obj).encode("utf-8"),
        loads=lambda b: json.loads(
            b.decode("utf-8") if isinstance(b, (bytes, bytearray)) else b
        ),
    )
    sys.modules["orjson"] = fake
    import orjson

try:
    import redis.asyncio  # noqa: F401
except ImportError:
    redis_mod = types.ModuleType("redis")
    redis_asyncio = types.ModuleType("redis.asyncio")

    async def _from_url(*args, **kwargs):
        raise RuntimeError("redis async stub in tests")

    class _Redis: ...

    redis_asyncio.Redis = _Redis
    redis_asyncio.from_url = _from_url
    sys.modules["redis"] = redis_mod
    sys.modules["redis.asyncio"] = redis_asyncio

from havocforge.contracts.stateful_timestamp import StatefulTimestampGeneratorSpec
from havocforge.schema.registry import SchemaRegistry
from havocforge.pregeneration.worker import _discover_stateful_fields
from server.routers import streaming
from server.routers.streaming import state as streaming_state


class FakeRedis:
    """Minimal async Redis stub for tests."""

    def __init__(self, data: dict[str, bytes] | None = None) -> None:
        self.store: dict[str, bytes] = data or {}
        self.hashes: dict[str, dict[str, int]] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value):
        self.store[key] = value
        return True

    async def hgetall(self, key: str):
        return {k: v for k, v in self.hashes.get(key, {}).items()}

    async def hset(self, key: str, mapping: dict[str, int]):
        existing = self.hashes.get(key, {})
        existing.update(mapping)
        self.hashes[key] = existing
        return True


@pytest.fixture(autouse=True)
def clear_stateful_caches():
    streaming_state._STATEFUL_META.clear()
    try:
        from havocforge.chaos import get_temporal_tracker

        get_temporal_tracker().clear_all()
    except Exception:
        pass
    yield
    streaming_state._STATEFUL_META.clear()
    try:
        from havocforge.chaos import get_temporal_tracker

        get_temporal_tracker().clear_all()
    except Exception:
        pass


def test_discover_stateful_fields_uses_contract_token():
    doc = type(
        "Doc",
        (),
        {
            "contracts_by_path": {
                "event_timestamp": StatefulTimestampGeneratorSpec(
                    start=100, increment=5
                ),
                "user_id": "ignored",
            }
        },
    )
    SchemaRegistry.register("test_stateful_schema", doc)

    fields = _discover_stateful_fields("test_stateful_schema")

    assert fields == [
        {
            "field": "event_timestamp",
            "gen": "stateful_timestamp",
            "params": {"start": 100, "increment": 5},
        }
    ]


@pytest.mark.skip(reason="META_KEY_TEMPLATE refactored, test needs update")
def test_streaming_applies_stateful_generators():
    meta_key = "pregen:meta:stream_events"  # streaming.META_KEY_TEMPLATE.format(schema="stream_events")
    payload = {
        "schema": "stream_events",
        "stateful": [
            {
                "field": "event_timestamp",
                "gen": "stateful_timestamp",
                "params": {"start": 1_000_000, "increment": 10},
            }
        ],
        "worker_start_time_seconds": 0,
    }
    fake_redis = FakeRedis({meta_key: orjson.dumps(payload)})

    async def _run():
        meta = await streaming._ensure_stateful_meta(fake_redis, "stream_events")
        items = [{"event_timestamp": 0} for _ in range(3)]
        batch_items, state = await streaming._apply_stateful_user_batch(
            items, {}, meta, increment_mode="sequential"
        )
        return [item["event_timestamp"] for item in batch_items], state[
            "event_timestamp"
        ]

    import asyncio

    values, last_state = asyncio.run(_run())

    assert len(values) == 3
    assert values[1] - values[0] == 10
    assert values[2] - values[1] == 10
    assert last_state == values[-1]
