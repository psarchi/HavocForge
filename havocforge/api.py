from __future__ import annotations

import random
from collections.abc import Mapping
from typing import TYPE_CHECKING

from havocforge.context import GenContext
from havocforge.generators.base import BaseGenerator
from havocforge.spec_builder import SpecBuilder

if TYPE_CHECKING:  # import only for typing to avoid cycles
    from havocforge.types import JsonValue  # noqa: F401

__all__ = [
    "build_generator",
    "generate_one",
    "generate_many",
    "Havocforge",
    "build",
]

# Initialize global builder for the simple functional API.
_builder = SpecBuilder()


def build_generator(spec: Mapping[str, object]) -> BaseGenerator:
    """Build a generator from a spec mapping.

    Args:
        spec (Mapping[str, object]): Specification mapping parsed from configuration.

    Returns:
        BaseGenerator: Configured generator instance.
    """
    return _builder.build(spec)


def generate_one(
    gen: BaseGenerator,
    seed: int | None = None,
    locale: str = "en_US",
) -> "JsonValue":
    """Generate a single value from ``gen``.

    Args:
        gen (BaseGenerator): Generator instance.
        seed (int | None): Seed for deterministic behavior. ``None`` for random.
        locale (str): Locale identifier passed to :class:`GenContext`.

    Returns:
        JsonValue: Generated value.
    """
    rng = random.Random(seed)
    ctx = GenContext(rng=rng, locale=locale)
    return gen.generate(ctx)


def generate_many(
    gen: BaseGenerator,
    n: int = 10,
    seed: int | None = None,
    locale: str = "en_US",
) -> list["JsonValue"]:
    """Generate ``n`` values from ``gen``.

    Args:
        gen (BaseGenerator): Generator instance.
        n (int): Number of values to generate.
        seed (int | None): Seed for deterministic behavior. ``None`` for random.
        locale (str): Locale identifier passed to :class:`GenContext`.

    Returns:
        list[JsonValue]: List of generated values.
    """
    rng = random.Random(seed)
    ctx = GenContext(rng=rng, locale=locale)
    return [gen.generate(ctx) for _ in range(n)]


class Havocforge:
    """High-level façade for building generators and producing values.

    Wraps a builder plus a reusable RNG/context.

    Args:
        seed (int | None): Seed for deterministic behavior. ``None`` for random.
        locale (str): Locale identifier passed to :class:`GenContext`.
    """

    __slots__ = ("builder", "rng", "ctx")

    def __init__(self, seed: int | None = None, locale: str = "en_US") -> None:
        """Initialize engine components and context.

        Args:
            seed (int | None): Seed for deterministic behavior. ``None`` for random.
            locale (str): Locale identifier passed to :class:`GenContext`.
        """
        self.builder = SpecBuilder()
        self.rng = random.Random(seed)
        self.ctx = GenContext(rng=self.rng, locale=locale)

    def build(self, spec: Mapping[str, object]) -> BaseGenerator:
        """Build a generator from a spec mapping.

        Args:
            spec (Mapping[str, object]): Specification mapping parsed from configuration.

        Returns:
            BaseGenerator: Configured generator instance.
        """
        return self.builder.build(spec)

    def generate_one(self, gen: BaseGenerator) -> "JsonValue":
        """Generate a single value using the engine context.

        Args:
            gen (BaseGenerator): Generator instance.

        Returns:
            JsonValue: Generated value.
        """
        return gen.generate(self.ctx)

    def generate_many(self, gen: BaseGenerator, n: int = 10) -> list["JsonValue"]:
        """Generate ``n`` values using the engine context.

        Args:
            gen (BaseGenerator): Generator instance.
            n (int): Number of values to generate.

        Returns:
            list[JsonValue]: List of generated values.
        """
        return [gen.generate(self.ctx) for _ in range(n)]


def _contract_to_spec(name: str, contract: object) -> dict:
    to_spec = getattr(contract, "to_spec", None)
    if callable(to_spec):
        return to_spec(name, _contract_to_spec)
    from havocforge.schema.contract_registry import token_for_instance

    tok = token_for_instance(contract) or "string"
    try:
        d = contract.model_dump(exclude_none=True)  # type: ignore[attr-defined]
    except Exception:
        d = {}
    d["type"] = tok
    return d


def build(contracts_by_path: dict[str, object]):
    """Build a generator from a contracts map by synthesizing a root object spec."""
    root_fields = {}
    for path, spec in contracts_by_path.items():
        if "." not in path and "[]" not in path and "|" not in path:
            root_fields[path] = _contract_to_spec(path, spec)
    if not root_fields:
        # fallback
        for path, spec in contracts_by_path.items():
            if "|" in path:
                continue
            if path.endswith("[]"):
                key = path[:-2]
            else:
                key = path.split(".")[-1]
            root_fields[key] = _contract_to_spec(path, spec)
    root_spec = {"type": "object", "fields": root_fields}
    return _builder.build(root_spec)
