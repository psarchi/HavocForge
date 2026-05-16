"""Builder utilities for composing generator specifications.

Normalizes loosely-typed input specs (strings/lists/mappings) into a canonical
shape and builds generator instances via the registry.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from havocforge.registry import Registry
from havocforge.generators.base import BaseGenerator
from havocforge.errors import (
    MissingTypeError,
    UnknownTypeError,
    InvalidSpecStructureError,
)

if TYPE_CHECKING:  # import only for typing to avoid cycles
    from havocforge.types import JsonValue  # noqa: F401


class SpecBuilder:
    """Normalize specs and construct generators using the unified registry.

    Generators are auto-registered via @Registry.register decorators.
    """

    __slots__ = ()

    def __init__(self) -> None:
        """Initialize the builder.

        Note: No registry parameter needed - generators auto-register on import.
        """
        pass

    # TODO(types): Make ``path`` consistently ``tuple[str, ...]``; callers pass mixed types today.
    # TODO(compat): Keep current string/list/dict normalization behavior until all callers migrate.
    def _normalize(
        self,
        spec: Mapping[str, object] | list[object] | str | object,
        path: tuple[str, ...] | str | None = "root",
    ) -> object:
        """Normalize nested specs into a canonical mapping/list/atom form.

        Args:
            spec (Mapping[str, object] | list[object] | str | object): Raw spec element.
            path (tuple[str, ...] | str | None): Schema location for error reporting.

        Returns:
            object: Canonicalized spec with children normalized recursively.

        Raises:
            NormalizationError: On irrecoverable structure problems.
        """
        if isinstance(spec, str):
            return {"type": spec}
        if isinstance(spec, list):
            # Note: path shape is kept as string for compatibility.
            return [self._normalize(s, path=f"{path}[]") for s in spec]
        if isinstance(spec, dict):
            normalized: dict[str, object] = {}
            for key, value in spec.items():
                if key == "type":
                    normalized[key] = value
                elif key == "pool":
                    # pool: true  → anchor only, no siblings (internal: [])
                    # pool: [...]  → anchor + sibling field names
                    # pool: false/None → not a pool source, skip
                    if value is True:
                        normalized[key] = []
                    elif value is False or value is None:
                        pass  # not a pool source
                    else:
                        normalized[key] = value
                elif isinstance(value, (dict, list)):
                    next_path = f"{path}.{key}"
                    normalized[key] = self._normalize(value, path=next_path)
                else:
                    normalized[key] = value
            return normalized
        # Atom value (kept as-is)
        return spec

    def build(
        self, spec: Mapping[str, object], path: tuple[str, ...] | str | None = "root"
    ) -> BaseGenerator:
        """Build a generator instance from a (possibly loose) spec mapping.

        Args:
            spec (Mapping[str, object]): Specification mapping parsed from configuration.
            path (tuple[str, ...] | str | None): Schema location for error reporting.

        Returns:
            BaseGenerator: Configured generator instance.

        Raises:
            MissingTypeError: If the normalized spec lacks a ``type``.
            InvalidSpecStructureError: If ``type`` is not a string.
            UnknownTypeError: If the registry cannot resolve the requested type.
        """
        normalized = self._normalize(spec, path=path)
        if not isinstance(normalized, dict) or "type" not in normalized:
            # TODO(errors): Consider NormalizationError with richer context once callers handle it.
            raise MissingTypeError("Invalid spec (missing 'type')", path=path)

        type_name = normalized["type"]
        if not isinstance(type_name, str):
            raise InvalidSpecStructureError("'type' must be string", path=path)

        gen_cls = Registry.get(BaseGenerator, type_name)  # type: ignore[type-abstract]
        if gen_cls is None:
            available = list(Registry.get_all(BaseGenerator).keys())  # type: ignore[type-abstract]
            raise UnknownTypeError(
                f"unknown generator '{type_name}'. available: {', '.join(sorted(available))}",
                path=path,
            )

        return gen_cls.from_spec(self, normalized)
