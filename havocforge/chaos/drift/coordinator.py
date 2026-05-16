from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Callable, Dict, Iterable, List, Optional, Tuple


@dataclass
class DriftLayer:
    """Descriptor for an active drift layer.

    Attributes:
        schema_name: Canonical schema the layer belongs to.
        strategy: Logical drift strategy/operation name (e.g. ``data_drift``).
        index: Strategy-local layer index (1-based when stacking).
        revision: Schema revision identifier produced by SchemaRegistry.
        max_hits: Maximum number of responses that may use this layer.
        hits: Number of responses that have used this layer so far.
        request_quota: Maximum activation approvals before the layer backs off.
        approvals: Number of approvals granted for this layer.
        metadata: Arbitrary payload supplied by the drift op.
        modifications: Free-form notes about schema deltas (for debugging).
    """

    schema_name: str
    strategy: str
    index: int
    revision: str
    max_hits: Optional[int] = None
    hits: int = 0
    request_quota: Optional[int] = None
    approvals: int = 0
    metadata: Dict[str, object] = field(default_factory=dict)
    modifications: List[str] = field(default_factory=list)

    def exhausted(self) -> bool:
        """Return True if the layer reached any configured limits."""
        if self.max_hits is not None and self.hits >= self.max_hits:
            return True
        if self.request_quota is not None and self.approvals >= self.request_quota:
            return True
        return False


@dataclass
class _SchemaDriftState:
    """Mutable drift state for a single schema."""

    schema_name: str
    layering_enabled: bool = True
    layers: List[DriftLayer] = field(default_factory=list)
    current_revision: Optional[str] = None
    cooldown_active: bool = False

    def active_layers(self) -> Tuple[DriftLayer, ...]:
        return tuple(self.layers)

    def iter_strategy_layers(self, strategy: str) -> Iterable[DriftLayer]:
        return (layer for layer in self.layers if layer.strategy == strategy)


class DriftCoordinator:
    """In-memory registry for drift state."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._schemas: Dict[str, _SchemaDriftState] = {}

    def _ensure_state(
        self, schema_name: str, *, layering_enabled: Optional[bool] = None
    ) -> _SchemaDriftState:
        state = self._schemas.get(schema_name)
        if state is None:
            state = _SchemaDriftState(schema_name=schema_name)
            self._schemas[schema_name] = state
        if layering_enabled is not None:
            state.layering_enabled = layering_enabled
        return state

    def _drop_state_if_empty(self, state: _SchemaDriftState) -> None:
        if not state.layers:
            self._schemas.pop(state.schema_name, None)

    def create_and_register_layer(
        self,
        *,
        schema_name: str,
        strategy: str,
        mutation_fn: Callable[[str], Tuple[str, List[str]]],
        layering_enabled: bool = True,
        max_hits: Optional[int] = None,
        request_quota: Optional[int] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> DriftLayer:
        """Create and register a new drift layer with auto-generated revision name.

        Args:
            schema_name: Canonical schema name.
            strategy: Drift strategy/operation name.
            mutation_fn: Callable that takes revision_name and returns (revision, modifications).
            layering_enabled: Whether layering is enabled for this schema.
            max_hits: Maximum number of responses that may use this layer.
            request_quota: Maximum activation approvals before the layer backs off.
            metadata: Arbitrary payload supplied by the drift op.

        Returns:
            The registered DriftLayer descriptor.
        """
        import time

        with self._lock:
            state = self._ensure_state(schema_name, layering_enabled=layering_enabled)
            next_index = sum(1 for _ in state.iter_strategy_layers(strategy)) + 1
            timestamp = int(time.time() * 1000)
            revision_name = f"{schema_name}_{strategy}_{next_index}_{timestamp}"

            revision, modifications = mutation_fn(revision_name)

            layer = DriftLayer(
                schema_name=schema_name,
                strategy=strategy,
                index=next_index,
                revision=revision,
                max_hits=max_hits,
                request_quota=request_quota,
                metadata=dict(metadata or {}),
                modifications=list(modifications or []),
            )
            state.layers.append(layer)
            state.current_revision = revision
            return layer

    def register_layer(
        self,
        *,
        schema_name: str,
        strategy: str,
        revision: str,
        modifications: Optional[List[str]] = None,
        layering_enabled: bool = True,
        max_hits: Optional[int] = None,
        request_quota: Optional[int] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> DriftLayer:
        """Register a new drift layer and return its descriptor."""
        with self._lock:
            state = self._ensure_state(schema_name, layering_enabled=layering_enabled)
            index = sum(1 for _ in state.iter_strategy_layers(strategy)) + 1
            layer = DriftLayer(
                schema_name=schema_name,
                strategy=strategy,
                index=index,
                revision=revision,
                max_hits=max_hits,
                request_quota=request_quota,
                metadata=dict(metadata or {}),
                modifications=list(modifications or []),
            )
            state.layers.append(layer)
            state.current_revision = revision
            return layer

    def remove_layer(self, schema_name: str, strategy: str, index: int) -> None:
        """Remove a specific layer by strategy + index."""
        with self._lock:
            state = self._schemas.get(schema_name)
            if state is None:
                return
            state.layers = [
                layer
                for layer in state.layers
                if not (layer.strategy == strategy and layer.index == index)
            ]
            if state.layers:
                state.current_revision = state.layers[-1].revision
            else:
                state.current_revision = None
                self._drop_state_if_empty(state)

    def clear_schema(self, schema_name: str) -> None:
        """Drop all drift layers for a schema."""
        with self._lock:
            self._schemas.pop(schema_name, None)

    def active_layers(self, schema_name: str) -> Tuple[DriftLayer, ...]:
        """Return active layers for ``schema_name`` in layering order."""
        with self._lock:
            state = self._schemas.get(schema_name)
            return state.active_layers() if state else ()

    def allow_activation(
        self,
        schema_name: str,
        strategy: str,
        *,
        layering_enabled: bool = True,
        max_layers_total: Optional[int] = None,
        max_layers_per_strategy: Optional[int] = None,
    ) -> bool:
        """Check whether a new layer may be activated."""
        with self._lock:
            state = self._schemas.get(schema_name)
            if state is None:
                return True

            if not layering_enabled and any(
                layer.strategy == strategy for layer in state.layers
            ):
                return False

            if max_layers_total is not None and len(state.layers) >= max_layers_total:
                return False

            if max_layers_per_strategy is not None:
                current = sum(1 for layer in state.layers if layer.strategy == strategy)
                if current >= max_layers_per_strategy:
                    return False

            if state.cooldown_active:
                return False

            return True

    def strategy_layer_count(self, schema_name: str, strategy: str) -> int:
        """Return current active layer count for ``(schema_name, strategy)``."""
        with self._lock:
            state = self._schemas.get(schema_name)
            if state is None:
                return 0
            return sum(1 for layer in state.layers if layer.strategy == strategy)

    def record_approval(self, schema_name: str, strategy: str) -> Optional[DriftLayer]:
        """Increment approval counter prior to actual hit (for backoff gates)."""
        with self._lock:
            state = self._schemas.get(schema_name)
            if state is None:
                return None
            matching = [layer for layer in state.layers if layer.strategy == strategy]
            if not matching:
                return None
            layer = matching[-1]
            layer.approvals += 1
            return layer

    def record_hit(self, schema_name: str, strategy: str) -> Optional[DriftLayer]:
        """Increment hit counters for the newest matching layer.

        Returns the layer if it remains active, or ``None`` if it should expire.
        """
        with self._lock:
            state = self._schemas.get(schema_name)
            if state is None:
                return None
            matching = [layer for layer in state.layers if layer.strategy == strategy]
            if not matching:
                return None

            layer = matching[-1]
            layer.hits += 1

            if layer.exhausted():
                state.layers.remove(layer)
                if state.layers:
                    state.current_revision = state.layers[-1].revision
                else:
                    state.current_revision = None
                    self._drop_state_if_empty(state)
                return None

            return layer

    def current_revision(self, schema_name: str) -> Optional[str]:
        """Return the latest schema revision recorded for ``schema_name``."""
        with self._lock:
            state = self._schemas.get(schema_name)
            return state.current_revision if state else None

    def get_state(self, schema_name: str) -> Optional[_SchemaDriftState]:
        """Return the internal state object (read-only; testing/debug)."""
        with self._lock:
            return self._schemas.get(schema_name)
