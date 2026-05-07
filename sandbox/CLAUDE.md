# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Single-page browser UI (`index.html`) for iterating on system prompts against a local MLX-served Gemma model, with optional RAG from a local Obsidian-style vault.

No build step, no bundler, no package manager, no tests. Everything lives in one HTML file plus three shell scripts. Edits are made directly to `index.html` and picked up on page reload.

## Running

```bash
./launch.command        # full stack: MLX + static server + vault-search, then opens browser
```

The launcher frees ports 7777 / 8080 / 8100 if held, spawns three Terminal windows, and polls `/`, `/v1/models`, and `/health` before opening `http://localhost:7777`.

Manual run (if you only need the UI against an already-running MLX):

```bash
python3 -m http.server 7777
```

## Three-service architecture

The UI is a thin client that talks to two separate local servers — both must be running for full functionality:

| Port | Service | Started by | Source |
|------|---------|------------|--------|
| 7777 | static web server (this repo) | `_run-web.sh` | `index.html` |
| 8080 | MLX chat completions (`mlx_lm.server`) | `_run-mlx.sh` | `~/mlx-env/` |
| 8100 | vault-search (embeddings + retrieval) | `_run-vault.sh` | `~/vault-search/` (sibling repo) |

`--allowed-origins "*"` on `mlx_lm.server` is mandatory — the browser blocks cross-origin requests without it.

Vault context is optional; if 8100 is down, sends proceed without context and show an inline warning. The MLX server is required.

## Key conventions

- **Config lives in `js/config.js`** — `MODELS` map + `DEFAULT_MODEL_KEY` + `getActiveModelKey()`, plus `VAULT_URL`, `STORAGE_KEY`, `DEFAULT_SYSTEM_PROMPT`. Each pane owns a `modelKey` (Pane A's persists to `localStorage["promptSandbox.modelKey"]`); the header dropdown in `pane.js` is the runtime UI. `send.js` takes `model` per pane from `activePanes()`; `meter.js` reads `.contextWindow` at construction and allows live updates via `updateContextWindow(n)`.
- **Per-pane model picker is in the pane's header DOM** — pane.js exposes `modelSelect`, `setModelKey` (programmatic, no event), `onModelChange(fn)` (user change). App.js wires Pane A's change to localStorage + meter; Pane B is in-session only.
- **Conversation state is in-memory**; saved sessions persist via `js/sessions.js` to `localStorage["promptSandbox.sessions"]`. A page reload wipes live state but not saves.
- **State mutations must go through methods** — `addUser`, `addAssistant`, `reset`, `applyPrompt`, `popLastUser`, `loadSnapshot`. All of them fire `state.subscribe` callbacks. Never write to `state.messages` directly.
- **System-prompt edits only apply on "Apply & Reset"** — typing in the textarea does not mutate `systemPrompt`; the button handler does. Preserve this behavior.
- **Vault context is ephemeral, not persisted in `messages`** — `send()` splices a retrieved-notes system message into `turnMessages` for a single request but never pushes it onto `messages`. Do not "fix" this by pushing to `messages`.
- **SSE parsing handles both `delta.content` and `delta.reasoning`** — Gemma-style models emit reasoning tokens in a separate field that's rendered in muted italics above the main content. `extractSSEDelta` also surfaces `usage` from the terminal chunk for the meter.
- **Top-K is clamped 1–20** in `send()` before calling vault-search.
- **onUsage fires BEFORE addAssistant** in `send.js`'s success path — the meter's exact anchor has to be set against the message count the server tokenized, not against the post-reply count.

## What to edit where

- Markup + styles → `index.html`.
- Entry wiring (DOM refs, event handlers, pane instantiation, meter attach) → `js/app.js`.
- Launcher behavior / port handling → `launch.command`.
- Which model/server runs → `_run-mlx.sh`, `_run-vault.sh`, `_run-web.sh`.
- The RAG backend (indexer, embeddings, `/search`, `/reindex`, `/health`) is **not in this repo** — it lives in `~/vault-search/`. See its README for endpoint contracts.

## Tests

`node --test js/*.test.js` — zero-dep Node-native tests for `stream.js`, `state.js`, `sessions.js`, `tokens.js`. DOM-facing modules (`pane.js`, `ui.js`, `session-panel.js`, `export.js`, `meter.js`, `app.js`) are verified by manual browser acceptance.

## Plans and specs

`docs/superpowers/plans/` and `docs/superpowers/specs/` hold dated design docs from the superpowers workflow. Consult before large changes to understand prior intent.
