from __future__ import annotations

from typing import Any, ClassVar, Dict, Optional, Type

from havocforge.contracts.base import ContractModel
from havocforge.chaos.drift.registry import DRIFT_REGISTRY


class DriftSpecMeta(type):
    """Metaclass that registers drift handlers on subclass definition."""

    def __init__(cls, name, bases, attrs):
        super().__init__(name, bases, attrs)
        spec_cls: Optional[Type[ContractModel]] = getattr(cls, "spec_cls", None)
        handlers: Dict[str, str] = getattr(cls, "handlers", {})
        if spec_cls and handlers:
            for kind, method_name in handlers.items():
                handler = getattr(cls, method_name)
                DRIFT_REGISTRY.register(kind, spec_cls, handler)


class DriftSpec(metaclass=DriftSpecMeta):
    """Subclass per generator to expose drift handlers."""

    spec_cls: ClassVar[Optional[Type[ContractModel]]] = None
    handlers: ClassVar[Dict[str, str]] = {}

    @staticmethod
    def noop(*args: Any, **kwargs: Any):
        return None
