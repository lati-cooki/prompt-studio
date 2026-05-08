# Prompt Studio

Prompt Studio is a unified, automated environment for drafting, testing, registering, and evaluating AI prompts. It merges the live iteration capabilities of a local `sandbox` with the rigid version control and evaluation schema of a `registry`.

## Operational Infrastructure

The repository has been fully integrated into a single workflow powered by:
- **Unified Backend**: A shared SQLite database (`prompt_studio.db`) stores both live Sandbox sessions and production-ready Registry assets.
- **Flask API**: A Python-based service (`server.py`) that serves the UIs and orchestrates the promotion and evaluation logic.
- **Automated Workflow**: A one-click loop that takes a prompt from "Idea" (Sandbox) → "Draft" (Registry) → "Validated Asset" (Evaluation).

## Repository Structure

- `sandbox/`: The live iteration UI. Now connects directly to the SQLite backend.
- `registry/`: The dashboard for production prompts and evaluation results.
- `scripts/`: Python and Bash utilities for the automated lifecycle:
    - `evaluate_prompt.py`: Runs multi-model stress tests against benchmark directives.
    - `register_prompt.py`: Formalizes the promotion of a validated draft to production status.
    - `execute_with_jules.sh`: Bridges registered protocols to autonomous task execution.
- `schema.sql`: The unified database definition.
- `server.py`: The core API service (port 7777).

## The Integrated Workflow

1.  **Iterate**: Use the **Sandbox** (:7777/sandbox) to refine your prompt against local MLX models.
2.  **Promote**: Use the **"Promote to Registry"** button in the Sandbox to instantly move your iteration into the shared database.
3.  **Evaluate**: Use the **Registry Dashboard** (:7777/registry) to trigger an **Automated Eval**. This runs a multi-model benchmark and persists the strategic findings to the DB.
4.  **Execute**: Run `./scripts/execute_with_jules.sh <prompt_id> "<task>"` to solve real-world problems using your validated assets.

## Quickstart

### 1. Launch the Ecosystem
Use the unified launcher on your desktop or run manually:
```bash
cd prompt-studio
~/vault-env/bin/python server.py
```

### 2. Connect Models
Ensure your local MLX servers are active (standard ports are 8080 and 8091).

### 3. Review the Backlog
See `TODO.md` for upcoming Phase 4 enhancements.
