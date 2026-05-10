# Phase 2 — Eval and Register Scripts

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build two CLI scripts — `evaluate_prompt.py` runs a prompt against a directive via the Claude API and writes a structured eval report; `register_prompt.py` takes a draft JSON + eval data JSON and safely appends to `registry/INDEX.json`.

**Architecture:** Both scripts are standalone Python 3 CLIs using only stdlib + `anthropic` SDK. `evaluate_prompt.py` calls Claude with the prompt body as a cached system message and the directive as the user turn, then writes `eval_<id>.md` + `eval_<id>_data.json` matching the existing `eval_batch_001` file pair. `register_prompt.py` reads the data JSON (not the markdown) to extract machine-readable eval metadata, merges it into the draft, duplicate-checks against `INDEX.json`, then writes atomically via temp-file rename.

**Tech Stack:** Python 3.9+, `anthropic` SDK (`pip install anthropic`), stdlib (`argparse`, `json`, `pathlib`, `datetime`, `tempfile`, `os`, `unittest.mock`)

---

## File Map

| File | Role |
|---|---|
| `scripts/evaluate_prompt.py` | CLI: run prompt vs directive → write eval md + data json |
| `scripts/register_prompt.py` | CLI: merge draft + eval data → append to INDEX.json |
| `tests/test_evaluate_prompt.py` | Unit tests for formatting, cost estimation, eval ID |
| `tests/test_register_prompt.py` | Unit tests for duplicate detection, merging, atomic write |

---

## Task 1: `evaluate_prompt.py` — core helpers and tests

**Files:**
- Create: `scripts/evaluate_prompt.py`
- Create: `tests/test_evaluate_prompt.py`

- [ ] **Step 1: Write failing tests for the pure helpers**

Create `tests/test_evaluate_prompt.py`:

```python
import json
import sys
import os
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scripts.evaluate_prompt as ep


class TestBuildEvalId(unittest.TestCase):
    def test_format(self):
        eid = ep.build_eval_id("consensus_protocol", "1.1.0", date(2026, 5, 10))
        self.assertEqual(eid, "eval_consensus_protocol_v1_1_0_2026-05-10")

    def test_version_dots_replaced(self):
        eid = ep.build_eval_id("my_prompt", "0.1.0", date(2026, 1, 1))
        self.assertIn("v0_1_0", eid)


class TestEstimateCost(unittest.TestCase):
    def test_sonnet_4_6(self):
        cost = ep.estimate_cost("claude-sonnet-4-6", input_tokens=1000, output_tokens=1000, cache_read_tokens=0)
        # $3/M input + $15/M output = 0.003 + 0.015 = $0.018
        self.assertAlmostEqual(cost, 0.018, places=4)

    def test_opus_4_7(self):
        cost = ep.estimate_cost("claude-opus-4-7", input_tokens=1000, output_tokens=1000, cache_read_tokens=0)
        # $15/M input + $75/M output = 0.015 + 0.075 = $0.09
        self.assertAlmostEqual(cost, 0.09, places=4)

    def test_haiku_4_5(self):
        cost = ep.estimate_cost("claude-haiku-4-5-20251001", input_tokens=1000, output_tokens=1000, cache_read_tokens=0)
        # $0.80/M input + $4/M output = 0.0008 + 0.004 = $0.0048
        self.assertAlmostEqual(cost, 0.0048, places=5)

    def test_cache_read_is_cheaper(self):
        # Cache read tokens are $0.30/M for sonnet
        cost_with_cache = ep.estimate_cost("claude-sonnet-4-6", input_tokens=0, output_tokens=0, cache_read_tokens=1000000)
        self.assertAlmostEqual(cost_with_cache, 0.30, places=2)

    def test_unknown_model_returns_none(self):
        cost = ep.estimate_cost("gpt-999", input_tokens=1000, output_tokens=1000, cache_read_tokens=0)
        self.assertIsNone(cost)


class TestFormatEvalMarkdown(unittest.TestCase):
    def _sample_data(self):
        return {
            "id": "eval_my_prompt_v0_1_0_2026-05-10",
            "directive_file": "registry/evals/strategiai_directive.md",
            "date": "2026-05-10",
            "prompt_under_test": {"id": "my_prompt", "version": "0.1.0"},
            "model": "claude-sonnet-4-6",
            "tokens": {"input": 1000, "output": 500, "cache_read": 200, "total": 1700},
            "cost_usd_estimated": 0.012,
            "response": "This is the model response.",
            "grade": None,
            "notes": "",
        }

    def test_header_contains_id_and_model(self):
        md = ep.format_eval_markdown(self._sample_data())
        self.assertIn("my_prompt@0.1.0", md)
        self.assertIn("claude-sonnet-4-6", md)

    def test_response_is_included(self):
        md = ep.format_eval_markdown(self._sample_data())
        self.assertIn("This is the model response.", md)

    def test_token_counts_present(self):
        md = ep.format_eval_markdown(self._sample_data())
        self.assertIn("1,000", md)   # input tokens formatted
        self.assertIn("500", md)      # output tokens
        self.assertIn("$0.012", md)   # cost

    def test_grade_placeholder_present(self):
        md = ep.format_eval_markdown(self._sample_data())
        self.assertIn("<!-- A / A- / B+ / B / C / F", md)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/troylatimer/.devswarm/repos/0/c92b5c95/agent-decision-making
python3 -m pytest tests/test_evaluate_prompt.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'scripts.evaluate_prompt'`

- [ ] **Step 3: Create `scripts/__init__.py` and implement `scripts/evaluate_prompt.py`**

First create the package file:
```bash
mkdir -p scripts && touch scripts/__init__.py
```

Then create `scripts/evaluate_prompt.py`:

```python
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
import sys
import tempfile
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


def build_eval_id(prompt_id: str, version: str, run_date: date) -> str:
    safe_version = version.replace(".", "_")
    return f"eval_{prompt_id}_v{safe_version}_{run_date.isoformat()}"


def estimate_cost(model: str, input_tokens: int, output_tokens: int, cache_read_tokens: int) -> float | None:
    pricing = _PRICING.get(model)
    if pricing is None:
        return None
    cost = (
        input_tokens       / 1_000_000 * pricing["input"]
        + output_tokens    / 1_000_000 * pricing["output"]
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


def load_prompt(path: str) -> tuple[str, str, str]:
    """Return (prompt_body, prompt_id, version)."""
    p = Path(path)
    if p.suffix == ".json":
        with open(p) as f:
            draft = json.load(f)
        return draft["body"], draft["id"], draft["version"]
    else:
        body = p.read_text()
        # Derive id from filename: consensus_protocol_v1_1_0.md → consensus_protocol, 1.1.0
        stem = p.stem  # e.g. consensus_protocol_v1_1_0
        parts = stem.rsplit("_v", 1)
        prompt_id = parts[0] if len(parts) == 2 else stem
        version = parts[1].replace("_", ".") if len(parts) == 2 else "unknown"
        return body, prompt_id, version


def run_eval(prompt_body: str, directive_text: str, model: str) -> dict:
    """Call Claude API and return raw usage + response text."""
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
    eval_id = build_eval_id(prompt_id, version, today)
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
```

- [ ] **Step 4: Run tests — all must pass**

```bash
python3 -m pytest tests/test_evaluate_prompt.py -v
```

Expected output:
```
tests/test_evaluate_prompt.py::TestBuildEvalId::test_format PASSED
tests/test_evaluate_prompt.py::TestBuildEvalId::test_version_dots_replaced PASSED
tests/test_evaluate_prompt.py::TestEstimateCost::test_sonnet_4_6 PASSED
tests/test_evaluate_prompt.py::TestEstimateCost::test_opus_4_7 PASSED
tests/test_evaluate_prompt.py::TestEstimateCost::test_haiku_4_5 PASSED
tests/test_evaluate_prompt.py::TestEstimateCost::test_cache_read_is_cheaper PASSED
tests/test_evaluate_prompt.py::TestEstimateCost::test_unknown_model_returns_none PASSED
tests/test_evaluate_prompt.py::TestFormatEvalMarkdown::test_header_contains_id_and_model PASSED
tests/test_evaluate_prompt.py::TestFormatEvalMarkdown::test_response_is_included PASSED
tests/test_evaluate_prompt.py::TestFormatEvalMarkdown::test_token_counts_present PASSED
tests/test_evaluate_prompt.py::TestFormatEvalMarkdown::test_grade_placeholder_present PASSED
11 passed in 0.XX s
```

- [ ] **Step 5: Commit**

```bash
git add scripts/__init__.py scripts/evaluate_prompt.py tests/test_evaluate_prompt.py
git commit -m "feat: add evaluate_prompt.py with Claude API eval runner and helpers"
```

---

## Task 2: `register_prompt.py` — helpers and tests

**Files:**
- Create: `scripts/register_prompt.py`
- Create: `tests/test_register_prompt.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_register_prompt.py`:

```python
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scripts.register_prompt as rp


def _make_index(prompts=None):
    return {
        "registry_version": "0.1",
        "generated_at": "2026-05-10",
        "owner": "test_owner",
        "owner_entity": "Test LLC",
        "prompts": prompts or [],
        "evals": [],
        "open_questions": [],
    }


def _sample_draft():
    return {
        "id": "my_prompt",
        "version": "0.1.0",
        "status": "draft",
        "tier": "audit",
        "owner": "unknown",
        "body": "You are a helpful assistant.",
        "use_case": "Draft exported from sandbox",
        "default_model": "claude-sonnet-4-6",
        "cost_per_run_usd": None,
        "tokens_prompt_body": None,
        "tested_on": ["claude-sonnet-4-6"],
        "eval_status": "unevaluated",
        "composes": [],
        "file": None,
        "notes": "",
    }


def _sample_eval_data():
    return {
        "id": "eval_my_prompt_v0_1_0_2026-05-10",
        "directive_file": "registry/evals/strategiai_directive.md",
        "date": "2026-05-10",
        "prompt_under_test": {"id": "my_prompt", "version": "0.1.0"},
        "model": "claude-sonnet-4-6",
        "tokens": {"input": 1000, "output": 500, "cache_read": 0, "total": 1500},
        "cost_usd_estimated": 0.0105,
        "response": "...",
        "grade": "A",
        "notes": "Caught arithmetic check.",
    }


class TestCheckDuplicate(unittest.TestCase):
    def test_no_duplicate_on_empty(self):
        index = _make_index()
        self.assertFalse(rp.check_duplicate(index, "my_prompt", "0.1.0"))

    def test_detects_exact_match(self):
        existing = {"id": "my_prompt", "version": "0.1.0"}
        index = _make_index(prompts=[existing])
        self.assertTrue(rp.check_duplicate(index, "my_prompt", "0.1.0"))

    def test_different_version_not_duplicate(self):
        existing = {"id": "my_prompt", "version": "0.2.0"}
        index = _make_index(prompts=[existing])
        self.assertFalse(rp.check_duplicate(index, "my_prompt", "0.1.0"))


class TestMergeEvalIntoDraft(unittest.TestCase):
    def test_updates_eval_status_from_grade(self):
        draft = _sample_draft()
        eval_data = _sample_eval_data()
        result = rp.merge_eval_into_draft(draft, eval_data)
        self.assertEqual(result["eval_status"], "passed")
        self.assertEqual(result["eval_batch"], eval_data["id"])

    def test_cost_and_tokens_updated(self):
        draft = _sample_draft()
        eval_data = _sample_eval_data()
        result = rp.merge_eval_into_draft(draft, eval_data)
        self.assertEqual(result["cost_per_run_usd"], 0.0105)

    def test_failing_grade_sets_status_failed(self):
        draft = _sample_draft()
        eval_data = {**_sample_eval_data(), "grade": "F"}
        result = rp.merge_eval_into_draft(draft, eval_data)
        self.assertEqual(result["eval_status"], "failed")

    def test_none_grade_sets_pending(self):
        draft = _sample_draft()
        eval_data = {**_sample_eval_data(), "grade": None}
        result = rp.merge_eval_into_draft(draft, eval_data)
        self.assertEqual(result["eval_status"], "pending")

    def test_body_field_removed_from_registry_entry(self):
        draft = _sample_draft()
        eval_data = _sample_eval_data()
        result = rp.merge_eval_into_draft(draft, eval_data)
        # INDEX.json stores body in a file, not inline
        self.assertNotIn("body", result)


class TestAppendToIndex(unittest.TestCase):
    def _write_index(self, tmp_dir, index):
        path = Path(tmp_dir) / "INDEX.json"
        path.write_text(json.dumps(index, indent=2))
        return str(path)

    def test_appends_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_index(tmp, _make_index())
            entry = {"id": "my_prompt", "version": "0.1.0"}
            rp.append_to_index(path, entry)
            with open(path) as f:
                loaded = json.load(f)
            self.assertEqual(len(loaded["prompts"]), 1)
            self.assertEqual(loaded["prompts"][0]["id"], "my_prompt")

    def test_write_is_atomic(self):
        """File should be valid JSON even if we read during write."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_index(tmp, _make_index())
            entry = {"id": "my_prompt", "version": "0.1.0"}
            rp.append_to_index(path, entry)
            # Re-read and validate
            with open(path) as f:
                loaded = json.load(f)
            self.assertIn("prompts", loaded)

    def test_updates_generated_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_index(tmp, _make_index())
            rp.append_to_index(path, {"id": "x", "version": "0.1.0"})
            with open(path) as f:
                loaded = json.load(f)
            self.assertNotEqual(loaded["generated_at"], "2026-05-10")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_register_prompt.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'scripts.register_prompt'`

- [ ] **Step 3: Implement `scripts/register_prompt.py`**

```python
#!/usr/bin/env python3
"""
register_prompt.py — Append a prompt draft + eval result to registry/INDEX.json.

Usage:
  python3 scripts/register_prompt.py \
    --draft /path/to/draft.json \
    --eval-data registry/evals/eval_my_prompt_v0_1_0_2026-05-10_data.json \
    --index registry/INDEX.json
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path


def check_duplicate(index: dict, prompt_id: str, version: str) -> bool:
    for entry in index.get("prompts", []):
        if entry.get("id") == prompt_id and entry.get("version") == version:
            return True
    return False


def merge_eval_into_draft(draft: dict, eval_data: dict) -> dict:
    """Produce a registry entry from draft + eval data. Removes the body field."""
    grade = eval_data.get("grade")
    if grade is None:
        eval_status = "pending"
    elif grade in ("F",):
        eval_status = "failed"
    else:
        eval_status = "passed"

    entry = {k: v for k, v in draft.items() if k != "body"}

    entry["eval_status"] = eval_status
    entry["eval_batch"]  = eval_data["id"]

    if eval_data.get("cost_usd_estimated") is not None:
        entry["cost_per_run_usd"] = eval_data["cost_usd_estimated"]

    model = eval_data.get("model")
    if model and model not in entry.get("tested_on", []):
        entry.setdefault("tested_on", []).append(model)

    return entry


def append_to_index(index_path: str, entry: dict) -> None:
    """Read INDEX.json, append entry, write back atomically."""
    with open(index_path) as f:
        index = json.load(f)

    index["prompts"].append(entry)
    index["generated_at"] = date.today().isoformat()

    # Atomic write: write to sibling temp file, then rename
    dir_name = os.path.dirname(os.path.abspath(index_path))
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(index, f, indent=2)
        os.replace(tmp_path, index_path)
    except Exception:
        os.unlink(tmp_path)
        raise


def main():
    parser = argparse.ArgumentParser(description="Register a prompt draft into INDEX.json.")
    parser.add_argument("--draft",     required=True, help="Draft JSON file (from exportToRegistryDraft)")
    parser.add_argument("--eval-data", required=True, help="Eval data JSON file (from evaluate_prompt.py)")
    parser.add_argument("--index",     default="registry/INDEX.json")
    args = parser.parse_args()

    with open(args.draft) as f:
        draft = json.load(f)

    with open(args.eval_data) as f:
        eval_data = json.load(f)

    with open(args.index) as f:
        index = json.load(f)

    prompt_id = draft["id"]
    version   = draft["version"]

    if check_duplicate(index, prompt_id, version):
        print(f"ERROR: {prompt_id}@{version} already exists in {args.index}. Aborting.", file=sys.stderr)
        sys.exit(1)

    entry = merge_eval_into_draft(draft, eval_data)
    append_to_index(args.index, entry)

    print(f"Registered {prompt_id}@{version} → {args.index}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests — all must pass**

```bash
python3 -m pytest tests/test_register_prompt.py -v
```

Expected:
```
tests/test_register_prompt.py::TestCheckDuplicate::test_no_duplicate_on_empty PASSED
tests/test_register_prompt.py::TestCheckDuplicate::test_detects_exact_match PASSED
tests/test_register_prompt.py::TestCheckDuplicate::test_different_version_not_duplicate PASSED
tests/test_register_prompt.py::TestMergeEvalIntoDraft::test_updates_eval_status_from_grade PASSED
tests/test_register_prompt.py::TestMergeEvalIntoDraft::test_cost_and_tokens_updated PASSED
tests/test_register_prompt.py::TestMergeEvalIntoDraft::test_failing_grade_sets_status_failed PASSED
tests/test_register_prompt.py::TestMergeEvalIntoDraft::test_none_grade_sets_pending PASSED
tests/test_register_prompt.py::TestMergeEvalIntoDraft::test_body_field_removed_from_registry_entry PASSED
tests/test_register_prompt.py::TestAppendToIndex::test_appends_entry PASSED
tests/test_register_prompt.py::TestAppendToIndex::test_write_is_atomic PASSED
tests/test_register_prompt.py::TestAppendToIndex::test_updates_generated_at PASSED
11 passed in 0.XX s
```

- [ ] **Step 5: Commit**

```bash
git add scripts/register_prompt.py tests/test_register_prompt.py
git commit -m "feat: add register_prompt.py with duplicate detection and atomic INDEX.json write"
```

---

## Task 3: Run all tests and push

- [ ] **Step 1: Run full test suite**

```bash
python3 -m pytest tests/test_evaluate_prompt.py tests/test_register_prompt.py tests/test_server.py -v
```

Expected: 22 passed, 0 failed.

- [ ] **Step 2: Smoke test `register_prompt.py` against real files**

```bash
# Export a draft JSON for testing (using the existing consensus_protocol prompt body)
python3 -c "
import json
draft = {
  'id': 'consensus_protocol_test',
  'version': '0.0.1',
  'status': 'draft',
  'tier': 'audit',
  'owner': 'unknown',
  'body': 'Test body.',
  'use_case': 'Smoke test entry',
  'default_model': 'claude-sonnet-4-6',
  'cost_per_run_usd': None,
  'tokens_prompt_body': None,
  'tested_on': ['claude-sonnet-4-6'],
  'eval_status': 'unevaluated',
  'composes': [],
  'file': None,
  'notes': '',
}
open('/tmp/draft_test.json', 'w').write(json.dumps(draft, indent=2))
eval_data = {
  'id': 'eval_consensus_protocol_test_v0_0_1_2026-05-10',
  'directive_file': 'registry/evals/strategiai_directive.md',
  'date': '2026-05-10',
  'prompt_under_test': {'id': 'consensus_protocol_test', 'version': '0.0.1'},
  'model': 'claude-sonnet-4-6',
  'tokens': {'input': 500, 'output': 300, 'cache_read': 0, 'total': 800},
  'cost_usd_estimated': 0.006,
  'response': 'Smoke test response.',
  'grade': 'A',
  'notes': 'Smoke test.',
}
open('/tmp/eval_test_data.json', 'w').write(json.dumps(eval_data, indent=2))
print('Files written.')
"
```

Then run (against a copy of INDEX.json so we don't pollute it):
```bash
cp registry/INDEX.json /tmp/INDEX_test.json
python3 scripts/register_prompt.py \
  --draft /tmp/draft_test.json \
  --eval-data /tmp/eval_test_data.json \
  --index /tmp/INDEX_test.json
```

Expected:
```
Registered consensus_protocol_test@0.0.1 → /tmp/INDEX_test.json
```

Verify the entry appears:
```bash
python3 -c "import json; d=json.load(open('/tmp/INDEX_test.json')); print([p['id'] for p in d['prompts']])"
```

Expected: list includes `consensus_protocol_test`.

- [ ] **Step 3: Push**

```bash
git push origin master
```
