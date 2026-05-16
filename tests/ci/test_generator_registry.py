from __future__ import annotations

from pathlib import Path

from havocforge.registry import Registry
from havocforge.generators.base import BaseGenerator


TESTS_DIR = Path(__file__).resolve().parents[2] / "tests" / "core" / "generators"


def test_registered_generators_have_tests():
    registered = set(Registry.get_all(BaseGenerator).keys())

    file_stems = {p.stem.replace("test_", "") for p in TESTS_DIR.glob("test_*.py")}
    alias_map = {
        "str": "string",
        "list": "array",
        "timestamp_stateful": "stateful_timestamp",
        "ts_stateful": "stateful_timestamp",
        "datetime_stateful": "stateful_datetime",
        "dt_stateful": "stateful_datetime",
    }

    missing = []
    for key in registered:
        canonical = alias_map.get(key, key)
        if canonical not in file_stems:
            missing.append(key)

    assert not missing, f"Missing generator tests for: {', '.join(sorted(missing))}"
