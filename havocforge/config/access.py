from __future__ import annotations

import hashlib
from pathlib import Path
from threading import Lock
from typing import Optional
from havocforge.config.manager import ConfigManager
from havocforge.config.utils import OVERRIDES_DIR

__all__ = [
    "ConfigAccess",
    "get_config_manager",
    "reset_config_manager",
    "reload_config",
]


class ConfigAccess:
    """Lazy, thread-safe accessor for a shared :class:`ConfigManager` instance.

    Uses double-checked locking around a module-level singleton. The first call
    initializes the manager with ``OVERRIDES_DIR`` and triggers ``load()``.
    Subsequent calls reuse the same instance.

    Prefer this in application code where a long-lived manager is desirable.
    For tests, consider constructing a dedicated ``ConfigManager`` per test.
    """

    _manager_singleton: Optional[ConfigManager] = None
    _manager_lock: Lock = Lock()

    @classmethod
    def get(cls) -> ConfigManager:
        """Return the process-wide :class:`ConfigManager` instance.

        Initialization occurs at first call and is guarded by a lock. The
        manager is constructed with ``overrides_dir=OVERRIDES_DIR`` and
        ``load()`` is invoked before returning.

        Returns:
            ConfigManager: Shared, ready-to-use manager.
        """
        if cls._manager_singleton is None:
            with cls._manager_lock:
                if cls._manager_singleton is None:
                    cls._manager_singleton = ConfigManager(overrides_dir=OVERRIDES_DIR)
                    cls._manager_singleton.load()
        return cls._manager_singleton


_manager_singleton: Optional[ConfigManager] = None
_manager_lock = Lock()


def get_config_manager(overrides_dir: Path | None = None) -> ConfigManager:
    """Return a singleton :class:`ConfigManager` with optional directory override.

    Args:
        overrides_dir (Path | None): Directory containing overrides. If ``None``,
            defaults to :data:`OVERRIDES_DIR`.

    Returns:
        ConfigManager: Shared, loaded manager instance.

    Notes:
        - Uses double-checked locking to ensure exactly-once initialization.
        - Subsequent calls ignore differing ``overrides_dir`` values; configure
          the desired path on the first call.
    """
    global _manager_singleton
    if _manager_singleton is None:
        with _manager_lock:
            if _manager_singleton is None:
                if overrides_dir is None:
                    overrides_dir = OVERRIDES_DIR
                _manager_singleton = ConfigManager(overrides_dir=overrides_dir)
                _manager_singleton.load()
    return _manager_singleton


def reset_config_manager(overrides_dir: Path | None = None) -> ConfigManager:
    """Drop the singleton and create a fresh manager (then load)."""
    global _manager_singleton
    with _manager_lock:
        _manager_singleton = None
    return get_config_manager(overrides_dir=overrides_dir)


def reload_config() -> ConfigManager:
    """Force reload on the existing manager and return it."""
    mgr = get_config_manager()
    mgr.load()
    return mgr


def _hash_file(p: Path, h):
    try:
        h.update(str(p).encode("utf-8"))
        # include size + mtime to avoid heavy reads if desired
        st = p.stat()
        h.update(str(st.st_size).encode("utf-8"))
        h.update(str(int(st.st_mtime)).encode("utf-8"))
        # also mix a small chunk of content to be robust
        with p.open("rb") as f:
            chunk = f.read(4096)
        h.update(chunk)
    except Exception:
        pass


def _dir_digest(root: Path) -> str:
    from havocforge.config.utils import YAML_GLOBS

    h = hashlib.sha1()
    for pat in YAML_GLOBS:
        for p in sorted(root.rglob(pat)):
            _hash_file(p, h)
    return h.hexdigest()


_last_conf_hash: str | None = None


def get_config_hash() -> str:
    """Return a digest over defaults+overrides YAML trees."""
    from havocforge.config.utils import DEFAULTS_DIR, OVERRIDES_DIR

    h = hashlib.sha1()
    # Defaults
    try:
        h.update(_dir_digest(DEFAULTS_DIR).encode("utf-8"))
    except Exception:
        pass
    # Overrides
    try:
        h.update(_dir_digest(OVERRIDES_DIR).encode("utf-8"))
    except Exception:
        pass
    return h.hexdigest()


def ensure_config_fresh() -> bool:
    """Reload config if files changed since last check.

    Returns:
        bool: True if a reload happened, False otherwise.
    """
    global _last_conf_hash
    cur = get_config_hash()
    if _last_conf_hash is None:
        _last_conf_hash = cur
        return False
    if cur != _last_conf_hash:
        reload_config()
        _last_conf_hash = cur
        return True
    return False
