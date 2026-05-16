from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any, Dict

from havocforge import api as engine_api
from havocforge.context import GenContext
from havocforge.schema.builder import build_schema
from havocforge.schema.registry import SchemaRegistry


SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


def load_schema(schema_name: str) -> Dict[str, Any]:
    """Load a schema YAML file from tests/schemas/."""
    schema_path = SCHEMAS_DIR / f"{schema_name}.yaml"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")

    with open(schema_path, "r") as f:
        return yaml.safe_load(f)


def build_generator_from_schema(
    schema_name: str, seed: int | None = None
) -> tuple[Any, GenContext]:
    """Build a generator from a schema file.

    Returns:
        Tuple of (generator, context)
    """
    schema_path = SCHEMAS_DIR / f"{schema_name}.yaml"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")

    unique_name = f"{schema_name}_test_{id(schema_name)}"
    doc = build_schema(
        unique_name, schema_path.read_text(), source_path=str(schema_path)
    )
    SchemaRegistry.register(unique_name, doc)

    gen = engine_api.build(doc.contracts_by_path)
    ctx = GenContext(seed=seed)

    return gen, ctx


def generate_from_schema(
    schema_name: str, count: int = 10, seed: int | None = None
) -> list[Dict[str, Any]]:
    """Generate data from a schema file.

    Returns:
        List of generated data dictionaries
    """
    gen, ctx = build_generator_from_schema(schema_name, seed=seed)
    return [gen.generate(ctx) for _ in range(count)]


def get_all_registered_generators() -> list[str]:
    """Get all registered generator keys."""
    from havocforge.registry import Registry
    from havocforge.generators.base import BaseGenerator

    all_gens = Registry.get_all(BaseGenerator)
    return sorted(all_gens.keys())
