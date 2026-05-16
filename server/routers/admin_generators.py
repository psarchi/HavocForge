from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from havocforge.context import GenContext
from server.auth import RequireAuth
from server.deps import get_generator, get_correlation_redis

router = APIRouter(prefix="/v1/admin/generators", tags=["admin-generators"])


class GenerateRequest(BaseModel):
    """Request to generate data from a specific schema."""

    count: int = Field(1, ge=1, le=100, description="Number of items to generate")
    seed: int | None = Field(
        None, description="Optional seed for deterministic generation"
    )


@router.get("/debug")
def list_generators(_token: RequireAuth = None) -> dict[str, Any]:
    """List all cached generators.

    Returns:
        dict with generator cache info
    """
    from server.deps import _GENERATOR_CACHE

    cache_info = {}
    for name, (revision, gen) in _GENERATOR_CACHE.items():
        cache_info[name] = {
            "revision": revision,
            "generator_type": type(gen).__name__,
            "module": type(gen).__module__,
        }

    return {
        "cached_generators": cache_info,
        "cache_size": len(_GENERATOR_CACHE),
    }


@router.post("/{schema}/generate")
def invoke_generator(
    schema: str,
    request: GenerateRequest,
    http_request: Request,
    _token: RequireAuth = None,
) -> dict[str, Any]:
    """Invoke a specific generator with schema context.

    Args:
        schema: Schema name to use for generation
        request: Generation request with count and optional seed

    Returns:
        Generated items
    """
    try:
        gen = get_generator(schema)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Schema '{schema}' not found")
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to load generator: {str(e)}"
        )

    ctx = GenContext(seed=request.seed)
    ctx.schema_name = schema
    ctx._correlation_client = get_correlation_redis(http_request)

    try:
        items = [gen.generate(ctx) for _ in range(request.count)]
        return {
            "schema": schema,
            "count": len(items),
            "seed": ctx.seed,
            "items": items,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")


@router.get("/{schema}/info")
def get_generator_info(schema: str, _token: RequireAuth = None) -> dict[str, Any]:
    """Get information about a specific generator.

    Args:
        schema: Schema name

    Returns:
        Generator metadata and structure
    """
    try:
        gen = get_generator(schema)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Schema '{schema}' not found")
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to load generator: {str(e)}"
        )

    from server.deps import _GENERATOR_CACHE

    cached_info = _GENERATOR_CACHE.get(schema)

    return {
        "schema": schema,
        "generator_type": type(gen).__name__,
        "module": type(gen).__module__,
        "cached": cached_info is not None,
        "revision": cached_info[0] if cached_info else None,
    }


@router.post("/{schema}/clear-cache")
def clear_generator_cache(schema: str, _token: RequireAuth = None) -> dict[str, Any]:
    """Clear generator cache for a specific schema.

    Args:
        schema: Schema name

    Returns:
        Cache clear result
    """
    from server.deps import _GENERATOR_CACHE

    if schema in _GENERATOR_CACHE:
        del _GENERATOR_CACHE[schema]
        return {
            "success": True,
            "schema": schema,
            "message": f"Cache cleared for '{schema}'",
        }
    else:
        return {
            "success": False,
            "schema": schema,
            "message": f"No cached generator for '{schema}'",
        }


@router.post("/clear-cache")
def clear_all_generator_caches(_token: RequireAuth = None) -> dict[str, Any]:
    """Clear all generator caches.

    Returns:
        Cache clear summary
    """
    from server.deps import _GENERATOR_CACHE

    cleared_count = len(_GENERATOR_CACHE)
    _GENERATOR_CACHE.clear()

    return {
        "success": True,
        "cleared_count": cleared_count,
        "message": "All generator caches cleared",
    }
