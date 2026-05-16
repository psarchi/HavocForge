from __future__ import annotations

from typing import Any, Dict



def test_select_generator(
    count: int = 100, seed: int | None = None
) -> tuple[bool, Dict[str, Any]]:
    """Test select generator with options.

    Returns:
        Tuple of (passed: bool, data: dict)
    """
    try:
        from havocforge import api as engine_api
        from havocforge.context import GenContext

        spec = {
            "type": "object",
            "fields": {
                "selection": {
                    "type": "select",
                    "options": {
                        "req": {
                            "of": {"type": "int", "min": 1, "max": 1},
                            "required": True,
                        },
                        "opt1": {"of": {"type": "int", "min": 2, "max": 2}},
                        "opt2": {"of": {"type": "int", "min": 3, "max": 3}},
                    },
                    "pick": {"mode": "exact", "min": 1},
                }
            },
        }
        gen = engine_api.build_generator(spec)
        ctx = GenContext(seed=seed)
        results = [gen.generate(ctx) for _ in range(count)]

        if not results:
            return False, {"error": "No results generated"}

        all_valid = True
        has_req = False

        for r in results:
            if "selection" not in r:
                all_valid = False
                continue

            sel = r["selection"]
            if not isinstance(sel, dict):
                all_valid = False
                continue

            if "req" in sel and sel["req"] == 1:
                has_req = True

            for key, value in sel.items():
                if key == "req" and value != 1:
                    all_valid = False
                elif key == "opt1" and value != 2:
                    all_valid = False
                elif key == "opt2" and value != 3:
                    all_valid = False

        passed = all_valid and has_req
        data = {
            "count": len(results),
            "all_valid": all_valid,
            "has_req": has_req,
        }

        return passed, data
    except Exception as e:
        return False, {"error": str(e)}
