# Jules Operational Workflow

This document defines how Jules interacts with the Prompt Studio repository across its three roles. When creating a session for Jules (`jules new`), reference the specific role workflow below.

## Architecture (current)

- **`server.py`** — Unified backend on port 8000: SQLite (`prompt_studio.db`), REST API, static UIs.
- **`sandbox/`** — Live prompt iteration UI. Sessions persist via `/api/sessions` (not `localStorage`).
- **`registry/`** — Version-controlled prompts + `INDEX.json`. Registry widget loads live data from `/api/registry`.
- **`scripts/`** — Eval, register, and Jules executor pipeline.

```bash
python3 server.py          # API + sandbox at / + registry at /registry
python3 -m pytest tests/ -v
cd sandbox && node --test js/*.test.js
```

## 1. Developer Workflow

**Goal:** Build and maintain Prompt Studio infrastructure.
**Trigger:** `jules new "Feature description"`

**Guidelines:**
- Keep the sandbox **no build step** (vanilla HTML/JS modules) unless a change truly requires npm.
- New registry or session features should use the existing SQLite API in `server.py`, not duplicate state in HTML.
- Whitelist static routes in `server.py` — do not re-enable broad directory serving (see `test_security.py`).
- Do not commit `.devswarm-temp/` artifacts.

## 2. Evaluator Workflow

**Goal:** Automated QA for prompts.
**Trigger:** `jules new "Evaluate consensus_protocol@1.1.0 against strategiai directive"`

**Process:**
1. Read the prompt from `registry/prompts/` and the directive from `registry/evals/strategiai_directive.md`.
2. Run evals (Anthropic models via script, or document multi-provider runs manually):

```bash
# Single model
python3 scripts/evaluate_prompt.py \
  --prompt registry/prompts/consensus_protocol_v1_1_0.md \
  --directive registry/evals/strategiai_directive.md \
  --model claude-opus-4-7

# Full v1.1.0 regression batch (requires ANTHROPIC_API_KEY)
./scripts/run_regression_v1_1_0.sh
```

3. Grade the markdown (`## Grade`) and set `grade` in the `*_data.json`.
4. Register on pass:

```bash
python3 scripts/register_prompt.py \
  --draft /path/to/draft.json \
  --eval-data registry/evals/eval_<id>_data.json \
  --index registry/INDEX.json
```

**v1.1.0 pass criteria:** Step 0 must surface the StrategiAI arithmetic inconsistency ($49 / 75 queries / $0.04–$0.06 vs claimed negative margin) and propose a reconciliation hypothesis.

## 3. Executor Workflow

**Goal:** Run production prompts on real tasks.
**Trigger:** `jules new "Execute task using registered prompt Z"`

```bash
./scripts/execute_with_jules.sh consensus_protocol "Evaluate the StrategiAI plan"
./scripts/execute_with_jules.sh consensus_protocol "Evaluate X" --version 1.1.0 --dry-run
```

**Process:**
1. Lookup in `registry/INDEX.json` (or `scripts/lookup_prompt.py`).
2. Read prompt body from `registry/prompts/`.
3. Apply as system context for the task; output per prompt schema.