"""Thin LiteLLM wrapper used by every agent in this package.

Why LiteLLM and not provider-specific SDKs:
    - One interface across Anthropic / OpenAI / Gemini / Bedrock / Ollama /
      vLLM / OpenRouter / etc. (See https://docs.litellm.ai/docs/providers.)
    - Tools/functions are normalised to the OpenAI schema regardless of the
      backend, so an agent can swap models without touching its prompts.
    - ``supports_function_calling()`` lets us detect capability and pick a
      pattern (tool-calling vs JSON-mode fallback) per model.

This module exposes a tiny surface — ``complete()`` and ``call_with_tools()`` —
because the agents themselves own the prompts and the validation loops.
Keeping the wrapper thin makes it trivial to swap LiteLLM out later if we
ever want to.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Iterable

import litellm

logger = logging.getLogger(__name__)

# Silence LiteLLM's noisy startup; we'll handle errors ourselves.
litellm.suppress_debug_info = True
os.environ.setdefault("LITELLM_LOG", "WARNING")


@dataclass
class ToolCall:
    """A single tool/function invocation returned by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Completion:
    """Normalised completion result regardless of provider."""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    raw: Any = None  # the original litellm response for debugging


class LLM:
    """Per-agent LLM client. One instance per agent run is fine."""

    def __init__(
        self,
        *,
        model: str,
        api_base: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        timeout: int = 120,
    ) -> None:
        self.model = model
        self.api_base = api_base
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    @property
    def supports_tools(self) -> bool:
        """Whether this model can do native function calling.

        Used by agents to pick between tool-calling and JSON-mode fallback.
        Defaults to True if LiteLLM can't determine — the worst case is a
        runtime error on the first call, which is fine.
        """
        try:
            return litellm.supports_function_calling(self.model)
        except Exception:
            return True

    def _common_kwargs(self) -> dict[str, Any]:
        kw: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
        }
        if self.api_base:
            kw["api_base"] = self.api_base
        if self.api_key:
            kw["api_key"] = self.api_key
        return kw

    def complete(self, messages: list[dict[str, Any]]) -> Completion:
        """Plain text completion. No tools, no JSON enforcement."""
        r = litellm.completion(messages=messages, **self._common_kwargs())
        msg = r.choices[0].message
        return Completion(
            content=msg.content,
            finish_reason=r.choices[0].finish_reason,
            raw=r,
        )

    def call_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str = "auto",
    ) -> Completion:
        """One round of chat with tools available.

        Caller is responsible for the multi-turn loop (append the tool_call
        result and ``call_with_tools`` again until ``finish_reason="stop"``
        or the agent's own terminating tool fires).
        """
        r = litellm.completion(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            **self._common_kwargs(),
        )
        msg = r.choices[0].message

        calls: list[ToolCall] = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError as e:
                logger.warning(
                    "tool_call_args_unparseable", extra={"raw": tc.function.arguments, "err": str(e)}
                )
                args = {}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        return Completion(
            content=msg.content,
            tool_calls=calls,
            finish_reason=r.choices[0].finish_reason,
            raw=r,
        )


def make_tool_result_message(call: ToolCall, result: Any) -> dict[str, Any]:
    """Helper to build the tool-result message the model expects next turn."""
    payload = result if isinstance(result, str) else json.dumps(result, default=str)
    return {
        "role": "tool",
        "tool_call_id": call.id,
        "name": call.name,
        "content": payload,
    }


def assistant_with_tool_calls(calls: Iterable[ToolCall]) -> dict[str, Any]:
    """Helper to echo the assistant's tool_call message back into history."""
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
            }
            for c in calls
        ],
    }
