from __future__ import annotations

from threading import Lock
from typing import Dict, Optional

from .manager import ChaosManager
from .ops.base import BaseChaosOp
from havocforge.config.access import get_config_manager
from havocforge.context import GenContext
from havocforge.registry import Registry

_manager_post: Optional[ChaosManager] = None
_manager_pre: Optional[ChaosManager] = None
_lock = Lock()

_registry_post: Optional[Dict[str, type[BaseChaosOp]]] = None
_registry_pre: Optional[Dict[str, type[BaseChaosOp]]] = None


def _build_registries() -> tuple[
    Dict[str, type[BaseChaosOp]], Dict[str, type[BaseChaosOp]]
]:
    all_ops = Registry.get_all(BaseChaosOp)
    pre: Dict[str, type[BaseChaosOp]] = {}
    post: Dict[str, type[BaseChaosOp]] = {}
    for name, cls in all_ops.items():
        phase = getattr(cls, "phase", "post")
        if str(phase).lower().startswith("pre"):
            pre[name] = cls
        else:
            post[name] = cls
    return post, pre


def get_chaos_manager(ctx=None, pre_gen: bool = False) -> ChaosManager:
    """Return a singleton ChaosManager.
    If ctx is provided, attach its RNG to the existing manager for the requested phase.
    """
    global _manager_post, _manager_pre, _registry_post, _registry_pre
    if _registry_post is None or _registry_pre is None:
        with _lock:
            if _registry_post is None or _registry_pre is None:
                _registry_post, _registry_pre = _build_registries()

    target_manager = _manager_pre if pre_gen else _manager_post

    if target_manager is None:
        with _lock:
            target_manager = _manager_pre if pre_gen else _manager_post
            if target_manager is None:
                chaos_cfg = get_config_manager().get_root("chaos")
                registry = _registry_pre if pre_gen else _registry_post
                target_manager = ChaosManager(
                    ctx=ctx or GenContext(),
                    config_snapshot=chaos_cfg,
                    registry=registry or {},
                )
                if pre_gen:
                    _manager_pre = target_manager
                else:
                    _manager_post = target_manager

    if ctx is not None:
        try:
            target_manager.ctx = ctx
            target_manager.rng = getattr(ctx, "rng", ctx)
        except Exception:
            setattr(target_manager, "ctx", ctx)
    return target_manager
