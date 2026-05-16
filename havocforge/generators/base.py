"""Base class for all generators.

Provides a common construction and configuration contract used by concrete
generators. Behavior is intentionally minimal; subclasses implement
``_generate_impl`` and ``_sanity_check``.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from typing import Any, TYPE_CHECKING
from abc import abstractmethod

from havocforge.generators.utils import get_init_fields
from havocforge.observability import (
    generator_duration_seconds,
    generator_invocations_total,
)

if TYPE_CHECKING:  # import only for typing to avoid cycles
    from havocforge.context import GenContext
    from havocforge.types import JsonValue  # noqa: F401


def _check_metrics_disabled() -> bool:
    """Check if per-generator metrics should be disabled (called once at module load)."""
    try:
        from havocforge.config import get_config_manager

        cfg = get_config_manager().get_root("server")
        observability_cfg = getattr(cfg, "observability", None)
        if not observability_cfg:
            return True
        if not bool(getattr(observability_cfg, "metrics_enabled", True)):
            return True
        if not bool(getattr(observability_cfg, "enabled", True)):
            return True
        return bool(getattr(observability_cfg, "disable_generator_metrics", False))
    except Exception:
        return bool(os.getenv("DISABLE_GENERATOR_METRICS"))


_METRICS_DISABLED = _check_metrics_disabled()


class BaseGenerator:
    """Abstract base class for all generators.

    Subclasses must implement :meth:`_generate_impl` and :meth:`_sanity_check`.

    The :meth:`generate` method is a concrete wrapper that automatically tracks
    generator performance metrics.
    """

    __abstract__ = True

    def generate(self, ctx: "GenContext") -> "JsonValue":
        """Produce a value according to this generator's configuration.

        This method wraps :meth:`_generate_impl` with performance tracking.
        Subclasses should implement :meth:`_generate_impl` instead of this method.

        Args:
            ctx (GenContext): Execution context providing RNG, builder, and state.

        Returns:
            JsonValue: JSON-compatible value (str, int, float, bool, null, object, array).

        Raises:
            Exception: Subclasses should document specific errors.
        """
        # Skip per-generator metrics if disabled (40% performance boost in pre-gen)
        if _METRICS_DISABLED:
            return self._generate_impl(ctx)

        gen_type = self.__class__.__name__
        schema = getattr(ctx, "schema_name", "unknown")

        generator_invocations_total.labels(generator=gen_type, schema=schema).inc()

        start = time.perf_counter()
        result = self._generate_impl(ctx)
        duration = time.perf_counter() - start

        generator_duration_seconds.labels(generator=gen_type, schema=schema).observe(
            duration
        )

        return result

    @abstractmethod
    def _generate_impl(self, ctx: "GenContext") -> "JsonValue":
        """Implementation of value generation logic.

        Subclasses must implement this method instead of :meth:`generate`.

        Args:
            ctx (GenContext): Execution context providing RNG, builder, and state.

        Returns:
            JsonValue: JSON-compatible value (str, int, float, bool, null, object, array).

        Raises:
            Exception: Subclasses should document specific errors.
        """
        raise NotImplementedError

    @abstractmethod
    def _sanity_check(self, ctx: "GenContext") -> None:
        """Validate configuration and context preconditions.

        Args:
            ctx (GenContext): Execution context.

        Returns:
            None: This method enforces validation via exceptions.
        """
        raise NotImplementedError

    @classmethod
    def _init_fields(cls) -> list[str]:
        """Return constructor field names for this generator class.

        Returns:
            list[str]: Field names derived from ``__init__`` signature.
        """
        return get_init_fields(cls)

    @classmethod
    def from_spec(cls, builder: Any, spec: Mapping[str, Any]) -> "BaseGenerator":
        """Construct a generator instance from a specification mapping.

        The default behavior maps keys from ``spec`` to the class ``__init__``
        parameters (by name), then calls :meth:`configure` with any remaining
        keys.

        Args:
            builder (Any): Factory/builder provided by the framework (unused here).
            spec (Mapping[str, Any]): Generator specification parsed from configuration.

        Returns:
            BaseGenerator: Configured instance of ``cls``.
        """
        init_names = cls._init_fields()
        init_kwargs: dict[str, Any] = {}
        for name in init_names:
            if name in spec:
                init_kwargs[name] = spec[name]
        inst = cls(**init_kwargs)
        remaining = {k: v for k, v in spec.items() if k not in init_names}
        if remaining:
            inst.configure(**remaining)
        return inst

    def configure(self, *args: Any, **kwargs: Any) -> "BaseGenerator":
        """Apply positional/keyword overrides and return ``self``.

        Positional args map to ``__init__`` parameters by position; keyword args
        override by name. Unknown kwargs are ignored to preserve behavior.

        Args:
            *args (Any): Positional overrides for ``__init__`` parameters.
            **kwargs (Any): Keyword overrides for ``__init__`` parameters.

        Returns:
            BaseGenerator: ``self`` for fluent chaining.
        """
        init_names = self._init_fields()
        for position, value in enumerate(args):
            if position < len(init_names):
                setattr(self, init_names[position], value)
        for name, value in kwargs.items():
            if name in init_names:
                setattr(self, name, value)
        return self

    def reset(self) -> "BaseGenerator":
        """Reset all ``__init__`` fields to ``None`` and return ``self``.

        Returns:
            BaseGenerator: ``self`` for fluent chaining.
        """
        for name in self._init_fields():
            setattr(self, name, None)
        return self
