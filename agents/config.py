"""Resolution of the model / API config for an agent run.

Precedence (highest wins):
    1. Explicit kwargs passed to ``resolve_llm_config()``  (CLI uses this)
    2. Environment variables                                (CI/scripted runs)
    3. ``~/.havocforge/agent.toml``                         (per-user defaults)
    4. Hardcoded fallback                                   (ollama/qwen3:8b)

The toml format is intentionally tiny:

    [agent]
    model = "claude-haiku-4-5"
    api_base = "https://api.anthropic.com"
    temperature = 0.2
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "ollama_chat/qwen3:8b"
DEFAULT_API_BASE = None  # let LiteLLM/Ollama use their own defaults
DEFAULT_TEMPERATURE = 0.2

CONFIG_PATH = Path.home() / ".havocforge" / "agent.toml"

ENV_MODEL = "HAVOCFORGE_AGENT_MODEL"
ENV_API_BASE = "HAVOCFORGE_AGENT_API_BASE"
ENV_API_KEY = "HAVOCFORGE_AGENT_API_KEY"
ENV_TEMP = "HAVOCFORGE_AGENT_TEMPERATURE"


@dataclass
class AgentConfig:
    model: str
    api_base: str | None
    api_key: str | None
    temperature: float


def _load_toml() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        with CONFIG_PATH.open("rb") as f:
            return tomllib.load(f).get("agent", {})
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def resolve_llm_config(
    *,
    model: str | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
    temperature: float | None = None,
) -> AgentConfig:
    """Compute the final agent config from CLI > env > toml > default."""
    toml_cfg = _load_toml()

    return AgentConfig(
        model=(
            model
            or os.getenv(ENV_MODEL)
            or toml_cfg.get("model")
            or DEFAULT_MODEL
        ),
        api_base=(
            api_base
            or os.getenv(ENV_API_BASE)
            or toml_cfg.get("api_base")
            or DEFAULT_API_BASE
        ),
        api_key=(
            api_key
            or os.getenv(ENV_API_KEY)
            or toml_cfg.get("api_key")
            # Most cloud providers also accept their native env vars (ANTHROPIC_API_KEY,
            # OPENAI_API_KEY, etc.) — LiteLLM picks those up automatically.
        ),
        temperature=(
            temperature
            if temperature is not None
            else (
                float(os.getenv(ENV_TEMP) or 0)
                or toml_cfg.get("temperature")
                or DEFAULT_TEMPERATURE
            )
        ),
    )
