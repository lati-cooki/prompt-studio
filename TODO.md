# Jules Task Backlog

Assign these tasks to Jules using `jules new "<task string>"`.

## Phase 1: Developer Integration (Infrastructure)
- [x] Read `sandbox/README.md` and `registry/README.md`. Design a unified SQLite database schema that can store Sandbox "Saved Sessions" alongside Registry "Registered Prompts" and their Evaluation metadata. Output the schema as `schema.sql`.
- [x] Modify the `sandbox/js/sessions.js` to support exporting a saved session directly into a draft JSON format compatible with the Registry schema (`registry/prompts/prompt_schema.md`).
- [x] Build a simple Python API (using standard library `http.server` or a minimal framework) that serves both the Sandbox UI and the Registry UI, replacing `localStorage` with SQLite read/writes.

## Phase 2: Evaluator Automation
- [x] Create a Python script `scripts/evaluate_prompt.py` that takes a draft prompt file, runs it against the `registry/evals/strategiai_directive.md`, and outputs a formatted markdown report similar to `eval_batch_001.md`.
- [x] Create a script `scripts/register_prompt.py` that takes a successful evaluation report and a draft prompt, formats it according to `prompt_schema.md`, and safely appends it to `registry/INDEX.json`.

## Phase 3: Executor Demonstration
- [x] Write a wrapper script `scripts/execute_with_jules.sh` that allows a user to specify a Registry ID (e.g., `consensus_protocol`) and a task. The script should extract the prompt from the registry and feed it directly into a `jules new` command as context.