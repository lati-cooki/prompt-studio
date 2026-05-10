# Prompt Studio

Prompt Studio is a unified, automated environment for drafting, testing, registering, and evaluating AI prompts. It merges the live iteration capabilities of a local `sandbox` with the rigid version control and evaluation schema of a `registry`.

Crucially, **Prompt Studio is designed to be operated by Jules**, Google's asynchronous coding agent.

## Repository Structure

- `sandbox/` — Live prompt iteration UI. Single-pane or A/B compare mode. Connects to local MLX models via `http.server`-based Python backend.
- `registry/` — Version-controlled archive of production-ready prompts, evaluations, and `INDEX.json`.
- `scripts/` — CLI tools for the eval and registration pipeline (see below).
- `server.py` — Python API serving both UIs over SQLite (`schema.sql`).
- `schema.sql` — Unified SQLite schema: sessions, prompts, evals.
- `JULES_WORKFLOW.md` — Operational manual for Jules in this repository.
- `TODO.md` — Task backlog.

## Running

```bash
# Start the API + static file server (serves sandbox at / and registry at /registry)
python3 server.py

# Or run the sandbox standalone on port 7777
cd sandbox && python3 -m http.server 7777
```

Requires: `pip install anthropic` for the eval script.

## Scripts

### Evaluate a prompt

Run a prompt file against a directive via the Claude API and write a structured eval report:

```bash
python3 scripts/evaluate_prompt.py \
  --prompt registry/prompts/consensus_protocol_v1_1_0.md \
  --directive registry/evals/strategiai_directive.md \
  --model claude-sonnet-4-6 \
  --output-dir registry/evals/
```

Writes `registry/evals/eval_<id>.md` and `registry/evals/eval_<id>_data.json`. Fill in the `## Grade` field in the markdown, then update the `grade` key in the data JSON before registering.

### Register a prompt

Merge a sandbox draft JSON + eval data JSON into `registry/INDEX.json`:

```bash
python3 scripts/register_prompt.py \
  --draft /path/to/draft.json \
  --eval-data registry/evals/eval_<id>_data.json \
  --index registry/INDEX.json
```

Duplicate-checks by `id + version`. Writes atomically via temp-file rename. Strips the `body` field from the registry entry.

### Execute a task with a registered prompt

Look up a prompt by registry ID, read its body, and feed it to `jules new` as context:

```bash
./scripts/execute_with_jules.sh consensus_protocol "Evaluate the StrategiAI plan"

# Specific version
./scripts/execute_with_jules.sh consensus_protocol "Evaluate X" --version 1.1.0

# Preview without running jules
./scripts/execute_with_jules.sh consensus_protocol "Evaluate X" --dry-run
```

Prefers `production` > `active` > `draft` > `deprecated` when no version is specified.

## The Tri-Role Jules Architecture

Jules acts as the primary engine for this repository in three distinct capacities:

1. **Jules as the Developer:** Building and maintaining infrastructure. The sandbox UI and registry interface share a unified SQLite backend via `server.py`.
2. **Jules as the Evaluator:** Automated QA pipeline for prompts. `evaluate_prompt.py` runs a draft against a directive via the Claude API; `register_prompt.py` commits it to the registry once graded.
3. **Jules as the Executor:** Consuming production prompts from the registry to autonomously execute complex reasoning tasks via `execute_with_jules.sh`.

## Tests

```bash
# Python (server + eval + register + lookup)
python3 -m pytest tests/ -v

# JavaScript (state, sessions, stream, tokens)
cd sandbox && node --test js/*.test.js
```