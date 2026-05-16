from __future__ import annotations

import pytest
from pathlib import Path
import yaml

from havocforge.registry import Registry
from havocforge.generators.base import BaseGenerator
from havocforge.chaos.ops.base import BaseChaosOp
from havocforge.config import get_config_manager


@pytest.mark.ci
def test_all_schemas_parse():
    """Verify all schema YAML files parse correctly."""
    schemas_dir = Path("schemas")
    schema_files = list(schemas_dir.glob("*.yaml")) + list(schemas_dir.glob("*.yml"))

    assert len(schema_files) > 0, "No schema files found"

    errors = []
    for schema_file in schema_files:
        try:
            with open(schema_file) as f:
                data = yaml.safe_load(f)
                assert data is not None
                assert "type" in data, f"{schema_file.name} missing 'type' field"
        except Exception as e:
            errors.append(f"{schema_file.name}: {e}")

    assert not errors, f"{len(errors)} schema(s) failed:\n" + "\n".join(errors)


@pytest.mark.ci
def test_smoke_schema_structure():
    """Verify smoke.yaml has expected structure."""
    with open("schemas/smoke.yaml") as f:
        schema = yaml.safe_load(f)

    assert schema["type"] == "object"
    assert "fields" in schema
    assert "int_field" in schema["fields"]
    assert "bool_field" in schema["fields"]


@pytest.mark.ci
def test_config_files_parse():
    """Verify config files parse correctly."""
    config_dir = Path("config/default")

    if not config_dir.exists():
        pytest.skip("Config directory not found")

    config_files = list(config_dir.glob("*.yaml")) + list(config_dir.glob("*.yml"))

    errors = []
    for config_file in config_files:
        try:
            with open(config_file) as f:
                data = yaml.safe_load(f)
                assert data is not None
        except Exception as e:
            errors.append(f"{config_file.name}: {e}")

    assert not errors, f"{len(errors)} config(s) failed:\n" + "\n".join(errors)


@pytest.mark.ci
def test_config_manager_works():
    """Test config manager initializes."""
    cm = get_config_manager()
    assert cm is not None


@pytest.mark.ci
def test_generator_registry_not_empty():
    """Verify generators are registered."""
    registry = Registry.get_all(BaseGenerator)
    assert len(registry) > 0, "No generators registered"
    print(f"Found {len(registry)} registered generators")


@pytest.mark.ci
def test_critical_generators_registered():
    """Verify critical generator types are registered."""
    registry = Registry.get_all(BaseGenerator)
    critical = ["int", "float", "string", "bool", "object", "array"]

    missing = [t for t in critical if t not in registry]
    assert not missing, f"Missing critical generators: {missing}"


@pytest.mark.ci
def test_chaos_registry_not_empty():
    """Verify chaos ops are registered (excluding drifts)."""
    registry = Registry.get_all(BaseChaosOp)

    ops = [k for k in registry.keys() if k not in {"data_drift", "schema_drift"}]

    assert len(ops) > 0, "No chaos ops registered"
    print(f"Found {len(ops)} registered chaos ops (excluding drifts)")


@pytest.mark.ci
def test_critical_chaos_ops_registered():
    """Verify critical chaos ops are registered."""
    registry = Registry.get_all(BaseChaosOp)
    critical = ["latency", "duplicate_items", "truncate"]

    missing = [op for op in critical if op not in registry]
    assert not missing, f"Missing critical chaos ops: {missing}"


@pytest.mark.ci
def test_registered_chaos_ops_instantiate():
    """Test registered chaos ops can be instantiated."""
    registry = Registry.get_all(BaseChaosOp)

    ops = {k: v for k, v in registry.items() if k not in {"data_drift", "schema_drift"}}

    errors = []
    for op_name, op_class in ops.items():
        try:
            instance = op_class(enabled=True)
            assert instance is not None
        except Exception as e:
            errors.append(f"{op_name}: {str(e)[:80]}")

    assert not errors, f"{len(errors)} chaos op(s) failed:\n" + "\n".join(errors[:10])
