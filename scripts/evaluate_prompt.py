#!/usr/bin/env python3
"""
evaluate_prompt.py — Run a prompt against a directive via Claude API.

Usage:
  python3 scripts/evaluate_prompt.py \
    --prompt registry/prompts/consensus_protocol_v1_1_0.md \
    --directive registry/evals/strategiai_directive.md \
    --model claude-sonnet-4-6 \
    --output-dir registry/evals/

The --prompt argument accepts either:
  - A .md file (treated as the raw prompt body)
  - A .json file (draft export from sandbox; uses the "body" field)
"""
import argparse
import json
import os
from datetime import date, datetime
from pathlib import Path

# ── Pricing table (USD per million tokens) ─────────────
_PRICING = {
    "claude-sonnet-4-6": {
        "input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75,
    },
    "claude-opus-4-7": {
        "input": 15.00, "output": 75.00, "cache_read": 1.50, "cache_write": 18.75,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80, "output": 4.00, "cache_read": 0.08, "cache_write": 1.00,
    },
}


def build_eval_id(prompt_id: str, version: str, run_date: date, model: str = "") -> str:
    safe_version = version.replace(".", "_")
    safe_model = model.replace(".", "_").replace("-", "_") if model else ""
    base = f"eval_{prompt_id}_v{safe_version}_{run_date.isoformat()}"
    return f"{base}_{safe_model}" if safe_model else base


def estimate_cost(model: str, input_tokens: int, output_tokens: int, cache_read_tokens: int):
    pricing = _PRICING.get(model)
    if pricing is None:
        return None
    cost = (
        input_tokens        / 1_000_000 * pricing["input"]
        + output_tokens     / 1_000_000 * pricing["output"]
        + cache_read_tokens / 1_000_000 * pricing["cache_read"]
    )
    return round(cost, 6)


def format_eval_markdown(data: dict) -> str:
    pt = data["prompt_under_test"]
    prompt_ref = f"{pt['id']}@{pt['version']}"
    tokens = data["tokens"]
    cost = data["cost_usd_estimated"]
    cost_str = f"${cost:.4f}" if cost is not None else "unknown"

    return f"""# Eval — {prompt_ref} · {data['model']} · {data['date']}

**Prompt under test:** {prompt_ref}
**Date:** {data['date']}
**Directive:** {data['directive_file']}
**Model:** {data['model']}
**Eval ID:** {data['id']}

## Response

{data['response']}

## Metadata

| Field | Value |
|---|---|
| Input tokens | {tokens['input']:,} |
| Output tokens | {tokens['output']:,} |
| Cache read tokens | {tokens['cache_read']:,} |
| Total tokens | {tokens['total']:,} |
| Cost estimate | ~{cost_str} |

## Grade

<!-- A / A- / B+ / B / C / F — fill in after review -->

## Notes

<!-- Reviewer notes -->
"""


def load_prompt(path: str) -> tuple:
    """Return (prompt_body, prompt_id, version)."""
    p = Path(path)
    if p.suffix == ".json":
        with open(p) as f:
            draft = json.load(f)
        return draft["body"], draft["id"], draft["version"]
    else:
        body = p.read_text()
        stem = p.stem
        parts = stem.rsplit("_v", 1)
        prompt_id = parts[0] if len(parts) == 2 else stem
        version = parts[1].replace("_", ".") if len(parts) == 2 else "unknown"
        return body, prompt_id, version


def run_eval(prompt_body: str, directive_text: str, model: str) -> dict:
    """Call Claude API and return usage + response text."""
    import anthropic
    client = anthropic.Anthropic()

    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=[
            {
                "type": "text",
                "text": prompt_body,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": directive_text}],
    )

    usage = response.usage
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    input_tokens = usage.input_tokens
    output_tokens = usage.output_tokens

    return {
        "response_text": response.content[0].text,
        "tokens": {
            "input":      input_tokens,
            "output":     output_tokens,
            "cache_read": cache_read,
            "total":      input_tokens + output_tokens,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Run a prompt against a directive via Claude API.")
    parser.add_argument("--prompt",      required=True, help=".md or .json prompt file")
    parser.add_argument("--directive",   default="registry/evals/strategiai_directive.md")
    parser.add_argument("--model",       default="claude-sonnet-4-6")
    parser.add_argument("--output-dir",  default="registry/evals/")
    args = parser.parse_args()

    prompt_body, prompt_id, version = load_prompt(args.prompt)
    directive_text = Path(args.directive).read_text()

    print(f"Running {prompt_id}@{version} against {args.directive} using {args.model}…")
    result = run_eval(prompt_body, directive_text, args.model)

    today = date.today()
    eval_id = build_eval_id(prompt_id, version, today, args.model)
    cost = estimate_cost(args.model, result["tokens"]["input"], result["tokens"]["output"], result["tokens"]["cache_read"])

    eval_data = {
        "id": eval_id,
        "directive_file": args.directive,
        "date": today.isoformat(),
        "prompt_under_test": {"id": prompt_id, "version": version},
        "model": args.model,
        "tokens": result["tokens"],
        "cost_usd_estimated": cost,
        "response": result["response_text"],
        "grade": None,
        "notes": "",
    }

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    md_path   = out_dir / f"{eval_id}.md"
    data_path = out_dir / f"{eval_id}_data.json"

    md_path.write_text(format_eval_markdown(eval_data))
    data_path.write_text(json.dumps(eval_data, indent=2))

    print(f"Written:\n  {md_path}\n  {data_path}")
    if cost is not None:
        print(f"Estimated cost: ${cost:.4f}")


if __name__ == "__main__":
    main()
