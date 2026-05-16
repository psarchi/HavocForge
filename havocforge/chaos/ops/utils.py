from __future__ import annotations

from typing import Any, Callable, Iterable, Iterator, NamedTuple


class NodeRef(NamedTuple):
    """Reference to a node within a nested dict/list payload."""

    parent: Any
    key: Any
    path: str
    value: Any


def iter_nodes(root: Any) -> Iterator[NodeRef]:
    """Depth-first traversal yielding NodeRef for every node."""
    stack: list[NodeRef] = [NodeRef(parent=None, key=None, path="", value=root)]
    while stack:
        ref = stack.pop()
        yield ref
        value = ref.value
        if isinstance(value, dict):
            for k, v in value.items():
                child_path = f"{ref.path}.{k}" if ref.path else str(k)
                stack.append(NodeRef(parent=value, key=k, path=child_path, value=v))
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                child_path = f"{ref.path}[{idx}]" if ref.path else f"[{idx}]"
                stack.append(
                    NodeRef(parent=value, key=idx, path=child_path, value=item)
                )


def iter_lists(
    root: Any,
    *,
    include_root: bool = True,
    root_label: str = "[root]",
) -> Iterator[tuple[str, list[Any], Any, Any]]:
    """Yield (path, list_obj, parent, key) for every list in *root*."""
    for ref in iter_nodes(root):
        if isinstance(ref.value, list):
            if not include_root and ref.path == "":
                continue
            yield (ref.path or root_label, ref.value, ref.parent, ref.key)


def iter_leaf_refs(
    root: Any,
    *,
    predicate: Callable[[Any], bool] | None = None,
) -> Iterator[NodeRef]:
    """Yield NodeRef instances for scalar (non-dict/list) values."""
    for ref in iter_nodes(root):
        value = ref.value
        if isinstance(value, (dict, list)):
            continue
        if predicate is None or predicate(value):
            yield ref


def iter_dict_entries(
    root: Any,
    *,
    skip_keys: Iterable[str] | None = None,
) -> Iterator[NodeRef]:
    """Yield NodeRef for values whose parent is a dict (optionally skipping keys)."""
    skip: set[str] = set(skip_keys or ())
    for ref in iter_nodes(root):
        if isinstance(ref.parent, dict):
            if isinstance(ref.key, str) and ref.key in skip:
                continue
            yield ref
