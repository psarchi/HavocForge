from __future__ import annotations

from typing import Any, Dict



def test_string_or_null_generator(
    count: int = 100, seed: int | None = None
) -> tuple[bool, Dict[str, Any]]:
    """Test string_or_null generator.

    Returns:
        Tuple of (passed: bool, data: dict)
    """
    try:
        from havocforge import api as engine_api
        from havocforge.context import GenContext

        spec = {
            "type": "object",
            "fields": {
                "nullable_str": {
                    "type": "string_or_null",
                    "p_null": 0.5,
                    "of": {"type": "string", "template": "TEST-{nn}"},
                }
            },
        }
        gen = engine_api.build_generator(spec)
        ctx = GenContext(seed=seed)

        results = [gen.generate(ctx) for _ in range(count)]

        if not results:
            return False, {"error": "No results generated"}

        values = [r.get("nullable_str") for r in results]
        null_count = sum(1 for v in values if v is None)
        string_count = sum(1 for v in values if v is not None and isinstance(v, str))

        passed = null_count > 0 and string_count > 0
        data = {
            "count": len(results),
            "null_count": null_count,
            "string_count": string_count,
        }

        return passed, data
    except Exception as e:
        return False, {"error": str(e)}
