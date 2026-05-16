from __future__ import annotations

from typing import Any, Dict



def test_stateful_timestamp_generator(
    count: int = 10, seed: int | None = None
) -> tuple[bool, Dict[str, Any]]:
    """Test stateful timestamp generator (sequential increments).

    Returns:
        Tuple of (passed: bool, data: dict)
    """
    try:
        # Create a schema with stateful timestamp
        schema_yaml = """
        type: object
        fields:
        ts:
            type: stateful_timestamp
            increment: 1000000
        """
        from havocforge import api as engine_api
        from havocforge.context import GenContext
        from havocforge.schema.builder import build_schema
        from havocforge.schema.registry import SchemaRegistry

        schema_name = "stateful_timestamp_test"
        doc = build_schema(
            schema_name, schema_yaml, source_path="stateful_timestamp_test.yaml"
        )
        SchemaRegistry.register(schema_name, doc)
        gen = engine_api.build(doc.contracts_by_path)
        ctx = GenContext(seed=seed)

        results = [gen.generate(ctx) for _ in range(count)]

        if not results:
            return False, {"error": "No results generated"}

        timestamps = [r.get("ts") for r in results]
        all_timestamps = all(
            isinstance(ts, (int, float)) for ts in timestamps if ts is not None
        )

        increasing = True
        for i in range(1, len(timestamps)):
            if timestamps[i] is not None and timestamps[i - 1] is not None:
                if timestamps[i] <= timestamps[i - 1]:
                    increasing = False
                    break

        passed = all_timestamps and increasing
        data = {
            "count": len(results),
            "all_timestamps": all_timestamps,
            "increasing": increasing,
            "sample_values": timestamps[:3] if timestamps else [],
        }

        return passed, data
    except Exception as e:
        return False, {"error": str(e)}
