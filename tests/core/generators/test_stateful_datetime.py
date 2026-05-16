from __future__ import annotations

from typing import Any, Dict



def test_stateful_datetime_generator(
    count: int = 10, seed: int | None = None
) -> tuple[bool, Dict[str, Any]]:
    """Test stateful datetime generator (sequential increments).

    Returns:
        Tuple of (passed: bool, data: dict)
    """
    try:
        schema_yaml = """
        type: object
        fields:
        dt:
            type: stateful_datetime
            increment: 1000000
            format: "%Y-%m-%dT%H:%M:%S"
        """
        from havocforge import api as engine_api
        from havocforge.context import GenContext
        from havocforge.schema.builder import build_schema
        from havocforge.schema.registry import SchemaRegistry

        schema_name = "stateful_datetime_test"
        doc = build_schema(
            schema_name, schema_yaml, source_path="stateful_datetime_test.yaml"
        )
        SchemaRegistry.register(schema_name, doc)
        gen = engine_api.build(doc.contracts_by_path)
        ctx = GenContext(seed=seed)

        results = [gen.generate(ctx) for _ in range(count)]

        if not results:
            return False, {"error": "No results generated"}

        datetimes = [r.get("dt") for r in results]
        all_strings = all(isinstance(dt, str) for dt in datetimes if dt is not None)

        format_ok = all("T" in dt and ":" in dt for dt in datetimes if dt is not None)

        passed = all_strings and format_ok
        data = {
            "count": len(results),
            "all_strings": all_strings,
            "format_ok": format_ok,
            "sample_values": datetimes[:3] if datetimes else [],
        }

        return passed, data
    except Exception as e:
        return False, {"error": str(e)}
