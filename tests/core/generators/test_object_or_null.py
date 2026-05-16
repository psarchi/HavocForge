from __future__ import annotations

from typing import Any, Dict



def test_object_or_null_generator(
    count: int = 100, seed: int | None = None
) -> tuple[bool, Dict[str, Any]]:
    """Test object_or_null generator with null probability.

    Returns:
        Tuple of (passed: bool, data: dict)
    """
    try:
        from havocforge import api as engine_api
        from havocforge.context import GenContext

        spec = {
            "type": "object",
            "fields": {
                "always_null": {
                    "type": "object_or_null",
                    "p_null": 1.0,
                    "of": {
                        "type": "object",
                        "fields": {"id": {"type": "int", "min": 1, "max": 1}},
                    },
                },
                "always_obj": {
                    "type": "object_or_null",
                    "p_null": 0.0,
                    "of": {
                        "type": "object",
                        "fields": {"id": {"type": "int", "min": 1, "max": 1}},
                    },
                },
            },
        }
        gen = engine_api.build_generator(spec)
        ctx = GenContext(seed=seed)
        results = [gen.generate(ctx) for _ in range(count)]

        if not results:
            return False, {"error": "No results generated"}

        always_null_values = [r["always_null"] for r in results]
        always_obj_values = [r["always_obj"] for r in results]

        all_null = all(v is None for v in always_null_values)

        all_obj = all(isinstance(v, dict) for v in always_obj_values)

        passed = all_null and all_obj
        data = {
            "count": len(results),
            "all_null": all_null,
            "all_obj": all_obj,
            "always_null_count": sum(1 for v in always_null_values if v is None),
            "always_obj_count": sum(
                1 for v in always_obj_values if isinstance(v, dict)
            ),
        }

        return passed, data
    except Exception as e:
        return False, {"error": str(e)}
