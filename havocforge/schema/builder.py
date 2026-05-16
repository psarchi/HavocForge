from __future__ import annotations
from typing import Any, Dict, List, Tuple

import time
import yaml

from havocforge.context import GenContext
from havocforge.schema.validator import Validator
from havocforge.schema.errors import SchemaPreflightError, SchemaValidationError
from havocforge.errors import PoolEmptyError
from havocforge.schema.models import SchemaDoc, PreflightReport, PreflightFailure
from havocforge import api as engine_api
from havocforge.contracts import (
    ArrayGeneratorSpec,
    OneOfGeneratorSpec,
    ObjectGeneratorSpec,
    MaybeGeneratorSpec,
)


def _flatten(node: Any, prefix: str = "") -> Dict[str, Any]:
    """Flatten a contract tree into a dot-path map.

    Objects, arrays, one-ofs, and maybes are expanded into dot/marker
    notation so downstream consumers can address nodes directly.

    Args:
        node (Any): Contract node to flatten.
        prefix (str): Accumulated path to prepend.

    Returns:
        dict[str, Any]: Mapping of flattened paths to contract nodes.
    """
    out: Dict[str, Any] = {}
    if isinstance(node, ObjectGeneratorSpec):
        if prefix:
            out[prefix] = node
        for k, v in (node.fields or {}).items():
            child_prefix = f"{prefix}.{k}" if prefix else k
            out.update(_flatten(v, child_prefix))
        return out

    if isinstance(node, ArrayGeneratorSpec):
        if prefix:
            out[prefix] = node  # array node
        else:
            out[""] = node  # degenerate case
        if node.child is not None:
            out[f"{prefix}[]"] = node.child
            out.update(_flatten(node.child, f"{prefix}[]"))
        return out

    if isinstance(node, OneOfGeneratorSpec):
        out[prefix] = node
        for i, choice in enumerate(node.choices or []):
            out.update(_flatten(choice, f"{prefix}|{i}"))
        return out

    if isinstance(node, MaybeGeneratorSpec):
        out[prefix] = node
        if node.child is not None:
            out.update(_flatten(node.child, f"{prefix}.?"))
        return out

    # leaf or unknown: record as-is
    out[prefix] = node
    return out


def _get_by_path(value: Any, path: str) -> Any:
    """Resolve a flattened schema path against a generated payload.

    Args:
        value (Any): Payload produced by a generator.
        path (str): Flattened path (``items[]``, ``foo.bar``).

    Returns:
        Any: Value located at ``path`` or ``None`` if traversal fails.
    """
    if path == "" or value is None:
        return value
    parts = [p for p in path.split(".") if p]
    cur = value
    for part in parts:
        clean = part.replace("[]", "").split("|")[0].replace("?", "")
        if not isinstance(cur, dict):
            return None
        cur = cur.get(clean)
    return cur


def _synthesize_root_spec(contracts_by_path: Dict[str, Any]) -> Dict[str, Any]:
    """Build the canonical root object spec from flattened contracts.

    Args:
        contracts_by_path (dict[str, Any]): Flattened contract map.

    Returns:
        dict[str, Any]: Object specification ready for `engine_api.build`.
    """
    fields: Dict[str, Any] = {}
    for path, contract in contracts_by_path.items():
        if "." in path or "[]" in path or "|" in path or path == "":
            continue
        fields[path] = engine_api._contract_to_spec(path, contract)
    if not fields:
        # Fallback
        for path, contract in contracts_by_path.items():
            if "|" in path:
                continue
            key = path[:-2] if path.endswith("[]") else path.split(".")[-1]
            fields[key] = engine_api._contract_to_spec(path, contract)
    return {"type": "object", "fields": fields}


def _preflight_sample(
    name: str,
    contracts_by_path: Dict[str, Any],
    samples: int = 3,
) -> Tuple[PreflightReport, Any]:
    """Generate deterministic samples to surface schema issues early.

    Args:
        name (str): Schema identifier (used in error reporting).
        contracts_by_path (dict[str, Any]): Flattened contracts map.
        samples (int): Number of deterministic seeds to test.

    Returns:
        tuple[PreflightReport, Any]: Report summary and the built generator.

    Raises:
        RuntimeError: When generation fails across the attempted seeds.
    """
    seeds = [101, 202, 303][: max(1, samples)]
    report = PreflightReport(
        seeds=seeds, samples=0, failures=[], arrays_materialized=0, union_choices_hit={}
    )
    # Build engine generator
    gen = engine_api.build(contracts_by_path)
    start = time.perf_counter()
    array_requirements: List[Tuple[str, int]] = []
    for path, spec in contracts_by_path.items():
        if isinstance(spec, ArrayGeneratorSpec):
            if spec.min_items is not None and int(spec.min_items) > 0:
                array_requirements.append((path, int(spec.min_items)))
    try:
        for seed in seeds:
            ctx = GenContext(seed=seed)
            ctx.schema_name = name
            row = gen.generate(ctx)
            report.samples += 1
            for path, min_needed in array_requirements:
                arr = _get_by_path(row, path)
                if isinstance(arr, list) and len(arr) >= min_needed:
                    report.arrays_materialized += 1
    except PoolEmptyError:
        # Schema has depends_on_pool fields — pool not populated at load time, that's fine.
        pass
    except Exception as e:
        report.failures.append(PreflightFailure(path="<root>", error=str(e)))
        raise
    finally:
        _ = (time.perf_counter() - start) * 1000.0
    if report.failures:
        raise SchemaPreflightError(f"preflight failed: {report.failures[0].error}")
    if array_requirements and report.arrays_materialized == 0:
        report.failures.append(
            PreflightFailure(
                path=array_requirements[0][0],
                error="array did not materialize with required min_items during preflight",
            )
        )
        raise SchemaPreflightError(f"preflight failed: {report.failures[-1].error}")
    return report, gen


def build_schema(
    name: str,
    payload: dict | str,
    *,
    source_path: str | None = None,
    checksum: str | None = None,
) -> SchemaDoc:
    """Parse, validate, flatten, and preflight a schema into a `SchemaDoc`.

    Args:
        name (str): Schema name.
        payload (dict | str): Parsed mapping or raw YAML string.
        source_path (str | None): Optional reference to the source file.
        checksum (str | None): Optional checksum of the payload.

    Returns:
        SchemaDoc: Fully prepared schema artifact.
    """
    spec = yaml.safe_load(payload) if isinstance(payload, str) else payload
    validator = Validator()
    root = validator.read(spec)
    contracts_by_path = _flatten(root)

    # Validate pool configuration
    pool_anchors = [
        path for path, c in contracts_by_path.items()
        if getattr(c, "pool", None) is not None
    ]
    if len(pool_anchors) > 1:
        raise SchemaValidationError(
            f"Only one field can have 'pool' set. Found: {pool_anchors}"
        )
    for path, contract in contracts_by_path.items():
        source = getattr(contract, "depends_on_pool", None)
        if source is not None:
            if not isinstance(source, str) or not source.strip():
                raise SchemaValidationError(
                    f"Field '{path}': depends_on_pool must be a schema name string."
                )
            if getattr(contract, "pool", None) is not None:
                raise SchemaValidationError(
                    f"Field '{path}': cannot have both pool and depends_on_pool set."
                )
            if getattr(contract, "bound_to", None) is not None:
                raise SchemaValidationError(
                    f"Field '{path}': cannot have both depends_on_pool and bound_to set."
                )

    engine_spec = _synthesize_root_spec(contracts_by_path)
    preflight, _gen = _preflight_sample(name, contracts_by_path, samples=3)
    return SchemaDoc(
        name=name,
        source_path=source_path,
        checksum=checksum,
        contracts_tree=root,
        contracts_by_path=contracts_by_path,
        engine_spec=engine_spec,
        preflight=preflight,
    )
