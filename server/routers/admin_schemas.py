from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Body, HTTPException

from havocforge.schema.builder import build_schema
from havocforge.schema.registry import SchemaRegistry
from server.auth import RequireAuth

router = APIRouter(prefix="/v1/admin/schemas", tags=["admin-schemas"])

_SCHEMAS_DIR = Path("schemas")


@router.get("/debug")
def list_schemas(_token: RequireAuth = None) -> dict[str, Any]:
    """List all registered schemas and their revisions.

    Returns:
        dict with registered schemas, disk schemas, and cache state
    """
    registered = {}
    for name in SchemaRegistry._store.keys():
        try:
            revision = SchemaRegistry.get_revision(name)
            doc = SchemaRegistry.get(name)
            registered[name] = {
                "revision": revision,
                "contracts_count": len(doc.contracts_by_path)
                if hasattr(doc, "contracts_by_path")
                else 0,
            }
        except Exception as e:
            registered[name] = {"error": str(e)}  # type: ignore[dict-item]

    disk_schemas = []
    for p in sorted(_SCHEMAS_DIR.glob("*.yml")) + sorted(_SCHEMAS_DIR.glob("*.yaml")):
        disk_schemas.append(p.stem)

    from server.deps import _GENERATOR_CACHE

    cache_info = {
        name: {"revision": rev} for name, (rev, _) in _GENERATOR_CACHE.items()
    }

    return {
        "registered": registered,
        "disk_schemas": disk_schemas,
        "generator_cache": cache_info,
    }


@router.get("/{name}")
def get_schema(name: str, _token: RequireAuth = None) -> dict[str, Any]:
    """Get schema details for a specific schema.

    Args:
        name: Schema name

    Returns:
        dict with schema document and metadata
    """
    try:
        doc = SchemaRegistry.get(name)
        revision = SchemaRegistry.get_revision(name)

        return {
            "name": name,
            "revision": revision,
            "contracts_by_path": doc.contracts_by_path,
        }
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"Schema '{name}' not found in registry"
        )


@router.get("/{name}/raw")
def get_schema_raw(name: str, _token: RequireAuth = None) -> dict[str, Any]:
    """Get raw YAML schema from disk.

    Args:
        name: Schema name

    Returns:
        Raw schema YAML as dict
    """
    schema_path = _SCHEMAS_DIR / f"{name}.yaml"
    if not schema_path.exists():
        schema_path = _SCHEMAS_DIR / f"{name}.yml"

    if not schema_path.exists():
        raise HTTPException(
            status_code=404, detail=f"Schema file '{name}.yaml' not found on disk"
        )

    try:
        payload = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        return {"name": name, "path": str(schema_path), "schema": payload}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read schema: {str(e)}")


@router.post("/{name}/validate")
def validate_schema(
    name: str, schema_payload: dict = Body(...), _token: RequireAuth = None
) -> dict[str, Any]:
    """Validate a schema document without registering it.

    Args:
        name: Schema name
        schema_payload: Schema YAML as dict

    Returns:
        Validation result
    """
    try:
        doc = build_schema(name, schema_payload)
        return {
            "valid": True,
            "name": name,
            "contracts_count": len(doc.contracts_by_path),
            "paths": list(doc.contracts_by_path.keys()),
        }
    except Exception as e:
        return {
            "valid": False,
            "name": name,
            "error": str(e),
            "error_type": type(e).__name__,
        }


@router.post("/{name}/reload")
def reload_schema(name: str, _token: RequireAuth = None) -> dict[str, Any]:
    """Reload a schema from disk and update registry.

    Args:
        name: Schema name

    Returns:
        Reload result with new revision
    """
    schema_path = _SCHEMAS_DIR / f"{name}.yaml"
    if not schema_path.exists():
        schema_path = _SCHEMAS_DIR / f"{name}.yml"

    if not schema_path.exists():
        raise HTTPException(
            status_code=404, detail=f"Schema file '{name}.yaml' not found on disk"
        )

    try:
        payload = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        doc = build_schema(name, payload)
        SchemaRegistry.register(name, doc)
        new_revision = SchemaRegistry.get_revision(name)

        from server.deps import _GENERATOR_CACHE

        if name in _GENERATOR_CACHE:
            del _GENERATOR_CACHE[name]

        return {
            "success": True,
            "name": name,
            "revision": new_revision,
            "message": f"Schema '{name}' reloaded successfully",
        }
    except Exception as e:
        return {
            "success": False,
            "name": name,
            "error": str(e),
            "error_type": type(e).__name__,
        }


@router.post("/reload-all")
def reload_all_schemas(_token: RequireAuth = None) -> dict[str, Any]:
    """Reload all schemas from disk.

    Returns:
        Summary of reload operation
    """
    results = []

    for p in sorted(_SCHEMAS_DIR.glob("*.yml")) + sorted(_SCHEMAS_DIR.glob("*.yaml")):
        name = p.stem
        try:
            payload = yaml.safe_load(p.read_text(encoding="utf-8"))
            doc = build_schema(name, payload)
            SchemaRegistry.register(name, doc)
            results.append({"name": name, "success": True})
        except Exception as e:
            results.append({"name": name, "success": False, "error": str(e)})

    from server.deps import _GENERATOR_CACHE

    _GENERATOR_CACHE.clear()

    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count

    return {
        "total": len(results),
        "success": success_count,
        "failed": fail_count,
        "results": results,
    }
