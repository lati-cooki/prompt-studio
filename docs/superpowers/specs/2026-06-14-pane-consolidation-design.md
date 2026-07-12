# Pane System Consolidation — Design

**Date:** 2026-06-14
**Status:** Approved (brainstorm), pending implementation plan
**Component:** Prompt Studio sandbox (`~/DevSwarmProjects/Clista/sandbox/`)

## Context

The Phase-1 upstream merge left the sandbox with what looked like two coexisting "pane" systems. A
full code map (app.js / pane.js / model-selector.js / send.js / sessions.js / meter.js / index.html)
shows it is **not** two live systems — it is **one live system plus a dead legacy system**. A recent
declutter pass CSS-hid the dead pieces; this spec removes them properly and fixes one real bug exposed
by the map.

## Findings (the map)

**Live system — the model-checklist / `activePaneMap`.** Every real interaction routes here:
- Chat send → `sendToPanes({ panes: activePanes(), … })` (app.js) → `activePaneMap`.
- Prompt apply → `applyPromptToAllPanes` via the rail `#prompt-picker`, the registry postMessage, and
  session load.
- Sessions save/load (`currentSnapshot`, `loadEntry`), token meter, ✨ Suggest (`window.sealActivePane`),
  autoname, reset — all iterate `activePaneMap`.
- "Compare" is already multi-select: checking 2+ models in the Setup-drawer Models checklist creates
  2+ panes (`syncPanes`/`createOrUpdatePane`).

**Dead legacy system — the "A/B" panes.** Essentially unreachable:
- `stateB`, `paneB`, `modelKeyB` — declared, **never assigned or read** by any path.
- `#mode-toggle` (`#seg-single`/`#seg-compare`) — refs queried, **no event listeners attached**; never
  creates paneB or toggles `.compare`. `$stopBoth` — queried, no handler.
- `paneA` — a full pane built + appended to `#pane-container` at module init, then only written by
  `applyRegistryPromptToPane(stateA, paneA, …)`, called only by `handleRegistryLoad` — whose trigger
  (`#registry-load-btn` in the `.registry-load` topbar widget) is hidden, so the whole flow is
  dead-in-practice.
- The `.compare .pane[data-pane-id="A"|"B"]` CSS rules are permanently inert (`.compare` is never set).
- `populateRegistrySelect()` still fires a boot fetch to populate the hidden `#registry-prompt-select`.

**Real bug exposed.** `activePanes()` returns `model: liveModels[modelKey]`, but **frontier models
(Claude/GPT/etc.) live in `ALL_MODELS`/`FRONTIER_MODELS`, not `liveModels`** — so `model` is
`undefined` and `send.js` (`model.endpoint`, ~line 40) throws when sending to a frontier model. Local
LM-Studio models work (they are in `liveModels`); frontier models crash. The same gap makes
`createOrUpdatePane`'s meter use the 32768 fallback context window for frontier models.

## Goal

Consolidate onto the one live (model-checklist) pane system: **delete the dead legacy A/B system and
its inert markup/CSS, and fix the frontier-model lookup** so Claude/GPT actually send. No change to the
live system's behavior.

## Changes

### Delete (dead code) — `sandbox/js/app.js`
- `stateA`, `stateB`, `paneA`, `paneB`, `modelKeyA`, `modelKeyB` declarations and the init
  `createPane({ id: "A", … })` call.
- `applyRegistryPromptToPane`, `handleRegistryLoad`, `populateRegistrySelect`, `showRegistryStatus`,
  and their DOM refs (`$segSingle`, `$segCompare`, `$stopBoth`, `$registrySelect`/`$registryLoadBtn`/
  `$registryStatus`) + the `$registryLoadBtn` click listener.
- The duplicate `paneContainer` binding (keep `$paneContainer`).
- `paneHasConversation(stateA)` guard logic (it referenced the dead stateA).

### Delete (dead markup/CSS) — `sandbox/index.html`
- The `#mode-toggle` block (`#seg-single`, `#seg-compare`) and the `.registry-load` topbar block
  (`#registry-prompt-select`, `#registry-load-btn`, `#registry-status`).
- The `#stop-both` element (if present) — verify it has no live handler first.
- The inert `.compare .pane[data-pane-id="A"|"B"]` CSS rules.
- The declutter hacks added earlier that are now redundant:
  `.pane[data-pane-id="A"] { display:none }` and `#mode-toggle, .registry-load { display:none }`
  (the elements they hid are deleted).

### Fix the frontier-model lookup — `sandbox/js/app.js`
- `activePanes()` → `model: ALL_MODELS[modelKey]` (frontier + local both resolve; `ALL_MODELS` is kept
  in sync with `liveModels` at discovery time).
- `createOrUpdatePane` meter `contextWindow: ALL_MODELS[modelKey]?.contextWindow ?? 32768`.

## Resulting behavior
- **One** pane system. Single pane by default (the default `selectedModelKeys` = 1 model → 1 pane), with
  no CSS hack.
- **Compare** = check 2+ models in the Setup-drawer Models checklist.
- **Send works for both local and frontier models** (the bug fix).
- The topbar keeps `⚙ Setup` + `Seal`; the dead Single/Compare toggle and topbar registry-load are gone.
- The rail `#prompt-picker` remains the single prompt-loading path.

## ID-contract change
These ids are **removed** (markup + the JS that referenced them are deleted together, so nothing dangles):
`seg-single`, `seg-compare`, `mode-toggle`, `registry-prompt-select`, `registry-load-btn`,
`registry-status`, `stop-both`. The updated id list (for any future contract check) drops these.

## Error handling
- No new error surfaces. The deletions remove dead paths; the frontier fix removes a crash.
- `activePanes()` for an unknown key returns `model: undefined` only if a `selectedModelKey` isn't in
  `ALL_MODELS` (shouldn't happen, since selection comes from the model list) — same tolerance as today.

## Testing
- **`node --test sandbox/js/*.test.js`** must stay green (the pure modules — view/state/stream/sessions/
  tokens — are unaffected). `node --check sandbox/js/app.js` clean.
- **The app must boot** with the model checklist populated and no console errors (headless).
- **Interactive acceptance (user-verified):** send to a **local** model AND a **frontier** model
  (Claude/GPT) — both reply, no crash; check a 2nd model in Setup → a 2nd pane appears (Compare);
  load a prompt from the rail picker → applies to the pane(s); Save a session and reload it → restores;
  ✨ Suggest → Seal still works; Deliberate still shows a single pane by default.

## Non-goals
- No change to the model-selector UX, `send.js`, the seal/Suggest flow, or session persistence format.
- No rename of `activePaneMap`/`syncPanes` internals — just delete the dead twin + fix the lookup.
- No re-introduction of a separate Single/Compare toggle (multi-select is the compare mechanism).
