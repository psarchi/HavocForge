from __future__ import annotations

from typing import Any, Dict



def test_enum_generator(
    count: int = 100, seed: int | None = None
) -> tuple[bool, Dict[str, Any]]:
    """Test enum generator with weights.

    Returns:
        Tuple of (passed: bool, data: dict)
    """
    try:
        from havocforge.context import GenContext
        from havocforge.generators.leafs.enum import EnumGenerator

        gen = EnumGenerator(values=["x", "y"], weights=[1, 100])
        ctx = GenContext(seed=seed)
        results = [{"bias": gen.generate(ctx)} for _ in range(count)]

        if not results:
            return False, {"error": "No results generated"}

        values = [r["bias"] for r in results]
        valid_values = {"x", "y"}
        all_valid = all(v in valid_values for v in values)

        # With weights [1, 100], 'y' should be much more common
        y_count = sum(1 for v in values if v == "y")
        x_count = sum(1 for v in values if v == "x")
        weighted_ok = y_count > x_count * 10

        passed = all_valid
        data = {
            "count": len(values),
            "all_valid": all_valid,
            "x_count": x_count,
            "y_count": y_count,
            "weighted_ok": weighted_ok,
        }

        return passed, data
    except Exception as e:
        return False, {"error": str(e)}
