# Prompt Studio

Prompt Studio is a unified, automated environment for drafting, testing, registering, and evaluating AI prompts. It merges the live iteration capabilities of a local `sandbox` with the rigid version control and evaluation schema of a `registry`.

Crucially, **Prompt Studio is designed to be operated by Jules**, Google's asynchronous coding agent.

## Repository Structure

- `sandbox/`: The live prompt iteration UI. Connects to local MLX models or proxies. (Sourced from `prompt-sandbox`).
- `registry/`: The version-controlled archive of production-ready prompts, evaluations, and the `INDEX.json` schema. (Sourced from `prompt-registry`).
- `JULES_WORKFLOW.md`: The operational manual for Jules in this repository.
- `TODO.md`: The immediate backlog of tasks to assign to Jules.

## The Tri-Role Jules Architecture

Jules acts as the primary engine for this repository in three distinct capacities:

1. **Jules as the Developer:** Actively building and merging the infrastructure. Its first goal is to replace the Sandbox's `localStorage` and the Registry's hardcoded UI array with a unified backend (e.g., SQLite) so both systems talk to the same database.
2. **Jules as the Evaluator:** Acting as an automated CI/CD pipeline for prompts. When a draft prompt reaches maturity in the sandbox, Jules runs it against the `evals/` suite across multiple models, calculates the quality scores, and automatically commits it to the registry if it passes.
3. **Jules as the Executor:** Consuming the production prompts from the registry (like the `consensus_protocol`) to autonomously execute complex reasoning tasks defined in GitHub issues.

## Quickstart

```bash
cd prompt-studio
# Review the tasks
cat TODO.md

# Assign the first task to Jules
cat TODO.md | head -n 3 | tail -n 1 | jules new
```