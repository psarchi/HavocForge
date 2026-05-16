from __future__ import annotations
from typing import Any, Dict, Optional, Type

_TOKEN_CACHE: Dict[str, Type] = {}
_CLASS_TOKEN: Dict[Type, str] = {}


def _load_contracts_module():
    from havocforge import contracts as _contracts

    return _contracts


def _iter_contract_classes():
    """
    Yield contract classes that declare a `type_token` ClassVar.
    This works for Pydantic v2 BaseModels (no dataclass checks).
    """
    mod = _load_contracts_module()
    for _, obj in vars(mod).items():
        if isinstance(obj, type) and hasattr(obj, "type_token"):
            yield obj


def build_registry() -> None:
    """Build token -> class, plus aliases -> class."""
    global _TOKEN_CACHE, _CLASS_TOKEN
    if _TOKEN_CACHE:
        return
    for cls in _iter_contract_classes():
        token = getattr(cls, "type_token", None)
        if not token:
            continue
        _TOKEN_CACHE[str(token)] = cls
        _CLASS_TOKEN[cls] = str(token)
        aliases = getattr(cls, "type_aliases", None) or set()
        for alias in aliases:
            _TOKEN_CACHE[str(alias)] = cls


def get_class_for_token(token: str) -> Optional[Type]:
    build_registry()
    return _TOKEN_CACHE.get(token)


def token_for_instance(obj: Any) -> Optional[str]:
    build_registry()
    return _CLASS_TOKEN.get(type(obj))
