from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Set, Tuple

from havocforge.chaos.drift import get_drift_coordinator
from havocforge.chaos.ops.base import ApplyResult, BaseChaosOp
from havocforge.context import GenContext
from havocforge.contracts.object import ObjectGeneratorSpec

# GeneratorRegistry no longer needed - using unified Registry
from havocforge.schema.builder import _flatten
from havocforge.schema.registry import SchemaRegistry
from havocforge.spec_builder import SpecBuilder
import havocforge.generators  # noqa: F401 - Triggers auto-registration
from havocforge.registry import Registry


@Registry.register(BaseChaosOp)
class SchemaDriftOp(BaseChaosOp):
    """Apply structural drift (add/drop/rename/flatten) to schema definitions."""

    key = "schema_drift"
    layer_kind = "schema_drift"
    phase = "pre"

    def __init__(
        self,
        *,
        enabled: bool = True,
        schema_name: Optional[str] = None,
        layering_enabled: bool = True,
        max_layers_total: Optional[int] = 2,
        max_layers_per_strategy: Optional[int] = 3,
        max_hits: Optional[int] = 10,
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
        cfg_max = self.drift_config.get("max_mutations")
        self.max_mutations = int(max_mutations or cfg_max or 2)
        self.skip_fields: List[str] = list(self.drift_config.get("skip_fields", []))
        mutations_cfg = self.drift_config.get("mutations", {})
        self.mutation_weights = {
            "add_field": float(mutations_cfg.get("add_field", 1.0)),
            "drop_entry": float(mutations_cfg.get("drop_entry", 1.0)),
            "rename_entry": float(mutations_cfg.get("rename_entry", 1.0)),
            "flatten_object": float(mutations_cfg.get("flatten_object", 0.5)),
        }
        templates_cfg = self.drift_config.get("templates", {})
        self.primitives: List[str] = list(
            templates_cfg.get("primitives", ["string", "int", "float", "bool"])
        )
        self.catalog: List[Dict[str, Any]] = list(templates_cfg.get("catalog", []))
        self.maybe_probability = float(templates_cfg.get("maybe_probability", 0.3))
        self._raw_cfg = kwargs

    def _weighted_choice(self, rng: Any) -> str:
        """Select a mutation type based on configured weights."""
        items = list(self.mutation_weights.items())
        choices = [k for k, w in items if w > 0]
        weights = [w for k, w in items if w > 0]
        if not choices:
            return "add_field"
        total = sum(weights)
        if total <= 0:
            return choices[0]
        r = rng.random() * total
        cumulative = 0.0
        for choice, weight in zip(choices, weights):
            cumulative += weight
            if r <= cumulative:
                return choice
        return choices[-1]

    def _generate_word(self, rng: Any) -> str:
        """Generate a realistic word using StringGenerator with string_type=word."""
        builder = SpecBuilder()
        try:
            word_spec = builder.build({"type": "string", "string_type": "word"})
            ctx = GenContext(rng=rng)
            word = word_spec.generate(ctx=ctx)
            return word.lower() if isinstance(word, str) else "field"
        except Exception:
            return "field"

    def _generate_field_name(
        self, existing_keys: Set[str], rng: Any, reference_key: Optional[str] = None
    ) -> str:
        """Generate a unique field name not in existing_keys.

        Args:
            existing_keys: Set of existing field names to avoid
            rng: Random number generator
            reference_key: Optional reference key (e.g., for rename operations)

        Returns:
            A unique field name using word generation and smart patterns
        """
        attempts = 0
        while attempts < 100:
            word = self._generate_word(rng)

            if reference_key and "_" in reference_key:
                if rng.random() < 0.5:
                    parts = reference_key.split("_")
                    chosen_part = rng.choice(parts)
                    name = f"{chosen_part}_{word}"
                else:
                    name = f"{reference_key}_{word}"
            elif reference_key:
                name = f"{reference_key}_{word}"
            else:
                if rng.random() < 0.3:
                    word2 = self._generate_word(rng)
                    name = f"{word}_{word2}"
                else:
                    name = word

            if name not in existing_keys:
                return name
            attempts += 1

        return f"field_{rng.randint(1000, 9999)}"

    def _generate_field_spec(self, rng: Any) -> Dict[str, Any]:
        """Generate a simple field spec using primitives."""
        primitives = ["string", "int", "float", "bool"]
        prim = rng.choice(primitives)

        spec = {"type": prim}
        if prim == "int":
            spec["min"] = 0
            spec["max"] = 100
        elif prim == "float":
            spec["min"] = 0.0
            spec["max"] = 100.0
            spec["precision"] = 2
        elif prim == "string":
            spec["string_type"] = "word"

        if rng.random() < self.maybe_probability:
            spec = {
                "type": "maybe",
                "p_null": round(rng.uniform(0.1, 0.5), 2),
                "child": spec,
            }
        return spec

    def _add_field(self, obj_spec: ObjectGeneratorSpec, rng: Any) -> Optional[str]:
        """Add a new field to an object spec."""
        fields = dict(obj_spec.fields or {})
        existing = set(fields.keys())
        new_name = self._generate_field_name(existing, rng)
        new_spec_dict = self._generate_field_spec(rng)

        builder = SpecBuilder()
        try:
            new_contract = builder.build(new_spec_dict)
        except Exception:
            return None

        fields[new_name] = new_contract
        obj_spec.fields = fields
        return f"added field '{new_name}'"

    def _drop_entry(self, obj_spec: ObjectGeneratorSpec, rng: Any) -> Optional[str]:
        """Drop a field from an object spec."""
        fields = dict(obj_spec.fields or {})
        droppable = [k for k in fields.keys() if k not in self.skip_fields]
        if not droppable or len(droppable) < 2:
            return None
        victim = rng.choice(droppable)
        del fields[victim]
        obj_spec.fields = fields
        return f"dropped field '{victim}'"

    def _rename_entry(self, obj_spec: ObjectGeneratorSpec, rng: Any) -> Optional[str]:
        """Rename a field in an object spec."""
        fields = dict(obj_spec.fields or {})
        renameable = [k for k in fields.keys() if k not in self.skip_fields]
        if not renameable:
            return None
        old_name = rng.choice(renameable)
        existing = set(fields.keys())
        new_name = self._generate_field_name(existing, rng, reference_key=old_name)
        fields[new_name] = fields.pop(old_name)
        obj_spec.fields = fields
        return f"renamed '{old_name}' -> '{new_name}'"

    def _flatten_object(self, obj_spec: ObjectGeneratorSpec, rng: Any) -> Optional[str]:
        """Flatten a nested object by promoting its fields to parent."""
        fields = dict(obj_spec.fields or {})
        nested_objects = [
            (k, v)
            for k, v in fields.items()
            if isinstance(v, ObjectGeneratorSpec) and k not in self.skip_fields
        ]
        if not nested_objects:
            return None

        victim_key, victim_obj = rng.choice(nested_objects)
        child_fields = dict(victim_obj.fields or {})
        existing = set(fields.keys())

        for child_key, child_val in child_fields.items():
            new_key = f"{victim_key}_{child_key}"
            if new_key in existing:
                new_key = self._generate_field_name(existing, rng)
            fields[new_key] = child_val
            existing.add(new_key)

        del fields[victim_key]
        obj_spec.fields = fields
        return f"flattened object '{victim_key}' ({len(child_fields)} fields)"

    def _mutate_object(self, obj_spec: ObjectGeneratorSpec, rng: Any) -> Optional[str]:
        """Apply a single mutation to an object spec."""
        mutation_type = self._weighted_choice(rng)

        if mutation_type == "add_field":
            return self._add_field(obj_spec, rng)
        elif mutation_type == "drop_entry":
            return self._drop_entry(obj_spec, rng)
        elif mutation_type == "rename_entry":
            return self._rename_entry(obj_spec, rng)
        elif mutation_type == "flatten_object":
            return self._flatten_object(obj_spec, rng)
        return None

    def _mutate_schema(
        self,
        schema_name: str,
        revision_name: str,
        rng: Any,
    ) -> Tuple[str, List[str]]:
        """Create a mutated schema revision."""
        latest_name = SchemaRegistry.get_latest_name(schema_name)
        doc = SchemaRegistry.get(latest_name)
        try:
            clone = doc.model_copy(deep=True)
        except AttributeError:
            clone = copy.deepcopy(doc)

        doc = SchemaRegistry.register(revision_name, clone, parent=latest_name)

        candidates = [
            (path, contract)
            for path, contract in doc.contracts_by_path.items()
            if isinstance(contract, ObjectGeneratorSpec)
        ]

        # Flat schemas have no nested ObjectGeneratorSpec in contracts_by_path
        # (root is excluded by _flatten). Fall back to the root tree directly.
        if not candidates and isinstance(doc.contracts_tree, ObjectGeneratorSpec):
            candidates = [("root", doc.contracts_tree)]

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
            result = self._mutate_object(contract, rng)
            if result:
                modifications.append(f"{path}: {result}")
                needs_reflatten = True
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

        existing_layers = coordinator.active_layers(schema_name)
        exhausted_layers = [
            layer
            for layer in existing_layers
            if layer.strategy == self.key and layer.exhausted()
        ]

        if exhausted_layers and not self.layering_enabled:
            for layer in exhausted_layers:
                coordinator.remove_layer(schema_name, self.key, layer.index)

        allowed = coordinator.allow_activation(
            schema_name,
            self.key,
            layering_enabled=self.layering_enabled,
            max_layers_total=self.max_layers_total,
            max_layers_per_strategy=self.max_layers_per_strategy,
        )

        if not allowed:
            return ApplyResult(body=body)

        existing_strategy_layers = [
            layer for layer in existing_layers if layer.strategy == self.key
        ]

        if existing_strategy_layers and not self.layering_enabled:
            active_layer = existing_strategy_layers[-1]
            mutation_count = len(active_layer.modifications or [])

        else:
            try:
                active_layer = coordinator.create_and_register_layer(
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

            mutation_count = len(active_layer.modifications or [])

        return ApplyResult(
            body=body,
            descriptions=[f"{self.key}: {mutation_count} mutations to {schema_name}"],
        )
