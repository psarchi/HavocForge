"""Single CLI entry for both agents.

    havocforge-agent schema "a user with email, age 18-90, signup in 2024"
    havocforge-agent chaos  "stress test Black Friday checkout"

Overrides:
    --model         provider/model string (LiteLLM format, e.g. claude-opus-4-7,
                    gpt-4o, ollama_chat/qwen3:8b, gemini/gemini-2.0-flash)
    --api-base      custom API base (for self-hosted vLLM, OpenAI-compatible
                    gateways, etc.)
    --temperature   sampling temperature; default 0.2
    --out           write YAML to file; default = stdout
    --name          schema name (schema subcommand only); default = the prompt
                    slug
    --max-turns     chaos: max tool-calling turns (default 8)
    --max-retries   schema: max validation retries (default 3)
    --sample        schema: number of sample records to generate (default 3)
    -v / --verbose  print tool call trace + reasoning
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import yaml

from agents.config import resolve_llm_config
from agents.providers.llm import LLM


def _slugify(text: str, limit: int = 30) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return (s[:limit] or "designed_schema").rstrip("_")


def _write(path: str | None, body: str) -> None:
    if path:
        Path(path).write_text(body, encoding="utf-8")
        print(f"→ wrote {path}", file=sys.stderr)
    else:
        sys.stdout.write(body)
        if not body.endswith("\n"):
            sys.stdout.write("\n")


def cmd_schema(args: argparse.Namespace) -> int:
    from agents.schema.designer import design_schema

    cfg = resolve_llm_config(
        model=args.model,
        api_base=args.api_base,
        temperature=args.temperature,
    )
    llm = LLM(
        model=cfg.model,
        api_base=cfg.api_base,
        api_key=cfg.api_key,
        temperature=cfg.temperature,
    )

    print(f"→ model: {cfg.model}", file=sys.stderr)
    name = args.name or _slugify(args.prompt)

    result = design_schema(
        llm=llm,
        prompt=args.prompt,
        name=name,
        sample_count=args.sample,
        max_retries=args.max_retries,
    )

    if args.verbose:
        for err in result.errors:
            print(f"  · {err}", file=sys.stderr)

    if not result.success:
        print(f"✗ schema design failed after {result.attempts} attempt(s):", file=sys.stderr)
        for err in result.errors:
            print(f"  · {err}", file=sys.stderr)
        return 1

    print(f"✓ valid schema in {result.attempts} attempt(s)", file=sys.stderr)
    _write(args.out, result.yaml_text)
    if args.sample > 0 and result.sample:
        print("# sample records (for sanity-check):", file=sys.stderr)
        for item in result.sample:
            print(f"#   {item}", file=sys.stderr)
    return 0


def cmd_chaos(args: argparse.Namespace) -> int:
    from agents.chaos.designer import design_chaos

    cfg = resolve_llm_config(
        model=args.model,
        api_base=args.api_base,
        temperature=args.temperature,
    )
    llm = LLM(
        model=cfg.model,
        api_base=cfg.api_base,
        api_key=cfg.api_key,
        temperature=cfg.temperature,
    )

    print(f"→ model: {cfg.model}", file=sys.stderr)

    result = design_chaos(
        llm=llm,
        prompt=args.prompt,
        max_turns=args.max_turns,
    )

    if args.verbose:
        for r in result.reasoning:
            print(f"  reasoning: {r[:200]}", file=sys.stderr)
        for name, a in result.tool_calls:
            print(f"  · {name}({a})", file=sys.stderr)

    if not result.success:
        print(f"✗ chaos design failed after {result.turns} turn(s):", file=sys.stderr)
        for err in result.errors:
            print(f"  · {err}", file=sys.stderr)
        return 1

    print(f"✓ valid chaos profile in {result.turns} turn(s) ({len(result.tool_calls)} tool calls)",
          file=sys.stderr)
    _write(args.out, result.yaml_text)
    return 0


def _common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("prompt", help="Natural-language description.")
    p.add_argument("--model", default=None, help="Override the LiteLLM model string.")
    p.add_argument("--api-base", default=None, help="Override the API base URL.")
    p.add_argument("--temperature", type=float, default=None, help="Sampling temperature.")
    p.add_argument("--out", default=None, help="Write YAML to this file (default: stdout).")
    p.add_argument("-v", "--verbose", action="store_true", help="Print trace to stderr.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="havocforge-agent",
        description="Agentic helpers for Havocforge — schema authoring and chaos profile design.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_schema = sub.add_parser("schema", help="Design a Havocforge schema from natural language.")
    _common_args(p_schema)
    p_schema.add_argument("--name", default=None, help="Schema name (default: prompt slug).")
    p_schema.add_argument("--sample", type=int, default=3, help="Sample records to generate.")
    p_schema.add_argument("--max-retries", type=int, default=3, help="Validation retry budget.")
    p_schema.set_defaults(func=cmd_schema)

    p_chaos = sub.add_parser("chaos", help="Design a chaos.yaml profile from natural language.")
    _common_args(p_chaos)
    p_chaos.add_argument("--max-turns", type=int, default=8, help="Max tool-calling turns.")
    p_chaos.set_defaults(func=cmd_chaos)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING if not args.verbose else logging.INFO,
                        format="%(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
