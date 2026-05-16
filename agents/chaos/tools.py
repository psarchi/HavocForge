"""Tool catalog + in-memory config builder for the chaos designer agent.

Each tool is a small function that mutates ``ChaosProfileBuilder`` state. The
agent's tool-calling loop invokes them in whatever order the LLM picks, and
finally calls ``finalize()`` to emit a validated chaos.yaml fragment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Allowed op names — kept in sync with havocforge.chaos.ops.* registrations.
# We do a runtime check against the live Registry on finalize too, so this is
# a fast-fail / autocomplete-style list rather than the source of truth.
KNOWN_OPS = {
    # body
    "truncate", "schema_field_nulling", "schema_bloat", "duplicate_items",
    "list_shuffle", "late_arrival", "time_skew", "schema_time_skew",
    "encoding_corrupt", "partial_load",
    # status
    "http_error", "http_mismatch", "auth_fault",
    # server / network
    "latency", "burst",
    # header
    "header_anomaly", "random_header_case",
    # drift
    "schema_drift", "data_drift",
}


# ── LiteLLM tool schemas (OpenAI shape) ──────────────────────────────────────

ENABLE_OP_TOOL = {
    "type": "function",
    "function": {
        "name": "enable_op",
        "description": (
            "Enable a chaos operation with a per-request activation probability "
            "and optional per-op parameters. Call this once per op you want to "
            "include in the profile."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": f"One of: {', '.join(sorted(KNOWN_OPS))}",
                },
                "p": {
                    "type": "number",
                    "description": "Activation probability per request. 0.0–1.0; realistic ~0.005–0.20.",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "weight": {
                    "type": "number",
                    "description": "Selection weight relative to other enabled ops. Default 1.0.",
                    "default": 1.0,
                },
                "params": {
                    "type": "object",
                    "description": (
                        "Op-specific parameters (e.g. for latency: min_ms, max_ms; for "
                        "schema_bloat: extra_kb, strategy). See system prompt."
                    ),
                    "additionalProperties": True,
                },
            },
            "required": ["name", "p"],
        },
    },
}

SET_BUDGET_TOOL = {
    "type": "function",
    "function": {
        "name": "set_budget",
        "description": (
            "Cap the aggregate behaviour of enabled ops per request. Both "
            "arguments are optional but at least one must be set."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "max_faults_per_request": {
                    "type": "integer",
                    "description": "Total number of fault-class ops allowed per request.",
                    "minimum": 0,
                },
                "max_added_latency_ms": {
                    "type": "integer",
                    "description": "Sum of artificial latency injected per request, in ms.",
                    "minimum": 0,
                },
            },
        },
    },
}

SET_SELECTION_TOOL = {
    "type": "function",
    "function": {
        "name": "set_selection",
        "description": (
            "Configure the global op selector. Use to force a minimum/maximum "
            "number of ops to fire per request, or to override the default "
            "'one op when none activate' behavior."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "min_ops": {"type": "integer", "minimum": 0},
                "max_ops": {"type": "integer", "minimum": 1},
                "ensure_at_least_one_when_any_enabled": {"type": "boolean"},
            },
        },
    },
}

FINALIZE_TOOL = {
    "type": "function",
    "function": {
        "name": "finalize",
        "description": (
            "Signal that the chaos profile is complete. The agent will validate "
            "the assembled config and return the resulting YAML to the caller."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

ALL_TOOLS = [ENABLE_OP_TOOL, SET_BUDGET_TOOL, SET_SELECTION_TOOL, FINALIZE_TOOL]


# ── In-memory builder ────────────────────────────────────────────────────────


@dataclass
class ChaosProfileBuilder:
    """Accumulates tool-call results into a chaos.yaml-shaped dict."""

    ops: dict[str, dict[str, Any]] = field(default_factory=dict)
    budgets: dict[str, int] = field(default_factory=dict)
    selection: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def enable_op(self, name: str, p: float, weight: float = 1.0, params: dict | None = None) -> dict:
        if name not in KNOWN_OPS:
            return {"ok": False, "error": f"unknown op '{name}'. Valid: {sorted(KNOWN_OPS)}"}
        if not 0.0 <= p <= 1.0:
            return {"ok": False, "error": f"p must be in [0.0, 1.0], got {p}"}
        entry: dict[str, Any] = {"enabled": True, "p": p, "weight": weight}
        if params:
            entry.update(params)
        self.ops[name] = entry
        return {"ok": True, "summary": f"enabled {name} at p={p}, weight={weight}"}

    def set_budget(self, max_faults_per_request: int | None = None, max_added_latency_ms: int | None = None) -> dict:
        if max_faults_per_request is None and max_added_latency_ms is None:
            return {"ok": False, "error": "must set at least one budget"}
        if max_faults_per_request is not None:
            self.budgets["max_faults_per_request"] = max_faults_per_request
        if max_added_latency_ms is not None:
            self.budgets["max_added_latency_ms"] = max_added_latency_ms
        return {"ok": True, "summary": f"budgets={self.budgets}"}

    def set_selection(
        self,
        min_ops: int | None = None,
        max_ops: int | None = None,
        ensure_at_least_one_when_any_enabled: bool | None = None,
    ) -> dict:
        if min_ops is not None:
            self.selection["min_ops"] = min_ops
        if max_ops is not None:
            self.selection["max_ops"] = max_ops
        if ensure_at_least_one_when_any_enabled is not None:
            self.selection["ensure_at_least_one_when_any_enabled"] = ensure_at_least_one_when_any_enabled
        return {"ok": True, "summary": f"selection={self.selection}"}

    def to_chaos_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"enabled": True, "ops": self.ops}
        if self.budgets:
            out["budgets"] = self.budgets
        if self.selection:
            out["selection"] = self.selection
        return out

    def validate_against_registry(self) -> str | None:
        """Verify every enabled op exists in the live havocforge registry."""
        try:
            import havocforge.chaos.ops  # noqa: F401  trigger auto-discovery
            from havocforge.chaos.ops.base import BaseChaosOp
            from havocforge.registry import Registry

            live = set(Registry.get_all(BaseChaosOp).keys())
        except Exception as e:
            return f"could not load live op registry: {e}"

        unknown = set(self.ops.keys()) - live
        if unknown:
            return f"ops not in live registry: {sorted(unknown)}"
        return None
