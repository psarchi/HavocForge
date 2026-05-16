# `agents/` — agentic helpers for Havocforge

Two small agents on top of the engine, both backed by any LLM
[LiteLLM](https://docs.litellm.ai/) supports (Anthropic, OpenAI, Gemini, Bedrock,
Ollama, vLLM, OpenRouter, …):

- **Schema designer** — natural-language → valid Havocforge YAML schema, with
  a validation-and-retry loop against the engine. Single tool, single-shot.
- **Chaos designer** — natural-language → chaos.yaml profile via multi-step
  tool calling. Catalogs all 19 chaos ops in the system prompt; agent picks
  ops + probabilities + budgets, validates against the live op registry,
  emits the YAML.

Both agents follow the [2026 consensus](https://www.buildmvpfast.com/blog/structured-output-llm-json-mode-function-calling-production-guide-2026)
for structured output: use the provider's native tool-calling pattern (rather
than free-form parsing) and feed validation errors back as tool results.

## Install

```bash
pip install litellm    # the one extra dep on top of what havocforge already needs
```

## Quickstart

### Schema designer

```bash
# Default model: ollama_chat/qwen3:8b (set HAVOCFORGE_AGENT_MODEL to change)
python -m agents.cli schema "a user with email, age 18-90, signup date in 2024"
```

Output (stderr is progress, stdout is the YAML):

```yaml
type: object
fields:
  age:
    type: int
    min: 18
    max: 90
  email:
    type: string
    string_type: email
  signup_date:
    type: datetime
    start: '2024-01-01T00:00:00Z'
    end: '2024-12-31T23:59:59Z'
    format: '%Y-%m-%d'
```

The agent runs the schema through `havocforge.schema.builder.build_schema`,
generates a few sample records (`--sample N`), and prints them to stderr for a
sanity check. If validation fails, it retries up to `--max-retries 3` with the
error fed back to the model.

### Chaos designer

```bash
python -m agents.cli chaos "realistic production traffic — occasional latency, very rare full failures, late-arriving events 1% of the time"
```

Output:

```yaml
chaos:
  enabled: true
  ops:
    latency:
      enabled: true
      p: 0.01
      min_ms: 50
      max_ms: 500
    http_error:
      enabled: true
      p: 0.005
      codes: [500, 502, 503]
    late_arrival:
      enabled: true
      p: 0.01
      min_elapsed_seconds: 5
      late_window_seconds: 30
  budgets:
    max_faults_per_request: 1
    max_added_latency_ms: 500
```

## Configuring the model

Resolution order (highest wins):

1. CLI flags: `--model claude-opus-4-7 --api-base ... --temperature 0.2`
2. Env vars: `HAVOCFORGE_AGENT_MODEL`, `HAVOCFORGE_AGENT_API_BASE`,
   `HAVOCFORGE_AGENT_API_KEY`, `HAVOCFORGE_AGENT_TEMPERATURE`
3. `~/.havocforge/agent.toml`:
   ```toml
   [agent]
   model = "claude-haiku-4-5"
   temperature = 0.3
   ```
4. Default: `ollama_chat/qwen3:8b` (assumes Ollama is running on `localhost:11434`)

Cloud-provider API keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.) are read
by LiteLLM directly — you don't need to wire them through `HAVOCFORGE_AGENT_API_KEY`
unless you want a separate one.

### Tested model matrix

| Provider | Model              | Tool calling | Notes                              |
| -------- | ------------------ | ------------ | ---------------------------------- |
| Ollama   | `qwen3:8b`         | ✓            | Default. Local, free, ~7s/turn.   |
| Ollama   | `llama3.1:8b`      | ✓            | Comparable. Slightly worse params. |
| Anthropic | `claude-haiku-4-5` | ✓            | Faster, higher accuracy, paid.    |
| Anthropic | `claude-opus-4-7`  | ✓            | Overkill for these prompts.       |
| OpenAI   | `gpt-4o-mini`      | ✓            | Solid, paid.                       |

Anything LiteLLM lists in [providers](https://docs.litellm.ai/docs/providers)
should work as long as it supports function calling.

## What's where

```
agents/
├── cli.py                    # `python -m agents.cli {schema|chaos} "..."`
├── config.py                 # CLI > env > toml > default resolution
├── providers/
│   └── llm.py                # Thin LiteLLM wrapper (complete + call_with_tools)
├── prompts/
│   ├── schema_designer.md    # System prompt for schema designer
│   └── chaos_designer.md     # System prompt for chaos designer
├── schema/
│   └── designer.py           # Single-tool, validation-loop agent
└── chaos/
    ├── tools.py              # Tool catalog + ChaosProfileBuilder
    └── designer.py           # Multi-step tool-calling agent
```

## Programmatic use

Both agents are importable; the CLI is a thin shell around them.

```python
from agents.config import resolve_llm_config
from agents.providers.llm import LLM
from agents.schema.designer import design_schema

cfg = resolve_llm_config(model="claude-haiku-4-5")
llm = LLM(model=cfg.model, api_base=cfg.api_base, temperature=cfg.temperature)

result = design_schema(
    llm=llm,
    prompt="a customer with id, email, signup date in 2024",
    name="customer",
    sample_count=5,
)
if result.success:
    print(result.yaml_text)
    print(result.sample)
```

## Known limitations

- **8B local models occasionally need a retry.** Smaller models sometimes
  hallucinate field types (`integer` instead of `int`, `text` instead of
  `string`). The validation loop catches these and feeds the corrected error
  back. Bigger / paid models nail it first try.
- **Weights aren't always respected** in the schema designer. If you ask for
  "enum with weights X, Y, Z", 8B models may emit equal weights. Cloud models
  handle it.
- **No streaming output** — the agents wait for the model's full response per
  turn. Fine for the latency budgets we care about (1–15s per agent run on a
  local 8B; 1–3s on a cloud model).
- **Schema agent doesn't (yet) understand `bound_to` / `pool` correlations**
  even though the system prompt mentions them. Cross-schema correlation
  requests work but with mixed results. Improvement target.
