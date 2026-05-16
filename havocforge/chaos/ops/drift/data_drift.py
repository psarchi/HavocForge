from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from havocforge.chaos.drift.registry import run_drift
from havocforge.chaos.drift import get_drift_coordinator
from havocforge.chaos.ops.base import ApplyResult, BaseChaosOp
from havocforge.chaos.drift.errors import DriftMutationError
from havocforge.contracts.array import ArrayGeneratorSpec
from havocforge.contracts.maybe import MaybeGeneratorSpec
from havocforge.contracts.object import ObjectGeneratorSpec
from havocforge.contracts.one_of import OneOfGeneratorSpec
from havocforge.contracts.select import SelectGeneratorSpec
from havocforge.schema.builder import _flatten
from havocforge.schema.registry import SchemaRegistry
from havocforge.registry import Registry


@Registry.register(BaseChaosOp)
class DataDriftOp(BaseChaosOp):
    """Apply contract-level drift using registered spec handlers."""

    key = "data_drift"
    layer_kind = "data_drift"
    phase = "pre"

    def __init__(
        self,
        *,
        enabled: bool = True,
        schema_name: Optional[str] = None,
        layering_enabled: bool = True,
        max_layers_total: Optional[int] = 2,
        max_layers_per_strategy: Optional[int] = 3,
        max_hits: Optional[int] = None,
        request_quota: Optional[int] = 10,
        max_mutations: Optional[int] = None,
        config: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(enabled=enabled)
        self.schema_name = schema_name
        self.layering_enabled = bool(layering_enabled)
        self.max_layers_total = max_layers_total
        self.max_layers_per_strategy = max_layers_per_strategy
        self.max_hits = max_hits
        self.request_quota = request_quota
        self.drift_config: Dict[str, Any] = dict(config or {})

        raw_config = self.drift_config.get("value", self.drift_config)
        self.spec_config: Dict[str, Any] = raw_config.get("specs", {})
        if isinstance(self.spec_config, dict) and "value" in self.spec_config:
            self.spec_config = self.spec_config["value"]

        self.default_spec_config: Dict[str, Any] = raw_config.get("default", {})
        if (
            isinstance(self.default_spec_config, dict)
            and "value" in self.default_spec_config
        ):
            self.default_spec_config = self.default_spec_config["value"] or {}

        cfg_max = raw_config.get("max_mutations")
        self.max_mutations = int(max_mutations or cfg_max or 3)
        self._raw_cfg = kwargs

    @staticmethod
    def _parse_path(path: str) -> List[str]:
        if not path:
            return []
        segments: List[str] = []
        buffer = ""
        i = 0
        while i < len(path):
            ch = path[i]
            if ch == ".":
                next_char = path[i + 1] if i + 1 < len(path) else ""
                if next_char == "?":
                    if buffer:
                        segments.append(buffer)
                        buffer = ""
                    segments.append("?")
                    i += 2
                    continue
                if buffer:
                    segments.append(buffer)
                    buffer = ""
                i += 1
                continue
            if ch == "[" and path[i : i + 2] == "[]":
                if buffer:
                    segments.append(buffer)
                    buffer = ""
                segments.append("[]")
                i += 2
                continue
            if ch == "|":
                if buffer:
                    segments.append(buffer)
                    buffer = ""
                j = i + 1
                while j < len(path) and path[j].isdigit():
                    j += 1
                segments.append(f"|{path[i + 1 : j]}")
                i = j
                continue
            buffer += ch
            i += 1
        if buffer:
            segments.append(buffer)
        return segments

    @staticmethod
    def _descend(node: Any, segment: str) -> Optional[Any]:
        if isinstance(node, ObjectGeneratorSpec):
            fields = node.fields or {}
            return fields.get(segment)
        if isinstance(node, SelectGeneratorSpec):
            options = node.options or {}
            return options.get(segment)
        if isinstance(node, ArrayGeneratorSpec):
            if segment == "[]":
                return node.child
            return None
        if isinstance(node, MaybeGeneratorSpec):
            if segment == "?":
                return node.child
            return None
        if isinstance(node, OneOfGeneratorSpec):
            if segment.startswith("|"):
                try:
                    idx = int(segment[1:])
                except ValueError:
                    return None
                choices = node.choices or []
                if 0 <= idx < len(choices):
                    return choices[idx]
            return None
        return None

    @staticmethod
    def _assign(node: Any, segment: str, replacement: Any) -> None:
        if isinstance(node, ObjectGeneratorSpec):
            fields = dict(node.fields or {})
            fields[segment] = replacement
            node.fields = fields
            return
        if isinstance(node, SelectGeneratorSpec):
            options = dict(node.options or {})
            options[segment] = replacement
            node.options = options
            return
        if isinstance(node, ArrayGeneratorSpec):
            if segment != "[]":
                raise DriftMutationError(
                    f"array child segment expected '[]', got {segment!r}"
                )
            node.child = replacement
            return
        if isinstance(node, MaybeGeneratorSpec):
            if segment != "?":
                raise DriftMutationError(
                    f"maybe child segment expected '?', got {segment!r}"
                )
            node.child = replacement
            return
        if isinstance(node, OneOfGeneratorSpec):
            if not segment.startswith("|"):
                raise DriftMutationError(
                    f"one_of choice segment expected '|idx', got {segment!r}"
                )
            idx = int(segment[1:])
            choices = list(node.choices or [])
            while len(choices) <= idx:
                choices.append(None)
            choices[idx] = replacement
            node.choices = choices
            return
        raise DriftMutationError(
            f"Unsupported parent spec {type(node).__name__} for replacement"
        )

    def _apply_replacement(self, doc: Any, path: str, replacement: Any) -> None:
        segments = self._parse_path(path)
        if not segments:
            doc.contracts_tree = replacement
            doc.contracts_by_path[path] = replacement
            return
        parent = doc.contracts_tree
        for segment in segments[:-1]:
            parent = self._descend(parent, segment)
            if parent is None:
                return
        target_segment = segments[-1]
        if parent is None:
            return
        self._assign(parent, target_segment, replacement)
        doc.contracts_by_path[path] = replacement

    @staticmethod
    def _unwrap_config(cfg: Any) -> Any:
        """Recursively unwrap 'value' wrappers from config dict."""
        if not isinstance(cfg, dict):
            return cfg
        if "value" in cfg and len(cfg) == 1:
            return DataDriftOp._unwrap_config(cfg["value"])
        return {k: DataDriftOp._unwrap_config(v) for k, v in cfg.items()}

    def _spec_config_for(self, spec_obj: Any) -> Dict[str, Any]:
        cfg: Dict[str, Any] = dict(self.default_spec_config)
        spec_type = getattr(spec_obj, "type_token", None)
        class_name = type(spec_obj).__name__

        if isinstance(spec_type, str):
            specific = self.spec_config.get(spec_type) or self.spec_config.get(
                spec_type.lower()
            )
            if isinstance(specific, dict):
                specific = self._unwrap_config(specific)
                cfg.update(specific)

        specific = self.spec_config.get(class_name)
        if isinstance(specific, dict):
            specific = self._unwrap_config(specific)
            cfg.update(specific)

        if (
            isinstance(spec_obj, MaybeGeneratorSpec)
            and getattr(spec_obj, "child", None) is not None
        ):
            child_cfg = self._spec_config_for(spec_obj.child)
            if child_cfg:
                cfg = dict(cfg)
                cfg.setdefault("child", child_cfg)

        return cfg

    def _mutate_schema(
        self,
        schema_name: str,
        revision_name: str,
        rng: Any,
    ) -> Tuple[str, List[str]]:
        latest_name = SchemaRegistry.get_latest_name(schema_name)
        doc = SchemaRegistry.get(latest_name)
        try:
            clone = doc.model_copy(deep=True)
        except AttributeError:
            clone = copy.deepcopy(doc)

        doc = SchemaRegistry.register(revision_name, clone, parent=latest_name)
        candidates = list(doc.contracts_by_path.items())
        if hasattr(rng, "shuffle"):
            rng.shuffle(candidates)
        else:
            import random

            random.shuffle(candidates)

        modifications: List[str] = []
        needs_reflatten = False
        remaining = max(1, int(self.max_mutations))
        for path, contract in candidates:
            if remaining <= 0:
                break
            spec_cfg = self._spec_config_for(contract)
            result = run_drift(
                "data", contract, rng, remaining, config=spec_cfg or None
            )
            if result:
                if result.summary:
                    modifications.append(f"{path}: {result.summary}")
                    remaining -= 1
                if result.replacement is not None:
                    self._apply_replacement(doc, path, result.replacement)
                    needs_reflatten = True
                    if not result.summary:
                        modifications.append(f"{path}: <replaced>")
                        remaining -= 1

        if needs_reflatten:
            doc.contracts_by_path = _flatten(doc.contracts_tree)

        if modifications:
            SchemaRegistry.replace(revision_name, doc)

        return revision_name, modifications

    def apply(
        self,
        *,
        request: Any,
        response: Any,
        body: Any,
        rng: Any,
    ) -> ApplyResult:
        if not self.enabled:
            return ApplyResult(body=body)

        schema_name = self.schema_name or getattr(response, "schema_name", None)
        if not schema_name:
            return ApplyResult(body=body)

        coordinator = get_drift_coordinator()

        try:
            coordinator.create_and_register_layer(
                schema_name=schema_name,
                strategy=self.key,
                mutation_fn=lambda rev_name: self._mutate_schema(
                    schema_name, rev_name, rng=rng
                ),
                layering_enabled=self.layering_enabled,
                max_hits=self.max_hits,
                request_quota=self.request_quota,
                metadata={"placeholder": True},
            )
        except Exception:
            return ApplyResult(body=body)

        return ApplyResult(
            body=body,
            descriptions=[f"{self.key} drift stub applied to {schema_name}"],
        )
