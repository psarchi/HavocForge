from __future__ import annotations

import sys
import keyword
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple, Optional

import unicodedata
import yaml
from havocforge.config.constants import TYPE_MAP
from havocforge.config.errors import (
    ConfigDefaultsFormatError,
    DuplicateConfigRootError,
)


# Auto-discover CONF_ROOT by searching upwards for a directory that contains "config/default"
def _discover_conf_root(start: Path | None = None) -> Path:
    start = start or Path(__file__).resolve()
    cur = start
    # climb up at most 8 levels
    for _ in range(8):
        if (cur / "config" / "default").exists():
            return cur
        cur = cur.parent
    # fallback to project root if known via env var or cwd
    try:
        import os

        env = os.getenv("MDE_CONF_ROOT")
        if env:
            p = Path(env)
            if (p / "config" / "default").exists():
                return p
    except Exception:
        pass
    # last resort: use two parents up (legacy); may be wrong but better than None
    return Path(__file__).resolve().parents[3]


# TODO(paths): Make CONF_ROOT configurable via env var or parameter.
CONF_ROOT = _discover_conf_root()  # auto-discovered project root
DEFAULTS_DIR = CONF_ROOT / "config" / "default"
OVERRIDES_DIR = CONF_ROOT / "config"
YAML_GLOBS = ("*.yaml", "*.yml")


def find_yaml_files(root: Path, include_subdirs: bool = False) -> List[Path]:
    """Return YAML files under ``root`` with optional recursive search.

    Args:
        root (Path): Directory to scan.
        include_subdirs (bool): If True, uses ``rglob`` to recurse into
            subdirectories; otherwise scans only the top level.

    Returns:
        List[Path]: Sorted list of matching ``*.yml``/``*.yaml`` files.
    """
    files: List[Path] = []
    if include_subdirs:
        for pat in YAML_GLOBS:
            files.extend(sorted(root.rglob(pat)))
    else:
        for pat in YAML_GLOBS:
            files.extend(sorted(root.glob(pat)))
    return files


def load_yaml(p: Path) -> Any:
    """Load a YAML file and return the parsed Python object.

    Args:
        p (Path): Path to the YAML file.

    Returns:
        Any: Result of ``yaml.safe_load``.
    """
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def discover_roots(defaults_dir: Path = DEFAULTS_DIR) -> Dict[str, Dict[str, Any]]:
    """Load default root documents from ``/config/default``.

    Reads each YAML file and expects a single top-level mapping per file where
    each key is a root name and its value is a dict schema. Duplicate root
    names across files raise an error.

    Args:
        defaults_dir (Path): Directory containing default YAML files.

    Returns:
        Dict[str, Dict[str, Any]]: Mapping of ``root_name -> root_payload``.

    Raises:
        ConfigDefaultsFormatError: If a file is not a non-empty mapping or a root payload is invalid.
        DuplicateConfigRootError: If duplicate roots are encountered across files.
    """
    roots: Dict[str, Dict[str, Any]] = {}
    for p in find_yaml_files(defaults_dir):
        data = load_yaml(p)
        if not isinstance(data, dict) or not data:
            raise ConfigDefaultsFormatError(
                f"default file must be a non-empty object: {p}", path=str(p)
            )
        for root_name, root_payload in data.items():
            if not isinstance(root_payload, dict):
                raise ConfigDefaultsFormatError(
                    f"root '{root_name}' in {p} must be an object",
                    path=f"{p}:{root_name}",
                )
            if root_name in roots:
                raise DuplicateConfigRootError(
                    f"duplicate root '{root_name}' across default files; split/merge explicitly. File: {p}",  # noqa
                    path=root_name,
                )
            roots[root_name] = root_payload
    return roots


def discover_overrides(
    overrides_dir: Path = OVERRIDES_DIR,
) -> Dict[str, List[Tuple[Path, Dict[str, Any]]]]:
    """Collect per-root override mappings from ``/config``.

    Scans YAML files in ``overrides_dir`` (excluding ``/config/default``),
    accepts multiple roots per file, and returns a stable filename-ordered list
    of overrides per root.

    Args:
        overrides_dir (Path): Directory to scan for override files.

    Returns:
        Dict[str, List[Tuple[Path, Dict[str, Any]]]]: Mapping of ``root_name``
            to a list of ``(file_path, override_payload)`` tuples ordered by
            filename.
    """
    result: Dict[str, List[Tuple[Path, Dict[str, Any]]]] = {}
    for p in find_yaml_files(overrides_dir):
        try:
            if DEFAULTS_DIR in p.parents:
                continue
        except Exception:
            pass
        data = load_yaml(p)
        if not isinstance(data, dict) or not data:
            continue
        for root_name, payload in data.items():
            if not isinstance(payload, dict):
                continue
            result.setdefault(root_name, []).append((p, payload))
    for k in list(result.keys()):
        result[k] = sorted(result[k], key=lambda t: str(t[0]))
    return result


def is_valid_identifier(s: str, *, ascii_only: bool = False) -> bool:
    """Return True if s is a valid (non-keyword) Python identifier.

    Args:
        s (str): Candidate identifier.
        ascii_only (bool): If True, reject non-ASCII letters/digits/underscore.

    Returns:
        bool: Whether s is a valid identifier and not a Python keyword.
    """
    if not isinstance(s, str):
        return False
    if not s.isidentifier():
        return False
    if keyword.iskeyword(s):
        return False
    if ascii_only and any(ord(ch) > 127 for ch in s):
        return False
    return True


def split_path(path: str) -> List[str]:
    """Split a dot/bracket path into components.

    Supports mixed notation such as ``server.sinks["http"].url`` and index
    access like ``codes[1]``. Returns components with indices preserved as
    ``"[1]"`` and quoted keys returned as their raw content.

    Args:
        path (str): Canonical config path using dot/bracket notation.

    Returns:
        List[str]: Component list, e.g., ``["server","sinks","http","url"]``.
    """
    out: List[str] = []
    i = 0
    cur = ""
    in_brackets = False
    quoted = False
    while i < len(path):
        ch = path[i]
        if not in_brackets:
            if ch == ".":
                if cur:
                    out.append(cur)
                    cur = ""
            elif ch == "[":
                if cur:
                    out.append(cur)
                    cur = ""
                in_brackets = True
                quoted = False
                cur = ""
            else:
                cur += ch
        else:
            if ch == '"' and not quoted:
                quoted = True
            elif ch == '"' and quoted:
                quoted = False
            elif ch == "]" and not quoted:
                content = cur
                if content.isdigit():
                    out.append(f"[{content}]")
                else:
                    out.append(content)
                cur = ""
                in_brackets = False
            else:
                cur += ch
        i += 1
    if cur:
        out.append(cur)
    return out


def join_path(parts: Iterable[str]) -> str:
    """Join path components into a canonical dot/bracket string.

    Reverses :func:`split_path` where possible, emitting dot notation for
    identifier-safe segments and bracket notation for indices or odd keys.

    Args:
        parts (Iterable[str]): Path components such as those produced by
            :func:`split_path`.

    Returns:
        str: Canonical path string.
    """
    out: List[str] = []
    for p in parts:
        if p.startswith("[") and p.endswith("]"):
            if out:
                out[-1] = f"{out[-1]}{p}"
            else:
                out.append(p)
        elif is_valid_identifier(p) and "." not in p:
            out.append(p if not out else f"{out[-1]}.{p}" if out[-1] else p)
        else:
            if not out:
                out.append(p)
            else:
                out[-1] = f'{out[-1]}["{p}"]'
    return out[-1] if out else ""


def normalize_declared_type(t: Optional[str]) -> str:
    """Normalize a declared type string to a lowercase token.

    Args:
        t (Optional[str]): Type name from schema (e.g., ``"Int"``, ``None``).

    Returns:
        str: Lowercased canonical token (defaults to ``"string"``).
    """
    if not isinstance(t, str):
        return "string"
    return t.strip().lower()


def pytype_for_declared(t: str) -> Any:
    """Map a declared type token to a Python type.

    Args:
        t (str): Declared type (e.g., ``"int"``, ``"array"``).

    Returns:
        Any: Python type (``int``, ``float``, etc.) or ``str`` as fallback.
    """
    t = normalize_declared_type(t)
    if t not in TYPE_MAP:
        return str
    return TYPE_MAP[t]


def type_of_value(v):
    """Return a loose type label for a runtime value.

    This is used when deriving a human-friendly type string from actual values
    in overrides or defaults (e.g., for normalization logs), independent of
    declared schema types.

    Args:
        v (Any): Value to inspect.

    Returns:
        str: One of ``"bool"``, ``"int"``, ``"float"``, ``"string"``,
            ``"array"``, ``"object"``, or ``"null"``.
    """
    for typ, name in (
        (bool, "bool"),
        (int, "int"),
        (float, "float"),
        (str, "string"),
        (list, "array"),
        (dict, "object"),
    ):
        if isinstance(v, typ):
            return name
    return "null" if v is None else "string"


def _safe_attr_name(name: str) -> str:
    """Return a safe attribute name from an arbitrary schema key.

    Converts non-identifier characters to underscores and ensures a leading
    letter by prefixing ``'f_'`` when necessary.

    Args:
        name (str): Raw field name from a schema or override file.

    Returns:
        str: A valid Python identifier suitable for attribute access.
    """
    if name.isidentifier():
        return name
    safe = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in name)
    if not safe or not safe[0].isalpha():
        safe = f"f_{safe or 'field'}"
    return safe


def _safe_field_name(
    name: str, *, ascii_only: bool = False
) -> Tuple[str, Optional[str]]:
    """Return a valid identifier and optional alias for a schema field name.

    If `name` isn’t a valid identifier (or is a keyword), return a sanitized
    identifier and set alias to the original `name`. Otherwise, alias is None.
    """
    original = name
    name = unicodedata.normalize("NFKC", name)

    if is_valid_identifier(name, ascii_only=ascii_only):
        return name, None
    safe_chars: list[str] = []
    for ch in name:
        if ch == "_":
            safe_chars.append("_")
        elif ch.isalnum() and (not ascii_only or ord(ch) < 128):
            safe_chars.append(ch)
        else:
            safe_chars.append("_")
    safe: str = "".join(safe_chars)

    if not safe or not (safe[0].isalpha() or safe[0] == "_"):
        safe = f"f_{safe or 'field'}"
    while "__" in safe:
        safe = safe.replace("__", "_")
    safe = safe.strip("_") or "f_field"
    if (
        keyword.iskeyword(safe)
        or not safe.isidentifier()
        or (ascii_only and any(ord(ch) > 127 for ch in safe))
    ):
        safe = f"f_{safe}"
        if not safe[0].isalpha() and safe[0] != "_":
            safe = f"f_{safe}"

    return safe, original


class LogEntry:
    """A single structured log line produced during config application.

    Attributes:
        level (str): Category (``APPLIED``, ``SKIPPED``, ``CONFLICT``, ``ERROR``,
            ``NORMALIZE``).
        path (str): Canonical path affected by the action.
        msg (str): Human-readable message.
        file (Optional[Path]): Source file responsible for the action.
        extra (Dict[str, Any]): Arbitrary structured context.
    """

    __slots__ = ("level", "path", "msg", "file", "extra")

    def __init__(
        self,
        level: str,
        path: str,
        msg: str,
        file: Optional[Path] = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        """Initialize a log entry.

        Args:
            level (str): Log level/category.
            path (str): Affected config path.
            msg (str): Message text.
            file (Optional[Path]): Source file reference.
            extra (Optional[Dict[str, Any]]): Additional structured fields.
        """
        self.level = level  # "APPLIED" | "SKIPPED" | "CONFLICT" | "ERROR" | "NORMALIZE"
        self.path = path
        self.msg = msg
        self.file = file
        self.extra = extra or {}

    def __str__(self) -> str:
        src = f" ({self.file})" if self.file else ""
        return f"{self.level:<9} {self.path:<60} {self.msg}{src}"


class Logger:
    """In-memory collector for :class:`LogEntry` records.

    Provides simple accumulation plus pretty-print dump and a one-line summary.
    """

    def __init__(self) -> None:
        self.entries: List[LogEntry] = []

    def add(
        self, level: str, path: str, msg: str, file: Optional[Path] = None, **extra: Any
    ) -> None:
        """Append a new log entry to the buffer.

        Args:
            level (str): Log category.
            path (str): Canonical path.
            msg (str): Message text.
            file (Optional[Path]): Source file.
            **extra (Any): Additional structured context.
        """
        self.entries.append(LogEntry(level, path, msg, file, extra))

    def dump(self, stream=None) -> None:
        """Print all collected log entries to ``stream``.

        Args:
            stream: File-like object with ``write``; defaults to ``sys.stdout``.
        """
        stream = stream or sys.stdout
        for e in self.entries:
            stream.write(f"{str(e)}\n")

    def summary(self, stream=None) -> None:
        """Print a one-line summary with counts per log level.

        Args:
            stream: File-like object with ``write``; defaults to ``sys.stdout``.
        """
        stream = stream or sys.stdout
        counts: Dict[str, int] = {}
        for e in self.entries:
            counts[e.level] = counts.get(e.level, 0) + 1
        summary_line = "SUMMARY " + " ".join(
            f"{k.lower()}={v}" for k, v in sorted(counts.items())
        )
        stream.write(f"{summary_line}\n")
