from __future__ import annotations

from typing import Any, List, Mapping

from pydantic import BaseModel

from havocforge.contracts import ObjectGeneratorSpec

from havocforge.schema.handlers import get_handlers
from havocforge.schema.contract_registry import get_class_for_token
from havocforge.schema.errors import (
    SchemaTypeError,
    SchemaRegistryKeyError,
    SchemaValidationError,
)


class Validator:
    """Contract-first reader producing Pydantic contract models."""

    def __init__(self) -> None:
        self._handlers = get_handlers()

    # helpers
    def _ensure_map(self, node: Any, path: str) -> Mapping[str, Any]:
        if not isinstance(node, Mapping):
            raise SchemaTypeError(
                f"{path}: expected mapping, got {type(node).__name__}"
            )
        return node

    def _ensure_list(self, node: Any, path: str) -> List[Any]:
        if not isinstance(node, list):
            raise SchemaTypeError(f"{path}: expected list, got {type(node).__name__}")
        return node

    def _coerce_map(self, node: Any, path: str) -> Mapping[str, Any]:
        return {} if node is None else self._ensure_map(node, path)

    def _coerce_list(self, node: Any, path: str) -> List[Any]:
        return [] if node is None else self._ensure_list(node, path)

    def _instantiate(self, token: str, data: Mapping[str, Any], path: str) -> BaseModel:
        cls = get_class_for_token(token)
        if cls is None:
            raise SchemaRegistryKeyError(f"{path}: unknown type '{token}'")
        payload = dict(data)
        payload.pop("type", None)
        try:
            return cls(**payload)
        except Exception as exc:
            raise type(exc)(f"{path}: {exc}")

    # recursion
    def _read_node(self, node: Mapping[str, Any], path: str) -> BaseModel:
        token = node.get("type")
        if not isinstance(token, str):
            raise SchemaTypeError(f"{path}: missing or non-string 'type'")
        token_key = token.strip().lower()
        handler = self._handlers.get(token_key)
        payload = dict(node)
        if handler:
            return handler(self, token, payload, path)
        return self._instantiate(token, payload, path)

    #  public API
    def read(self, spec: Mapping[str, Any]) -> ObjectGeneratorSpec:
        """Parse a schema mapping into a contract tree rooted at an object."""
        root = self._read_node(self._ensure_map(spec, "$"), "$")
        if not isinstance(root, ObjectGeneratorSpec):
            raise SchemaValidationError(
                "root must be an object contract (ObjectGeneratorSpec)"
            )
        return root
