# Prompt Studio

Prompt Studio is a local-first workbench for turning AI-assisted deliberation into decisions you can trust: draft and iterate prompts against local (MLX / LM Studio) or frontier models, keep a versioned prompt registry with an eval pipeline, and seal the decisions you reach as signed, hash-chained ClisTa records in ThreadHub.

It is the "deliberate" layer of the ClisTa decision stack (deliberate → shape → notarize) and wears the clista.ai design system — ink on paper, color only as a protocol signal.

## The app

A single-page shell (`sandbox/index.html`, no build step) with five views:

- **Home** — recent decisions + how the pieces fit together.
- **Deliberate** — the prompt sandbox: chat a decision through with your chosen model, load a system prompt from the Registry, pull vault context (RAG), then **Seal as decision** — assisted by ✨ Suggest, which drafts the seal fields from the conversation.
- **Decisions** — signed decision records read back from ThreadHub, with chain verification (`✓ chain valid`). Verification proves structure, never content.
- **Registry** — the versioned prompt library, with the promotion workflow (below).
- **Sessions** — saved deliberations.

## Promotion is a recorded decision (Threads Phase 4)

Prompts don't flip to `production` by editing a field — promotion opens a **final comment period (FCP)**:

1. `POST /api/prompts/<id>/promote/<version>` opens a time-boxed objection window and pins the latest eval run (content-hashed) as evidence.
2. Objections filed during the window survive into the record; an upheld objection aborts the promotion.
3. Status flips only when the window closes clean — or is explicitly **waived, disclosed as `fcp_waived: true`** in the sealed record. Absence of evidence is disclosed, never faked.
4. Every terminal outcome (closed / waived / aborted / deprecated) seals a decision-as-claim to ThreadHub.

Direct writes of `status='production'` (create, update, or the old validate route) return `409` pointing at the promote flow. Full route list in `docs/superpowers/specs/2026-07-12-threads-phase4-promotion-decision-design.md`.

## Repository structure

- `sandbox/` — the SPA shell + `js/` modules (config, panes, sessions, seal-extract, registry picker).
- `registry/` — prompt archive, evals, `INDEX.json`, and the registry widget (iframe).
- `threads/` — the Decisions widget (iframe) reading ThreadHub through the server proxy.
- `scripts/` — eval / register / execute pipeline (below).
- `server.py` — stdlib-Python API + static server: sessions, prompts, chat proxy (Anthropic / OpenAI-compat / MLX), ThreadHub proxy, seal orchestration, promotion FCP.
- `seal.py`, `promotion_store.py`, `promotion_evidence.py`, `promotion_seal.py` — seal + promotion machinery.
- `schema.sql` — SQLite schema: sessions, prompts, evals, promotions, promotion_objections.
- `JULES_WORKFLOW.md` — operational manual for Jules in this repository.

## Running

```bash
# ThreadHub sidecar (:8110) — canonical checkout lives in the lati-cooki/clista monorepo
bash sandbox/_run-threadhub.sh &

# API + UI (serves the shell at /, registry at /registry/, decisions at /threads/)
python3 server.py            # port 8000; PORT=8001 python3 server.py to override
```

Environment (all optional): `PORT`, `ALLOWED_ORIGIN` (CORS allowlist, comma-separated; default `http://localhost:7777`), `LM_STUDIO_URL`, `CLISTA_CLI` (path to the ClisTa CLI; defaults to `~/ClisTa-Protocol/src/cli.js`), `THREADHUB_PORT`, plus API keys in `.env` for frontier models and the eval script.

`sandbox/launch.command` opens the full local stack (MLX models, vault-search, ThreadHub) in Terminal windows — note its web-server script predates `server.py` and still serves the old static path.

## Scripts

### Evaluate a prompt

```bash
python3 scripts/evaluate_prompt.py \
  --prompt registry/prompts/consensus_protocol_v1_1_0.md \
  --directive registry/evals/strategiai_directive.md \
  --model claude-sonnet-4-6 \
  --output-dir registry/evals/
```

Writes `eval_<id>.md` + `eval_<id>_data.json`. The newest `*_data.json` for a version is what the promotion flow pins as evidence.

### Register a prompt

```bash
python3 scripts/register_prompt.py \
  --draft /path/to/draft.json \
  --eval-data registry/evals/eval_<id>_data.json \
  --index registry/INDEX.json
```

Duplicate-checks by `id + version`, writes atomically, strips `body` from the registry entry. Also records the prompt in the live studio DB (`--db`, default `prompt_studio.db`; `--no-db` to skip) so it appears in `/api/registry` immediately — if the DB is absent, the server's boot-time backfill picks it up from `INDEX.json` instead.

### Execute a task with a registered prompt

```bash
./scripts/execute_with_jules.sh consensus_protocol "Evaluate the StrategiAI plan"
./scripts/execute_with_jules.sh consensus_protocol "Evaluate X" --version 1.1.0
./scripts/execute_with_jules.sh consensus_protocol "Evaluate X" --dry-run
```

Prefers `production` > `active` > `draft` > `deprecated` when no version is specified.

## The Tri-Role Jules Architecture

Jules (Google's asynchronous coding agent) operates this repository in three capacities:

1. **Developer** — building and maintaining the infrastructure.
2. **Evaluator** — the automated QA pipeline (`evaluate_prompt.py` → grade → `register_prompt.py`).
3. **Executor** — consuming production prompts to run complex reasoning tasks via `execute_with_jules.sh`.

## Tests

```bash
python3 -m unittest discover tests -v     # server, seal, promotion FCP, eval, register, lookup
node --test sandbox/js/*.test.js          # state, sessions, stream, tokens, registry picker, seal-extract
```
