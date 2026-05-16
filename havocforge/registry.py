"""Unified type-based registry for generators, chaos ops, and other components."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Type, TypeVar
from havocforge.errors import DuplicateRegistryKeyError, MissingRegistryKeyError

if TYPE_CHECKING:
    pass

T = TypeVar("T")


class Registry:
    """Unified type-based registry for generators, chaos ops, contracts, etc."""

    _registry: Dict[Type, Dict[str, Type]] = {}

    @classmethod
    def register(cls, base_class: Type[T]):
        """Decorator to register a class under a base type.

        Args:
            base_class: The base class type to register under (e.g., BaseGenerator)

        Returns:
            Decorator function that registers the target class

        Raises:
            MissingRegistryKeyError: If class is missing 'key'/'__aliases__'.
            DuplicateRegistryKeyError: If a key or alias is already registered.

        Example:
            @Registry.register(BaseGenerator)
            class TimestampGenerator(BaseGenerator):
                key = "timestamp"
                ...
        """

        def wrapper(target_class: Type[T]) -> Type[T]:
            if base_class not in cls._registry:
                cls._registry[base_class] = {}

            key = getattr(target_class, "key", None)
            if not key:
                aliases = getattr(target_class, "__aliases__", None)
                if aliases and len(aliases) > 0:
                    key = aliases[0]
                else:
                    raise MissingRegistryKeyError(
                        f"{target_class.__name__} must have 'key' or '__aliases__' attribute for registration"
                    )

            if key in cls._registry[base_class]:
                existing = cls._registry[base_class][key]
                raise DuplicateRegistryKeyError(
                    f"Duplicate {base_class.__name__} key '{key}': "
                    f"{target_class.__name__} conflicts with {existing.__name__}"
                )

            cls._registry[base_class][key] = target_class

            aliases = getattr(target_class, "__aliases__", None)
            if aliases:
                for alias in aliases:
                    if alias != key and alias not in cls._registry[base_class]:
                        cls._registry[base_class][alias] = target_class

            return target_class

        return wrapper

    @classmethod
    def get(cls, base_class: Type[T], key: str) -> Type[T] | None:
        """Get a registered class by base type and key.

        Args:
            base_class: The base class type to search under
            key: The key to look up

        Returns:
            The registered class, or None if not found

        Example:
            gen_cls = Registry.get(BaseGenerator, "timestamp")
        """
        return cls._registry.get(base_class, {}).get(key)

    @classmethod
    def get_all(cls, base_class: Type[T]) -> Dict[str, Type[T]]:
        """Get all registered classes for a base type.

        Args:
            base_class: The base class type to get all registrations for

        Returns:
            Dictionary mapping keys to registered classes

        Example:
            all_generators = Registry.get_all(BaseGenerator)
        """
        return cls._registry.get(base_class, {}).copy()

    @classmethod
    def clear(cls, base_class: Type[T] | None = None) -> None:
        """Clear registry for testing.

        Args:
            base_class: If provided, clear only this base class namespace.
                       If None, clear entire registry.

        Example:
            Registry.clear(BaseGenerator)  # Clear only generators
            Registry.clear()                # Clear everything
        """
        if base_class is None:
            cls._registry.clear()
        else:
            cls._registry.pop(base_class, None)
