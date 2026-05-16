from __future__ import annotations

from typing import TYPE_CHECKING, Any

from havocforge.core.errors import MissingConfigureMethodError, UnknownGeneratorError
from havocforge.registry import Registry
from havocforge.generators.base import BaseGenerator

if TYPE_CHECKING:
    pass


class GeneratorFactory:
    """Factory for instantiating and configuring registered generators.

    Resolves generator classes from the unified Registry and instantiates them.
    """

    def __init__(self) -> None:
        """Initialize the factory.

        Note: No registry parameter needed - generators auto-register on import.
        """
        pass

    def resolve(self, name: str, **kwargs: Any) -> BaseGenerator:
        """Resolve, instantiate, and configure a generator by name.

        Looks up the generator class in the registry, constructs an instance,
        and calls ``configure(**kwargs)`` on it. The configured instance is
        returned.

        Args:
            name (str): Generator key (e.g., "timestamp", "int", "string").
            **kwargs (Any): Keyword arguments forwarded to ``configure``.

        Returns:
            BaseGenerator: Configured generator instance.

        Raises:
            UnknownGeneratorError: If no generator is registered for ``name``.
            MissingConfigureMethodError: The resolved generator instance has no
                callable ``configure`` method.
        """
        cls = Registry.get(BaseGenerator, name)  # type: ignore[type-abstract]
        if cls is None:
            available = list(Registry.get_all(BaseGenerator).keys())  # type: ignore[type-abstract]
            raise UnknownGeneratorError(
                f"unknown generator '{name}'. available: {', '.join(sorted(available))}"
            )

        instance: BaseGenerator = cls()
        configure = getattr(instance, "configure", None)
        if not callable(configure):
            raise MissingConfigureMethodError(
                f"{cls.__name__} has no configure() method"
            )
        return configure(**kwargs)
