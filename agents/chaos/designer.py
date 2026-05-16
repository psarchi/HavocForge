"""Chaos designer agent — multi-step tool calling.

Loop:
    1. Send system prompt + user prompt + ALL_TOOLS.
    2. Model emits some combination of {enable_op, set_budget, set_selection}.
       Possibly also free-form reasoning in the content field — we keep it
       in history (it improves subsequent turns).
    3. Apply each tool call to the in-memory builder, return result.
    4. Loop until the model calls ``finalize()`` or we hit ``max_turns``.
    5. Validate against the live op registry, emit YAML.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agents.chaos.tools import ALL_TOOLS, ChaosProfileBuilder
from agents.providers.llm import LLM, ToolCall, assistant_with_tool_calls, make_tool_result_message

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "chaos_designer.md"


@dataclass
class ChaosDesignResult:
    profile: dict[str, Any] | None
    yaml_text: str | None
    turns: int
    reasoning: list[str] = field(default_factory=list)
    tool_calls: list[tuple[str, dict]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    success: bool = False


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _dispatch(builder: ChaosProfileBuilder, call: ToolCall) -> tuple[dict[str, Any], bool]:
    """Apply one tool call. Returns (result_payload, is_finalize)."""
    if call.name == "enable_op":
        return builder.enable_op(**call.arguments), False
    if call.name == "set_budget":
        return builder.set_budget(**call.arguments), False
    if call.name == "set_selection":
        return builder.set_selection(**call.arguments), False
    if call.name == "finalize":
        return {"ok": True, "summary": "finalize received — agent will validate now"}, True
    return {"ok": False, "error": f"unknown tool '{call.name}'"}, False


def design_chaos(
    *,
    llm: LLM,
    prompt: str,
    max_turns: int = 8,
) -> ChaosDesignResult:
    builder = ChaosProfileBuilder()
    system = _load_prompt()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    reasoning: list[str] = []
    tool_log: list[tuple[str, dict]] = []
    errors: list[str] = []

    for turn in range(1, max_turns + 1):
        comp = llm.call_with_tools(messages, tools=ALL_TOOLS, tool_choice="auto")

        if comp.content:
            reasoning.append(comp.content)

        if not comp.tool_calls:
            # Model wrote prose but didn't call tools — nudge it
            errors.append(f"turn {turn}: no tool call (content: {comp.content!r:.150})")
            messages.append({
                "role": "user",
                "content": (
                    "You must call tools to build the profile. Available: enable_op, "
                    "set_budget, set_selection, finalize. Call them now."
                ),
            })
            continue

        # Echo assistant's tool_calls into history, then append each tool result
        messages.append(assistant_with_tool_calls(comp.tool_calls))

        finalized = False
        for call in comp.tool_calls:
            result, is_finalize = _dispatch(builder, call)
            tool_log.append((call.name, call.arguments))
            messages.append(make_tool_result_message(call, result))
            if is_finalize:
                finalized = True

        if finalized:
            if not builder.ops:
                errors.append("finalize called but no ops enabled")
                messages.append({
                    "role": "user",
                    "content": (
                        "You called finalize but no ops are enabled. Enable at least one "
                        "op via enable_op, then finalize again."
                    ),
                })
                continue

            registry_err = builder.validate_against_registry()
            if registry_err:
                errors.append(f"registry validation: {registry_err}")
                messages.append({
                    "role": "user",
                    "content": (
                        f"Profile rejected: {registry_err}. Remove the unknown op(s) "
                        "and call finalize again."
                    ),
                })
                continue

            profile = builder.to_chaos_dict()
            return ChaosDesignResult(
                profile=profile,
                yaml_text=yaml.safe_dump({"chaos": profile}, sort_keys=False, default_flow_style=False),
                turns=turn,
                reasoning=reasoning,
                tool_calls=tool_log,
                errors=errors,
                success=True,
            )

    return ChaosDesignResult(
        profile=builder.to_chaos_dict() if builder.ops else None,
        yaml_text=None,
        turns=max_turns,
        reasoning=reasoning,
        tool_calls=tool_log,
        errors=errors + [f"hit max_turns ({max_turns}) without finalize"],
        success=False,
    )
