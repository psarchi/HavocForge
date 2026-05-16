from __future__ import annotations

from typing import Any, Iterable, Tuple, Type

from fastapi.responses import JSONResponse

from havocforge.errors import HavocforgeError, PoolEmptyError, SchemaConfigError
from havocforge.chaos.errors import (
    ChaosConfigError,
    ChaosOpError,
    ChaosOpNotFoundError,
    ChaosOpValidationError,
    ChaosRegistryError,
)
from havocforge.config.errors import (
    ConfigDefaultsError,
    ConfigSchemaError,
)
from havocforge.core.errors import UnknownGeneratorError
from havocforge.generators.errors import GeneratorError, InvalidParameterError
from havocforge.schema.errors import (
    SchemaError,
    SchemaValidationError,
    SchemaRegistryKeyError,
    SchemaPreflightError,
)


ERROR_MAP: Iterable[Tuple[Type[BaseException], str, int]] = (
    (PoolEmptyError, "ERR_POOL_EMPTY", 422),
    (SchemaConfigError, "ERR_SCHEMA_CONFIG", 422),
    (ChaosOpNotFoundError, "ERR_CHAOS_OP_NOT_FOUND", 404),
    (ChaosRegistryError, "ERR_CHAOS_REGISTRY", 400),
    (ChaosConfigError, "ERR_CHAOS_CONFIG", 400),
    (ChaosOpValidationError, "ERR_CHAOS_OP_VALIDATION", 400),
    (ChaosOpError, "ERR_CHAOS_OP", 500),
    (ConfigDefaultsError, "ERR_CONFIG_DEFAULTS", 500),
    (ConfigSchemaError, "ERR_CONFIG_SCHEMA", 400),
    (SchemaRegistryKeyError, "ERR_SCHEMA_NOT_FOUND", 404),
    (SchemaValidationError, "ERR_SCHEMA_VALIDATION", 422),
    (SchemaPreflightError, "ERR_SCHEMA_PREFLIGHT", 500),
    (SchemaError, "ERR_SCHEMA", 400),
    (UnknownGeneratorError, "ERR_GENERATOR_UNKNOWN", 400),
    (InvalidParameterError, "ERR_GENERATOR_PARAMS", 400),
    (GeneratorError, "ERR_GENERATOR", 500),
    (HavocforgeError, "ERR_ENGINE", 400),
)


def _classify(exc: BaseException) -> tuple[str, int]:
    for exc_type, code, status in ERROR_MAP:
        if isinstance(exc, exc_type):
            return code, status
    return "ERR_INTERNAL", 500


def _extract_path(exc: BaseException) -> list[str | int] | None:
    path = getattr(exc, "path", None)
    if not path:
        return None
    if isinstance(path, (list, tuple)):
        return list(path)
    return [path]


def build_error_response(exc: BaseException, request) -> JSONResponse:
    code, status = _classify(exc)
    message = str(exc) or code
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
        "path": _extract_path(exc),
        "context": getattr(exc, "context", None) or None,
        "trace_id": request.headers.get("x-request-id")
        or request.headers.get("x-correlation-id")
        or None,
    }
    return JSONResponse(payload, status_code=status)


def build_unhandled_response(exc: BaseException, request) -> JSONResponse:
    payload: dict[str, Any] = {
        "code": "ERR_INTERNAL",
        "message": "Internal server error",
        "trace_id": request.headers.get("x-request-id")
        or request.headers.get("x-correlation-id")
        or None,
    }
    return JSONResponse(payload, status_code=500)
