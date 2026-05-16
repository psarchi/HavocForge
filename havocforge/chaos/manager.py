from __future__ import annotations

import random
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple, Type

from havocforge.chaos.drift import get_drift_coordinator
from havocforge.chaos.ops.base import ApplyResult, BaseChaosOp
from havocforge.context import GenContext
from pydantic import BaseModel

STATEFUL_OPS = frozenset({"burst"})


class ChaosManager:
    """Orchestrate chaos operations for request/response pairs.

    Manages op selection (probability-based or forced), budgeting, and execution
    order (drift ops first, then regular ops).
    """

    def __init__(
        self,
        *,
        ctx: GenContext | random.Random | None,
        config_snapshot: BaseModel,
        registry: Dict[str, Type[BaseChaosOp]],
    ) -> None:
        """Initialize chaos manager with context and configuration.

        Args:
            ctx: Generation context with RNG or standalone Random instance
            config_snapshot: Pydantic config model with ops/selection/budgets
            registry: Dict mapping op keys to op classes
        """
        self.ctx = ctx
        self.registry = registry
        self.drift = get_drift_coordinator()
        self.cfg = config_snapshot

        if isinstance(ctx, GenContext):
            self.rng = ctx.rng
        elif isinstance(ctx, random.Random):
            self.rng = ctx
        else:
            self.rng = random.Random()

        self._selection_min_ops = 0
        self._selection_max_ops = 0
        self._candidate_ops: List[Tuple[str, float, float]] = []
        self._op_params_by_name: Dict[str, Dict[str, Any]] = {}
        self._op_instances: Dict[str, BaseChaosOp] = {}  # Cache stateless ops
        self._build_selection_cache()
        self._build_ops_caches()

    def _build_selection_cache(self) -> None:
        selection_cfg = getattr(self.cfg, "selection", None)
        ensure_one = bool(
            getattr(selection_cfg, "ensure_at_least_one_when_any_enabled", False)
        )
        min_ops = getattr(selection_cfg, "min_ops", 0)
        max_ops = getattr(selection_cfg, "max_ops", 0)
        try:
            min_ops_int = int(min_ops)
        except Exception:
            min_ops_int = 0
        try:
            max_ops_int = int(max_ops)
        except Exception:
            max_ops_int = 0

        if ensure_one and min_ops_int < 1:
            min_ops_int = 1

        self._selection_min_ops = min_ops_int
        self._selection_max_ops = max_ops_int

    def _build_ops_caches(self) -> None:
        ops_cfg = getattr(self.cfg, "ops", None)
        if ops_cfg is None:
            return

        candidates: List[Tuple[str, float, float]] = []
        params_by_name: Dict[str, Dict[str, Any]] = {}

        for op_name in self.registry.keys():
            op_cfg = getattr(ops_cfg, op_name, None)
            if not op_cfg:
                continue

            try:
                params_by_name[op_name] = op_cfg.model_dump()
            except Exception:
                continue

            enabled = getattr(op_cfg, "enabled", False)
            probability = getattr(op_cfg, "p", 0)
            if not enabled:
                continue
            try:
                p_value = float(probability)
            except Exception:
                continue
            if p_value <= 0:
                continue

            weight = getattr(op_cfg, "weight", 1.0)
            try:
                weight_value = float(weight)
            except Exception:
                weight_value = 1.0

            candidates.append((op_name, p_value, weight_value))

        self._candidate_ops = candidates
        self._op_params_by_name = params_by_name

        for op_name, params in params_by_name.items():
            if op_name in STATEFUL_OPS:
                continue  # Skip stateful ops
            op_cls = self.registry.get(op_name)
            if op_cls:
                try:
                    self._op_instances[op_name] = op_cls(**dict(params))
                except Exception:
                    pass

    def apply(
        self,
        *,
        body: dict,
        schema_name: str | None = None,
        forced_activation: List[str] | None = None,
    ) -> Tuple[ApplyResult, Dict[str, Any]]:
        """Apply selected chaos ops to response body.

        Args:
            body: Response body dict to modify
            schema_name: Schema name for drift tracking
            forced_activation: Override selection with specific op keys (for testing)

        Returns:
            Tuple of (ApplyResult with final body, dict with headers/status)
        """
        if schema_name:
            self.drift.record_hit(schema_name, "chaos")

        ops_cfg = getattr(self.cfg, "ops", None)
        if ops_cfg is None:
            return ApplyResult(body=body), {}

        activated_ops = self._select_ops(ops_cfg, forced_activation)
        if not activated_ops:
            return ApplyResult(body=body), {}

        drift_ops, regular_ops = self._partition_ops(activated_ops)

        regular_ops = self._apply_budget_limits(regular_ops)

        result, resp_metadata = self._execute_ops(
            drift_ops + regular_ops,
            body,
            schema_name,
            ops_cfg,
        )

        return result, resp_metadata

    def _select_ops(
        self,
        ops_cfg: BaseModel,
        forced_activation: List[str] | None,
    ) -> List[str]:
        """Select which ops to run based on config or forced activation.

        Args:
            ops_cfg: Ops configuration with enabled/p/weight for each op
            forced_activation: Optional list of op keys to force (overrides config)

        Returns:
            List of op keys to execute
        """
        if forced_activation:
            return [k for k in forced_activation if k in self.registry]

        min_ops = self._selection_min_ops
        max_ops = self._selection_max_ops

        if max_ops == 0 or min_ops > max_ops:
            return []

        eligible_ops: List[str] = []
        op_weights: List[float] = []

        for op_name, probability, weight in self._candidate_ops:
            if self.rng.random() < probability:
                eligible_ops.append(op_name)
                op_weights.append(weight)

        if not eligible_ops:
            return []

        total_weight = sum(op_weights)
        if total_weight <= 0:
            return []

        k = self.rng.randint(min_ops, max_ops)
        k = min(k, len(eligible_ops))

        return self.rng.choices(eligible_ops, weights=op_weights, k=k)

    def _partition_ops(self, op_names: List[str]) -> Tuple[List[str], List[str]]:
        """Separate drift ops from regular ops.

        Drift ops contain 'drift' in their key and run first.

        Args:
            op_names: List of op keys to partition

        Returns:
            Tuple of (drift_ops, regular_ops)
        """
        drift_ops: List[str] = []
        regular_ops: List[str] = []

        for name in op_names:
            if "drift" in name:
                drift_ops.append(name)
            else:
                regular_ops.append(name)

        return drift_ops, regular_ops

    def _apply_budget_limits(self, op_names: List[str]) -> List[str]:
        """Apply budget limits to regular ops (drift ops exempt).

        Args:
            op_names: List of regular op keys

        Returns:
            Subset of ops within budget limits
        """
        budgets_cfg = getattr(self.cfg, "budgets", None)
        if not budgets_cfg:
            return op_names

        max_faults = getattr(budgets_cfg, "max_faults_per_request", None)
        if max_faults is None or len(op_names) <= max_faults:
            return op_names

        return self.rng.sample(op_names, k=max_faults)

    def _execute_ops(
        self,
        op_names: List[str],
        body: dict,
        schema_name: str | None,
        ops_cfg: BaseModel,
    ) -> Tuple[ApplyResult, Dict[str, Any]]:
        """Execute ops in sequence, accumulating results.

        Args:
            op_names: Ordered list of op keys to execute
            body: Initial response body
            schema_name: Schema name for response object
            ops_cfg: Ops configuration for parameter extraction

        Returns:
            Tuple of (final ApplyResult, response metadata dict)
        """
        resp_obj = SimpleNamespace(
            body=body,
            headers={"content-type": "application/json"},
            status=200,
            request=None,
            schema_name=schema_name,
        )

        result = ApplyResult(body=body)

        for op_key in op_names:
            op_cls = self.registry.get(op_key)
            if not op_cls:
                continue

            params = self._op_params_by_name.get(op_key)
            if params is None:
                op_cfg = getattr(ops_cfg, op_key, None)
                if not op_cfg:
                    continue
                params = op_cfg.model_dump()

            try:
                # Use cached instance for stateless ops, create new for stateful ops
                if op_key in self._op_instances:
                    op_instance = self._op_instances[op_key]
                else:
                    op_instance = op_cls(**dict(params))

                op_result = op_instance.apply(
                    request=None,
                    response=resp_obj,
                    body=result.body,
                    rng=self.rng,
                )

                result.body = op_result.body

                if op_result.descriptions:
                    if result.descriptions:
                        result.descriptions.extend(op_result.descriptions)
                    else:
                        result.descriptions = op_result.descriptions

                if op_result.status:
                    resp_obj.status = op_result.status
            except Exception as e:
                # Log which operation failed and skip it
                import logging
                logger = logging.getLogger(__name__)
                logger.error(
                    f"chaos_op_failed: operation='{op_key}' error='{type(e).__name__}: {e}' "
                    f"schema='{schema_name or 'unknown'}'"
                )
                # Continue with other operations
                continue

            if op_result.headers_delta:
                for k, v in op_result.headers_delta.items():
                    if v is None:
                        resp_obj.headers.pop(k, None)
                    else:
                        resp_obj.headers[k] = v

        return result, {
            "headers": dict(getattr(resp_obj, "headers", {}) or {}),
            "status": getattr(resp_obj, "status", 200),
        }
