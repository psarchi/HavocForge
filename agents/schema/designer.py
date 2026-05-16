"""Schema designer agent.

Single-tool pattern: the model has one tool, ``emit_schema``, and it must call
it. The agent validates the call via ``havocforge.schema.builder.build_schema``
and (on failure) feeds the error back into a retry round, up to ``max_retries``.

On success the agent also runs a small sample generation so the caller can
eyeball the output without manually wiring up the engine.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agents.providers.llm import LLM, ToolCall, assistant_with_tool_calls, make_tool_result_message

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "schema_designer.md"

EMIT_SCHEMA_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_schema",
        "description": (
            "Emit a Havocforge YAML schema as a structured object. "
            "The agent will validate it and either accept or report errors."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["object"],
                    "description": "Always 'object' at the root of a schema.",
                },
                "fields": {
                    "type": "object",
                    "description": (
                        "Map of field_name → FieldSpec. Each FieldSpec is an object with at least "
                        "a 'type' key; see the system prompt for the allowed types and their parameters."
                    ),
                    "additionalProperties": True,
                },
            },
            "required": ["type", "fields"],
        },
    },
}


@dataclass
class DesignResult:
    schema: dict[str, Any] | None
    yaml_text: str | None
    sample: list[dict] | None
    attempts: int
    errors: list[str] = field(default_factory=list)
    success: bool = False


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _validate_and_sample(name: str, spec: dict[str, Any], sample_count: int) -> tuple[list[dict] | None, str | None]:
    """Run the schema through havocforge's builder. Return (sample, error)."""
    try:
        from havocforge import api as engine_api
        from havocforge.schema.builder import build_schema
        from havocforge.schema.registry import SchemaRegistry
        from havocforge.context import GenContext
    except Exception as e:
        return None, f"engine import failed: {e}"

    try:
        doc = build_schema(name, spec)
    except Exception as e:
        return None, f"build_schema failed: {type(e).__name__}: {e}"

    try:
        SchemaRegistry.register(name, doc)
    except Exception as e:
        # Already-registered is fine; anything else is real
        if "already" not in str(e).lower():
            return None, f"registry register failed: {type(e).__name__}: {e}"

    try:
        gen = engine_api.build(doc.contracts_by_path)
    except Exception as e:
        return None, f"generator build failed: {type(e).__name__}: {e}"

    try:
        ctx = GenContext(seed=42)
        ctx.schema_name = name
        sample = [gen.generate(ctx) for _ in range(sample_count)]
    except Exception as e:
        return None, f"sample generation failed: {type(e).__name__}: {e}"

    return sample, None


def design_schema(
    *,
    llm: LLM,
    prompt: str,
    name: str = "designed_schema",
    sample_count: int = 3,
    max_retries: int = 3,
) -> DesignResult:
    """Run the schema designer agent end-to-end."""
    system = _load_prompt()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    errors: list[str] = []
    schema: dict[str, Any] | None = None
    sample: list[dict] | None = None

    for attempt in range(1, max_retries + 1):
        comp = llm.call_with_tools(messages, tools=[EMIT_SCHEMA_TOOL], tool_choice="auto")

        if not comp.tool_calls:
            err = f"attempt {attempt}: model returned no tool_call (content={comp.content!r:.200})"
            errors.append(err)
            messages.append({
                "role": "user",
                "content": "You did not call the emit_schema tool. You MUST call it. Try again.",
            })
            continue

        call = comp.tool_calls[0]
        schema = call.arguments
        sample, validation_error = _validate_and_sample(name, schema, sample_count)

        if validation_error is None:
            return DesignResult(
                schema=schema,
                yaml_text=yaml.safe_dump(schema, sort_keys=False, default_flow_style=False),
                sample=sample,
                attempts=attempt,
                errors=errors,
                success=True,
            )

        # Validation failed — feed error back and retry
        errors.append(f"attempt {attempt}: {validation_error}")
        messages.append(assistant_with_tool_calls([call]))
        messages.append(make_tool_result_message(call, {
            "ok": False,
            "error": validation_error,
            "instruction": "Fix the issue above and call emit_schema again. Adjust only what's broken.",
        }))

    return DesignResult(
        schema=schema,
        yaml_text=yaml.safe_dump(schema, sort_keys=False) if schema else None,
        sample=None,
        attempts=max_retries,
        errors=errors,
        success=False,
    )
