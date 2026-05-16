from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Tuple

from havocforge.schema.models import SchemaDoc
from havocforge.schema.errors import SchemaRegistryKeyError, SchemaMutationError


@dataclass
class SchemaEntry:
    """Registry entry storing a schema document and its revision metadata."""

    name: str
    doc: SchemaDoc
    revision: int = 1
    parent: str | None = None

    def clone(self, new_name: str, *, deep: bool = True) -> "SchemaEntry":
        """Return a clone of this entry under ``new_name``."""
        if deep:
            try:
                doc_copy = self.doc.model_copy(deep=True)
            except AttributeError:
                doc_copy = copy.deepcopy(self.doc)
        else:
            doc_copy = self.doc
        return SchemaEntry(name=new_name, doc=doc_copy, revision=1, parent=self.name)


class SchemaRegistry:
    """In-memory registry for schema documents with revision tracking and aliases."""

    _store: Dict[str, SchemaEntry] = {}
    _latest: Dict[str, str] = {}

    # public API
    @classmethod
    def register(
        cls, name: str, sd: SchemaDoc, *, parent: str | None = None
    ) -> SchemaDoc:
        """Register ``sd`` under ``name`` as a new schema (revision = 1)."""
        entry = SchemaEntry(name=name, doc=sd, revision=1, parent=parent)
        cls._store[name] = entry
        cls._update_latest(entry)
        return entry.doc

    @classmethod
    def replace(cls, name: str, sd: SchemaDoc) -> SchemaDoc:
        """Replace ``name`` with ``sd`` and bump its revision."""
        entry = cls._store.get(name)
        if entry is None:
            return cls.register(name, sd)
        entry.doc = sd
        cls._bump_revision(entry)
        return entry.doc

    @classmethod
    def get(cls, name: str) -> SchemaDoc:
        """Return the :class:`SchemaDoc` registered under ``name``."""
        return cls._get_entry(name).doc

    @classmethod
    def get_revision(cls, name: str) -> int:
        """Return the current revision number for ``name``."""
        return cls._get_entry(name).revision

    @classmethod
    def get_parent(cls, name: str) -> str | None:
        """Return the parent schema (if the entry was cloned from another)."""
        return cls._get_entry(name).parent

    @classmethod
    def get_latest_name(cls, name: str) -> str:
        """Return the alias pointing to the highest revision of ``name``'s lineage."""
        root = cls._root_name(name)
        return cls._latest.get(root, root)

    @classmethod
    def get_latest_revision(cls, name: str) -> SchemaDoc:
        """Return the :class:`SchemaDoc` representing the highest revision."""
        return cls.get(cls.get_latest_name(name))

    # mutation API
    @classmethod
    def mutate_contract(
        cls,
        name: str,
        path: str,
        mutator: Callable[[Any], None],
        *,
        revision_name: str | None = None,
        deep_copy: bool = True,
    ) -> SchemaDoc:
        """Apply ``mutator`` to the contract at ``path`` and persist the change.

        Args:
            name (str): Base schema name.
            path (str): Key within ``contracts_by_path`` (e.g., ``"user_id.?"``).
            mutator (Callable[[Any], None]): Callable that mutates the contract in place.
            revision_name (str | None): Optional target revision name (auto-cloned if missing).
            deep_copy (bool): Whether to deep-copy when creating a revision entry.

        Returns:
            SchemaDoc: Updated schema document for the targeted revision.
        """
        entry = cls._target_entry(name, revision_name, deep_copy, auto_clone=True)
        doc = entry.doc
        try:
            contract = doc.contracts_by_path[path]
        except KeyError as exc:
            raise SchemaRegistryKeyError(
                f"path '{path}' not found for schema '{entry.name}'"
            ) from exc

        mutator(contract)
        doc.contracts_by_path[path] = contract
        cls._refresh_entry(entry)
        return entry.doc

    @classmethod
    def set_contract_attr(
        cls,
        name: str,
        path: str,
        attr: str,
        value: Any,
        *,
        revision_name: str | None = None,
        deep_copy: bool = True,
    ) -> SchemaDoc:
        """Set ``contract.<attr> = value`` for the contract at ``path``.

        Returns:
            SchemaDoc: Updated schema document for the targeted revision.
        """
        return cls.mutate_contract(
            name,
            path,
            lambda contract: cls._set_attr(contract, path, attr, value),
            revision_name=revision_name,
            deep_copy=deep_copy,
        )

    @classmethod
    def set_schema_attrs(
        cls,
        name: str,
        changes: Iterable[Dict[str, Any]],
        *,
        revision_name: str | None = None,
        deep_copy: bool = True,
    ) -> SchemaDoc:
        """Apply multiple ``(path, attr, value)`` updates as a single revision bump.

        Args:
            name (str): Base schema name.
            changes (Iterable[dict[str, Any]]): Sequence of change descriptors.
            revision_name (str | None): Optional target revision name.
            deep_copy (bool): Whether to deep-copy when cloning a revision.

        Returns:
            SchemaDoc: Updated schema document for the targeted revision.
        """
        changes = list(changes)
        if not changes:
            return cls.get(revision_name or name)

        entry = cls._target_entry(name, revision_name, deep_copy, auto_clone=True)
        doc = entry.doc
        for change in changes:
            path = change.get("path")
            attr = change.get("attr")
            if path is None or attr is None:
                raise SchemaMutationError("each change must include 'path' and 'attr'")
            value = change.get("value")
            try:
                contract = doc.contracts_by_path[path]
            except KeyError as exc:
                raise SchemaRegistryKeyError(
                    f"path '{path}' not found for schema '{entry.name}'"
                ) from exc
            cls._set_attr(contract, path, attr, value)
            doc.contracts_by_path[path] = contract

        cls._refresh_entry(entry)
        return entry.doc

    # internals
    @classmethod
    def _target_entry(
        cls,
        name: str,
        revision_name: str | None,
        deep_copy: bool,
        *,
        auto_clone: bool = False,
    ) -> SchemaEntry:
        target = revision_name or name
        if revision_name and auto_clone and revision_name not in cls._store:
            target, entry = cls._create_revision_entry(name, revision_name, deep_copy)
            return entry
        return cls._get_entry(target)

    @classmethod
    def _create_revision_entry(
        cls,
        base_name: str,
        revision_name: str,
        deep_copy: bool,
    ) -> Tuple[str, SchemaEntry]:
        base_entry = cls._get_entry(base_name)
        clone_entry = base_entry.clone(revision_name, deep=deep_copy)
        cls._store[revision_name] = clone_entry
        cls._update_latest(clone_entry)
        return revision_name, clone_entry

    @classmethod
    def _refresh_entry(cls, entry: SchemaEntry) -> None:
        from havocforge.schema.builder import (
            _preflight_sample,
            _synthesize_root_spec,
        )

        doc = entry.doc
        doc.engine_spec = _synthesize_root_spec(doc.contracts_by_path)
        preflight, _ = _preflight_sample(entry.name, doc.contracts_by_path, samples=3)
        doc.preflight = preflight
        cls._bump_revision(entry)

    @classmethod
    def _bump_revision(cls, entry: SchemaEntry) -> None:
        entry.revision += 1
        cls._update_latest(entry)

    @classmethod
    def _update_latest(cls, entry: SchemaEntry) -> None:
        root = cls._root_name(entry.name)
        current_name = cls._latest.get(root)
        if current_name is None:
            cls._latest[root] = entry.name
            return
        current_entry = cls._store[current_name]
        if entry.revision >= current_entry.revision:
            cls._latest[root] = entry.name

    @classmethod
    def _root_name(cls, name: str) -> str:
        entry = cls._get_entry(name)
        while entry.parent:
            entry = cls._get_entry(entry.parent)
        return entry.name

    @classmethod
    def _get_entry(cls, name: str) -> SchemaEntry:
        try:
            return cls._store[name]
        except KeyError as exc:
            raise SchemaRegistryKeyError(f"schema '{name}' is not registered") from exc

    @staticmethod
    def _set_attr(contract: Any, path: str, attr: str, value: Any) -> None:
        if not hasattr(contract, attr):
            raise SchemaMutationError(f"contract at '{path}' has no attribute '{attr}'")
        setattr(contract, attr, value)
