from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, ValidationError

from havocforge.config.builder import build_config, BuiltRoot
from havocforge.config.utils import Logger, discover_overrides, _safe_attr_name
from havocforge.config.errors import ConfigError


@dataclass
class Provenance:
    """Record of the first override that set a specific config path.

    Attributes:
        file (Path): Path to the override file that applied the value.
        value_repr (str): ``repr()`` of the applied value, used to detect
            conflicts across multiple override files.
    """

    file: Path
    value_repr: str


class ConfigManager:
    """Load defaults, apply override files, and expose runtime/meta views.

    Builds Pydantic models from defaults and applies YAML/JSON overrides with
    conflict detection and rollback on validation errors. Uses provenance to
    detect multi-file conflicts and maintains readiness status for the server.

    Attributes:
        overrides_dir (Path): Directory scanned for per-root override files.
        print_logs (Literal['never','on_error','always']): Logging behavior.
        logger (Logger): In-memory log collector for load operations.
        built (Dict[str, BuiltRoot]): Build artifacts keyed by root name.
        provenance (Dict[str, Provenance]): First-writer record per path.
        ready (bool): True if the last load had no hard errors or conflicts.
        last_loaded_at (datetime | None): UTC timestamp of the last load.
        summary (Dict[str, int]): Counts per log level from the last load.
    """

    def __init__(
        self,
        overrides_dir: Path,
        print_logs: Literal["never", "on_error", "always"] = "on_error",
    ) -> None:  # noqa
        """Initialize the manager with override location and logging policy.

        Args:
            overrides_dir (Path): Directory containing per-root override files.
            print_logs (Literal['never','on_error','always']): When to print
                logs collected during ``load()``. Defaults to ``'always'``.
        """
        self.overrides_dir = overrides_dir
        self.print_logs: Literal["never", "on_error", "always"] = print_logs
        self.logger = Logger()
        self.built: Dict[str, BuiltRoot] = {}
        self.provenance: Dict[str, Provenance] = {}
        self.ready: bool = False
        self.last_loaded_at: datetime | None = None
        self.summary: Dict[str, int] = {}
        self._rollback_errors: int = 0  # overrides failed but rolled back
        self._hard_errors: int = 0  # conflicts or no-rollback cases

    def load(self) -> None:
        """Load defaults, apply overrides, compute summary, and set readiness.

        Rebuilds configuration from defaults, discovers and applies override
        files, logs successes/failures, computes per-level counts, sets
        ``ready``/``last_loaded_at``, and optionally prints logs. Raises if any
        conflicts or non-recoverable errors occurred.

        Raises:
            ConfigError: When conflicts or hard errors are detected during
                override application.
        """
        self.logger = Logger()
        self.ready = False
        # reset counters per load
        self._rollback_errors = 0
        self._hard_errors = 0

        try:
            self.built = build_config()
        except Exception as e:
            self.logger.add("ERROR", "<builder>", f"build failed: {e}")
            self._hard_errors += 1
            self.summary = self._compute_summary()
            self.ready = False
            if self.print_logs == "always":
                self.logger.dump()
                self.logger.summary()
            raise

        self.provenance.clear()

        overrides = discover_overrides(self.overrides_dir)
        for root_name, entries in overrides.items():
            if root_name not in self.built:
                self.logger.add("ERROR", root_name, "root not found in defaults")
                self._hard_errors += 1
                continue
            for file_path, payload in entries:
                self._apply_override_file(root_name, file_path, payload)

        # finalize status
        self.summary = self._compute_summary()
        has_problem = (self._hard_errors > 0) or (self.summary.get("CONFLICT", 0) > 0)
        self.last_loaded_at = datetime.now(timezone.utc)
        self.ready = not has_problem

        if self.print_logs == "always" or (
            self.print_logs == "on_error" and has_problem
        ):
            self.logger.dump()
            self.logger.summary()

        if has_problem:
            raise ConfigError(
                "one or more override errors/conflicts occurred; see console logs"
            )

    def reload(self) -> None:
        """Reload configuration by delegating to :meth:`load`."""
        self.load()

    @property
    def runtime(self) -> Dict[str, BaseModel]:
        """Mapping of root name to runtime Pydantic model instances.

        Returns:
            Dict[str, BaseModel]: The live runtime models keyed by root name.
        """
        return {k: v.runtime for k, v in self.built.items()}

    @property
    def meta(self) -> Dict[str, Any]:
        """Mapping of root name to meta trees.

        Returns:
            Dict[str, Any]: The meta trees keyed by root name as produced by
            the builder.
        """
        return {k: v.meta for k, v in self.built.items()}

    def get_root(self, name: str) -> Optional[BaseModel]:
        """Return a single runtime model by its root name.

        Args:
            name (str): Canonical root name to retrieve.

        Returns:
            Optional[BaseModel]: The runtime model instance if present, else
                ``None``.
        """
        bundle = self.built.get(name)
        return bundle.runtime if bundle else None

    def get_value(self, path: str, default: Any = None) -> Any:
        """Get a config value by dot-separated path.

        Args:
            path (str): Dot-separated path (e.g., "server.security.token_auth.enabled")
            default (Any): Default value if path not found

        Returns:
            Any: The config value or default if not found
        """
        parts = path.split(".")
        if not parts:
            return default

        root_name = parts[0]
        root = self.get_root(root_name)
        if root is None:
            return default

        current = root
        for part in parts[1:]:
            if not hasattr(current, part):
                return default
            current = getattr(current, part)

        return current

    def _compute_summary(self) -> Dict[str, int]:
        # TODO(logger): Move this into Logger and maintain counts incrementally.

        """Compute per-level log entry counts from the last load.

        Returns:
            Dict[str, int]: Mapping of log level to number of entries.
        """
        counts: Dict[str, int] = {}
        for e in self.logger.entries:
            counts[e.level] = counts.get(e.level, 0) + 1
        return counts

    def _apply_override_file(
        self, root_name: str, file_path: Path, payload: Dict[str, Any]
    ) -> None:
        """Apply one override file payload to a specific root.

        Args:
            root_name (str): Target configuration root name.
            file_path (Path): Source file path for logging/provenance.
            payload (Dict[str, Any]): Parsed override content (nested dict).
        """
        bundle = self.built[root_name]
        self._apply_object([root_name], bundle.meta, bundle.runtime, payload, file_path)

    def _apply_object(
        self,
        path_parts: List[str],
        meta_node,
        runtime_node,
        override_obj: Dict[str, Any],
        file_path: Path,
    ) -> None:
        """Recursively apply a nested override object at the given path.

        Descends through group/object meta nodes, resolving the correct runtime
        child by safe attribute name and delegating to :meth:`_apply_leaf` for
        scalars.

        Args:
            path_parts (List[str]): Current path components from the root.
            meta_node: Meta node describing the expected structure.
            runtime_node: Runtime model instance or sub-model.
            override_obj (Dict[str, Any]): Nested overrides to apply.
            file_path (Path): Source file path for logging/provenance.
        """
        if meta_node.kind not in ("group", "object"):
            self.logger.add(
                "ERROR",
                ".".join(path_parts),
                "expected group/object at this level; got scalar",
                file_path,
            )
            self._hard_errors += 1
            return

        children = meta_node.children or meta_node.properties or {}
        for key, val in override_obj.items():
            key_parts = path_parts + [key]
            child_meta = children.get(key)
            if not child_meta:
                self.logger.add(
                    "ERROR",
                    ".".join(key_parts),
                    "path not found in defaults",
                    file_path,
                )
                self._hard_errors += 1
                continue
            if child_meta.kind in ("group", "object") and isinstance(val, dict):
                attr = _safe_attr_name(key)
                child_runtime = getattr(runtime_node, attr, None)
                self._apply_object(key_parts, child_meta, child_runtime, val, file_path)
                continue
            self._apply_leaf(key_parts, child_meta, runtime_node, key, val, file_path)

    def _apply_leaf(
        self,
        path_parts: List[str],
        meta_leaf,
        runtime_parent,
        attr_name: str,
        value: Any,
        file_path: Path,
    ) -> None:
        """Set a leaf value with conflict detection and rollback on failure.

        If a different file already set the same path, logs a ``CONFLICT`` and
        aborts. Otherwise assigns via Pydantic to trigger validation; on
        ``ValidationError`` attempts to roll back to the previous value or a
        default (meta or field default). Logs each outcome.

        Args:
            path_parts (List[str]): Full path to the leaf from the root.
            meta_leaf: Meta node describing the leaf field and defaults.
            runtime_parent: Parent runtime model that owns the attribute.
            attr_name (str): Original (possibly unsafe) leaf name.
            value (Any): Value from the override payload to assign.
            file_path (Path): Source file path for logging/provenance.
        """
        path = ".".join(path_parts)
        prov = self.provenance.get(path)
        value_repr = repr(value)
        if prov and prov.value_repr != value_repr:
            self.logger.add(
                "CONFLICT",
                path,
                f"set by {prov.file}={prov.value_repr} and {file_path}={value_repr}",
            )
            self._hard_errors += 1
            return
        if not prov:
            self.provenance[path] = Provenance(file=file_path, value_repr=value_repr)

        attr = _safe_attr_name(attr_name)
        current_value = getattr(runtime_parent, attr, None)

        try:
            setattr(runtime_parent, attr, value)
        except ValidationError as ve:
            try:
                first = ve.errors()[0]
                reason = first.get("msg", str(ve))
            except Exception:
                reason = str(ve)

            fallback = current_value
            if fallback is None:
                fallback = getattr(meta_leaf, "default_value", None)
                if fallback is None:
                    fields = getattr(
                        runtime_parent.__class__, "__pydantic_fields__", {}
                    )
                    fld = fields.get(attr) if isinstance(fields, dict) else None
                    if fld is not None:
                        try:
                            fallback = getattr(fld, "default", None)
                        except Exception:
                            fallback = None

            if fallback is not None:
                try:
                    setattr(runtime_parent, attr, fallback)
                    self.logger.add(
                        "ERROR",
                        path,
                        f"{reason} — rolled back to default {repr(fallback)}",
                        file_path,
                    )
                    self._rollback_errors += 1
                    return
                except Exception as ex2:
                    self.logger.add(
                        "ERROR", path, f"{reason} — rollback failed: {ex2}", file_path
                    )
                    self._hard_errors += 1
                    return
            else:
                self.logger.add(
                    "ERROR", path, f"{reason} — no default to roll back to", file_path
                )
                self._hard_errors += 1
                return
        except Exception as ex:
            self.logger.add(
                "ERROR", path, f"pydantic validation error: {ex}", file_path
            )
            self._hard_errors += 1
            return

        self.logger.add("APPLIED", path, f"<- {value_repr}", file_path)
