# Unified Prompt Studio SPA — Design Spec

**Date:** 2026-05-11
**Status:** Draft — pending implementation plan

---

## Problem

Prompt Studio has two disconnected UIs (`/` sandbox, `/registry/` registry) and a collection of CLI scripts. The intended lifecycle — pick a prompt, run it against a directive, compare models, save results, update the registry, repeat — requires manually switching pages, downloading JSON, and running terminal commands at each step. The full loop is not achievable from a single surface.

---

## Goal

A single-page application where the complete eval loop is one continuous in-UI flow:

1. Select a registered prompt → it becomes the system prompt for all panes
2. Enter a directive → sent simultaneously to all selected models
3. Compare responses across local MLX models and frontier API models side-by-side
4. Save the session
5. Update the registry (new draft version or mark eval validated)
6. Repeat with the next directive or a revised prompt

---

## Architecture

### Page structure

```
/ ── Unified SPA (replaces sandbox/index.html as root)
/registry/ ── Redirects to / with #registry tab active (or stays as standalone for now)
```

The SPA has two top-level views toggled by a topbar tab:

- **Eval view** (default): multi-pane directive runner
- **Registry view**: full registry browser (current registry_widget.html content, embedded)

### Layout (Eval view)

```
┌─────────────────────────────────────────────────────────────────┐
│ Left Rail (220px) │ Main (flex) │ Registry Panel (240px) │
│ ─────────────────  ────────────  ──────────────────────── │
│ Active Prompt     │ [Topbar]    │ Prompt metadata         │
│  dropdown         │ ─────────── │ version, eval_status    │
│                   │ Pane A │ B │ tokens, cost/run         │
│ Models            │        │ C │ ──────────────           │
│  checklist        │        │   │ Save as vX.Y.Z draft     │
│  local + frontier │        │   │ Mark eval: validated     │
│                   │        │   │ View full registry →     │
│ Sessions          │ ─────────── │                         │
│  recent list      │ [Directive] │                         │
│ ──────────────── │  composer   │                         │
│ Save session      │             │                         │
│ Update registry → │             │                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Components

### 1. Left Rail

**Active Prompt picker**
- Dropdown populated from `GET /api/prompts`
- Shows `id` + version + eval_status badge
- Selecting a prompt loads its `body` as the system prompt for all panes
- Option to start a "new draft" (blank system prompt, unsaved)

**Model checklist**
- List of all configured models with checkboxes
- Two groups: **Local** (MLX endpoints from config) and **Frontier** (Claude API models)
- Checking/unchecking a model adds/removes its pane from the main area
- Minimum one model must remain checked
- Local models: direct fetch to MLX endpoint (existing flow)
- Frontier models: proxied through `POST /api/chat` on the server

**Sessions list**
- Most recent sessions, click to load
- Loaded session restores: active prompt, selected models, directive history

**Bottom actions**
- `Save session` — saves current state (prompt ref, models, messages)
- `Update registry →` — opens a modal with two options: Save as new draft version, or Mark current eval validated

### 2. Topbar

- Breadcrumb: `Prompt Studio / <session name>`
- Mode tabs: **Eval** | **Registry**
- Stop button (visible while streaming)

### 3. Panes

- One pane per checked model, flex-equal width
- Each pane header shows: model name, local/api tag, token count
- Pane body: system prompt preview (read-only, from registry), then conversation bubbles
- System prompt is **not editable per-pane** — it comes from the registry picker. To change it, the user edits the prompt in registry view or saves a new draft.
- Panes are created/destroyed as models are checked/unchecked

### 4. Directive Composer

- Replaces the generic "message" input
- Labeled: **Directive → sent to all active models**
- Placeholder: "Enter directive… e.g. Evaluate the Q3 plan for strategic coherence"
- `⌘↵` sends to all active panes simultaneously
- Single shared input — the same directive goes to every model (this is the eval pattern)

### 5. Registry Panel (right)

- Shows metadata for the currently selected prompt: id, version, status, tier, eval_status, token count, cost/run
- **Save as vX.Y.Z draft** — increments minor version, creates a new `prompts` row with status=draft, body = current system prompt text
- **Mark eval: validated** — updates `eval_status` on current prompt version to `validated`, sets status to `production`
- **View full registry →** — switches topbar to Registry tab

### 6. Registry View (tab)

- Renders `/registry/` in a full-height `<iframe>` inside the SPA — no rewrite of registry_widget.html required
- The iframe's `registry_widget.html` gets a small addition: an **"Open in Eval →"** button per row that calls `window.parent.postMessage({ type: "loadPrompt", id, version }, "*")` — the parent SPA listens, switches to the Eval tab, and selects that prompt

**Version increment rule for "Save as draft":** takes the highest existing version for that prompt ID in the registry, increments the minor segment by 1 (e.g. 1.1.0 → 1.2.0), and creates a new row with status=draft. If a draft at that version already exists, it is overwritten in place (upsert).

---

## Data Model Changes

### Sessions (existing table, updated save format)

Current `panes` JSON: `[{ systemPrompt, messages, modelKey }]`

New `panes` column JSON:
```json
{
  "promptRef": { "id": "consensus_protocol", "version": "1.1.0" },
  "models": ["qwen3-4b", "qwen3-27b", "claude-sonnet-4-6"],
  "panes": [
    { "modelKey": "qwen3-4b", "messages": [...] },
    { "modelKey": "claude-sonnet-4-6", "messages": [...] }
  ]
}
```

The `vault_config` column is unchanged — the server continues to save it separately and the client reads it from `entry.vaultConfig` as before.

Old format is backward-compatible on load: if `promptRef` is absent, treat as legacy session and load `systemPrompt` from `panes[0].systemPrompt` with no registry binding.

### Server — new endpoint

`POST /api/chat`

Routes a single chat completion request to either a local MLX endpoint or the Anthropic API based on model key.

Request:
```json
{
  "modelKey": "claude-sonnet-4-6",
  "messages": [...],
  "system": "..."
}
```

Response: Server-Sent Events stream (same format as MLX — `data: {...}` lines), so the existing `send.js` SSE parser works unchanged.

For frontier models, the server reads `ANTHROPIC_API_KEY` from the environment and calls the Anthropic API using `anthropic` Python package (already installed). Streaming is forwarded to the client.

### Config — frontier models

`config.js` adds a `frontier` group alongside the existing MLX models:

```js
export const FRONTIER_MODELS = {
  "claude-haiku-4-5":   { id: "claude-haiku-4-5-20251001",  provider: "anthropic" },
  "claude-sonnet-4-6":  { id: "claude-sonnet-4-6",           provider: "anthropic" },
};
```

Frontier models route through `/api/chat` instead of directly to a local endpoint.

---

## Regression & Test Plan

### Existing tests (must all pass throughout)

- `python3 -m pytest tests/ -v` — 35 server + script tests
- `node --test sandbox/js/*.test.js` — 44 JS unit tests (state, sessions, stream, tokens)

### New tests to add

**JS unit tests:**
- `model-selector.test.js`: toggling models adds/removes panes; min-1 enforcement
- `sessions.test.js`: load legacy format (no `promptRef`) falls back gracefully; new format round-trips cleanly
- `directive.test.js`: send dispatches to N panes; abort cancels all streams

**Server tests:**
- `POST /api/chat` with local model key → forwards to MLX endpoint (mock)
- `POST /api/chat` with frontier model key + env key → calls Anthropic API (mock)
- `POST /api/chat` with frontier model key, no env key → returns 503 with clear error

**Integration / acceptance (manual checklist):**
- [ ] Load app at `/` — prompt dropdown populated from registry
- [ ] Select a registered prompt — system prompt preview updates in all panes
- [ ] Check 3 models — 3 panes appear
- [ ] Uncheck a model — pane removed, others stay
- [ ] Enter directive, send — all panes stream simultaneously
- [ ] Save session — appears in sessions list, reloads correctly
- [ ] "Save as draft" — new version appears in registry dropdown
- [ ] "Mark eval validated" — eval_status updates in registry panel
- [ ] Load legacy session — no crash, system prompt shown without registry binding
- [ ] `/registry/` still works (standalone or tab)

---

## Visual Design

The unified SPA inherits the existing **Consensus Protocol design language** from `sandbox/index.html` exactly as-is:

- Palette: `--paper` (#f6f3ec cream), `--ink` (#0c0f14), `--ink-2/3/4` grays, `--amber`, `--green`, `--red`, `--teal`, `--plum`
- Fonts: Inter Tight (sans), JetBrains Mono (mono), Newsreader (serif)
- Existing component styles (rail, pane, bubble, composer, session-rail) are reused; new components (model checklist, registry panel) follow the same token conventions

No new CSS framework, no design system change. The brainstorming mockup used a dark theme for contrast only — the built UI is light/paper.

---

## What Is Not Changing

- `server.py` transport (stdlib http.server, no Flask)
- `schema.sql` sessions and prompts tables (additive only)
- `send.js` SSE parser (reused for all models including frontier via proxy)
- `sessions.js` API layer
- Vault integration (checkbox + top-K, unchanged)
- `scripts/` CLI tools (evaluate_prompt.py, register_prompt.py, execute_with_jules.sh)
- All 35 existing Python tests and 44 JS tests

---

## Open Questions (resolved)

- **System prompt editing**: Removed from per-pane UI. To edit a prompt, use the Registry view or save a new draft version from the registry panel. This enforces the registry as the source of truth.
- **Directive vs message**: The composer is explicitly labeled "Directive" — it maps to the `user` role in the messages array, same as before. No schema change.
- **Compare mode**: Replaced by the model checklist. Any number of models can be active. The old single/compare toggle is removed.
- **Vault**: Kept as-is. Vault context is injected per-send as before; the checkbox moves to the composer area.
