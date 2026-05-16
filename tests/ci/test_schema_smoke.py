from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from havocforge import api as engine_api
from havocforge.context import GenContext
from havocforge.errors import PoolEmptyError
from havocforge.schema.builder import build_schema
from havocforge.schema.registry import SchemaRegistry


SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas"


def _list_schema_names() -> list[str]:
    return sorted(p.stem for p in SCHEMAS_DIR.glob("*.yaml"))


@pytest.fixture(autouse=True)
def reset_registry():
    SchemaRegistry._store.clear()
    SchemaRegistry._latest.clear()
    yield
    SchemaRegistry._store.clear()
    SchemaRegistry._latest.clear()


@pytest.mark.parametrize("schema_name", _list_schema_names())
def test_schema_smoke_builds_and_generates(schema_name: str):
    payload = yaml.safe_load(
        (SCHEMAS_DIR / f"{schema_name}.yaml").read_text(encoding="utf-8")
    )
    doc = build_schema(schema_name, payload)
    SchemaRegistry.register(schema_name, doc)

    gen = engine_api.build(doc.contracts_by_path)
    ctx = GenContext(seed=123)
    ctx.schema_name = schema_name

    try:
        item = gen.generate(ctx)
    except PoolEmptyError:
        pytest.skip(f"schema '{schema_name}' requires a populated pool (Redis not available in unit tests)")
    assert isinstance(item, dict)
    assert item
