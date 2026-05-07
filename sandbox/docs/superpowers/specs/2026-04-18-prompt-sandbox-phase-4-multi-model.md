# Prompt Sandbox — Phase 4: Multi-Model (Per-Pane Model Selection)

**Date:** 2026-04-18
**Status:** Approved design, awaiting implementation plan.
**Parent project:** `prompt-sandbox`
**Prior specs:**
- `docs/superpowers/specs/2026-04-18-prompt-sandbox-ab-compare.md` (Phase 1)
- `docs/superpowers/specs/2026-04-18-prompt-sandbox-phase-2-persistence.md` (Phase 2)
- `docs/superpowers/specs/2026-04-18-prompt-sandbox-phase-3-meter.md` (Phase 3)

## Context

Phase 3 evolved `js/config.js` to a `MODELS` registry so swapping the LLM would be a one-line change. Phase 4 makes that real: the registry is now a runtime surface, each pane can target a different entry, and A/B compare gains teeth — "Gemma with prompt X vs Llama with prompt Y" becomes a first-class workflow instead of "same model, two prompts."

The browser's CORS constraint means cloud providers (OpenAI, Anthropic) still require a local proxy the user runs themselves. Phase 4 does **not** ship a proxy; it documents the pattern and assumes any endpoint the browser talks to is OpenAI-compatible and CORS-friendly.

## Goals

- **Per-pane model selection**: each active pane owns a model reference; `sendToPanes` dispatches per-pane, same parallel-fan-out as Phase 1.
- **Runtime switcher UI**: a dropdown per pane (visible in both single-pane and A/B modes) lists `Object.keys(MODELS)`; switching takes effect on the next send.
- **Persistent Pane A selection**: Pane A's choice saves to `localStorage` so page reloads don't dump you back to the `ACTIVE_MODEL_KEY` default.
- **Saved-session fidelity**: sessions capture per-pane `modelKey`; loading restores each pane's model. Phase 3 sessions (no modelKey) degrade gracefully.
- **Meter keeps its exact-anchor continuity** across model switches via a new `updateContextWindow(n)` API on the meter handle.
- Continue "one HTML file, no build, no npm" constraint.

## Non-goals

- **No in-repo proxy.** Cloud providers (OpenAI, Anthropic native, any CORS-blocked endpoint) are handled by a local proxy the user runs themselves. README documents the pattern.
- **No secrets in the browser.** API keys stay with the proxy.
- **No wire-format translation in client code.** Everything the browser talks to is OpenAI-compatible (`/v1/chat/completions` with SSE streaming + `usage`).
- **No cost display.**
- **No model-specific prompt templating.** The system prompt is already portable; per-model variants are a user concern, not code.
- **Pane B's selection is transient** (not persisted across reloads). B is created lazily via Compare; defaulting to Pane A's current model on enter is sufficient.

## Design

### 1. Data model

Three state layers:

**`MODELS` (js/config.js, unchanged shape):**

```javascript
export const MODELS = {
  "gemma-4-26b": {
    id:            "mlx-community/gemma-4-26B-A4B-it-4bit",
    endpoint:      "http://localhost:8080/v1/chat/completions",
    contextWindow: 128000,
  },
  "llama-3-local": {
    id:            "meta-llama/Meta-Llama-3-8B-Instruct",
    endpoint:      "http://localhost:8091/v1/chat/completions",
    contextWindow: 8192,
  },
};
```

**`ACTIVE_MODEL_KEY` + `ACTIVE_MODEL` exports are removed.** Phase 3's shim has no remaining consumers after Task 1's migration. In their place:

```javascript
export const DEFAULT_MODEL_KEY = "gemma-4-26b";

export function getActiveModelKey() {
  try {
    return localStorage.getItem("promptSandbox.modelKey") || DEFAULT_MODEL_KEY;
  } catch {
    return DEFAULT_MODEL_KEY;
  }
}
```

`getActiveModelKey()` is used only as:
1. The initial value of `modelKeyA` at app boot.
2. The fallback in `loadEntry` when a saved session lacks `modelKey` or references a removed entry.

Everywhere else (`send.js`, meter attachment, `activePanes()`), code reads the per-pane `modelKey` and looks up `MODELS[key]` directly. No module-level "active" reference — per-pane is the new active.

**Per-pane state in app.js:**

```javascript
let modelKeyA = getActiveModelKey();
let modelKeyB = null;   // set by enterCompare(); copies modelKeyA
```

No persistence for `modelKeyB` — Pane B is transient by design.

### 2. Save / load shape

Session entries gain `modelKey` per pane:

```javascript
{
  id, name, createdAt, updatedAt,
  panes: [
    { systemPrompt, messages, modelKey: "gemma-4-26b" },
    // second element in A/B
  ],
  vaultConfig: { enabled, topK },
}
```

Load behavior:
- `entry.panes[0].modelKey` → `modelKeyA`.
- `entry.panes[1]?.modelKey` → `modelKeyB`.
- Missing `modelKey` (Phase 3 entries) → fall back to `getActiveModelKey()`.
- If a saved `modelKey` references a `MODELS` key that no longer exists, fall back to `getActiveModelKey()` and log a `console.warn`.

### 3. UI: per-pane model selector

Attach a compact dropdown to each pane's `.pane-prompt` header, alongside the meter. Layout:

```
┌──────────────────────────────────────────────┐
│ Role: You are my Lead Strategic Advi…        │ ← existing preview
│ [gemma-4-26b ▾]  ├──── 1,247 / 128K ────────┤│ ← NEW: model picker + meter
└──────────────────────────────────────────────┘
```

The model picker is a native `<select>` styled to match the existing controls. Options come from `Object.keys(MODELS)` at construction. Change handler:

1. Updates `modelKeyA` / `modelKeyB` as appropriate.
2. Calls `meter.updateContextWindow(MODELS[newKey].contextWindow)` on that pane's meter.
3. If the pane is Pane A, persists to localStorage: `localStorage.setItem("promptSandbox.modelKey", newKey)`.

A pane's selector lives in `js/pane.js` — it's part of the pane's DOM. Pane factory adds:

```javascript
// In createPane's return:
modelSelect,   // the <select> element
setModelKey(key),   // programmatic change (no event fire)
onModelChange(fn),  // subscribe to user changes
```

`app.js` wires: on change → update runtime state + meter + localStorage (A only).

### 4. `js/send.js` per-pane model

`activePanes()` now returns each pane with a `model` field:

```javascript
const activePanes = () => paneB
  ? [{ state: stateA, pane: paneA, model: MODELS[modelKeyA] },
     { state: stateB, pane: paneB, model: MODELS[modelKeyB] }]
  : [{ state: stateA, pane: paneA, model: MODELS[modelKeyA] }];
```

`sendToPanes` passes `model` into `streamOnePane`. The fetch reads `model.endpoint` / `model.id` instead of module-level `ACTIVE_MODEL`. Parallel fan-out unchanged — each pane runs its own `fetch` against its own endpoint simultaneously.

### 5. Meter `updateContextWindow(n)`

`createMeter` currently captures `contextWindow` at construction in a closure. Add an API method:

```javascript
return {
  setExactPromptTokens(n) { … },
  updateContextWindow(newMax) {
    contextWindowLocal = newMax;
    maxEl.textContent = newMax.toLocaleString();
    render();
  },
  render,
  destroy() { … },
};
```

Internal `contextWindow` parameter becomes a mutable local. The exact anchor (`exactPromptTokens` + `anchorMessageCount` + `anchorSystemPrompt`) stays — switching models doesn't invalidate it semantically; it just re-denominates the display.

### 6. Task 0 pre-work

One Phase 3 review carry-forward that intersects Phase 4 directly:

- **Minor #8 from Phase 3**: extract `computeUsed({exactPromptTokens, anchorMessageCount, anchorSystemPrompt, messages, draftText})` → number from `meter.js` into `tokens.js`. Unit-test the anchor-invalidation and slice-post-anchor branches. `meter.js` imports and uses it. Makes the correctness logic that landed in the Phase 3 meter-anchor fix properly testable.

No other structural cleanups are needed up front; everything else is additive.

### 7. Data flow (end-to-end, Phase 4 complete)

1. Page load: `modelKeyA = getActiveModelKey()` reads localStorage, defaulting to `DEFAULT_MODEL_KEY`. Pane A's selector initializes to that key. Meter's contextWindow comes from `MODELS[modelKeyA].contextWindow`.
2. User changes Pane A's model: selector fires change; `modelKeyA` updated; `meterA.updateContextWindow(...)` runs; `localStorage` updated.
3. User clicks Compare: `enterCompare()` creates Pane B with `modelKeyB = modelKeyA` (matching A as a sensible default); Pane B's selector initializes to `modelKeyA`; B's meter uses `MODELS[modelKeyB].contextWindow`.
4. User changes Pane B's model independently: same flow as A, minus the localStorage write.
5. User sends: `activePanes()` returns `{state, pane, model}` tuples; `sendToPanes` fans out; each `streamOnePane` uses its own `model.endpoint` / `.id`.
6. User saves: `currentSnapshot()` captures `modelKey` per pane; sessions.js stores it in the entry.
7. User loads: `loadEntry` reads each pane's `modelKey`, updates runtime `modelKeyA` / `modelKeyB`, syncs each pane's selector + meter.
8. User reloads the page: Pane A's last model is restored from localStorage; single-pane mode.

### 8. Documentation updates

- **README "Swapping models"** becomes **"Adding providers"**. Documents three patterns:
  1. **Local OpenAI-compatible server** (llama.cpp, vLLM, MLX): drop a new `MODELS` entry pointing at its port; make sure the server runs with CORS. Ready-to-go example for llama.cpp.
  2. **Cloud via local proxy** (OpenAI, Anthropic): run a tiny local proxy (recommend `litellm --port 8090 --model openai/gpt-4o` pattern); the proxy holds the API key and speaks OpenAI shape out to localhost:8090; add a `MODELS` entry pointing at `http://localhost:8090/v1/chat/completions`.
  3. **Native-Anthropic-via-proxy**: same as (2) with LiteLLM/OpenRouter/custom. The browser always sees OpenAI shape.
- Add a second MODELS entry (`llama-3-local`) as a concrete example.
- **CLAUDE.md**: update "Swap models by changing `ACTIVE_MODEL_KEY`" note to point at the per-pane selector and `getActiveModelKey()`.

### 9. Key invariants preserved

- Browser speaks **only** OpenAI-compatible `/v1/chat/completions` with SSE. No fetch to `api.openai.com` or `api.anthropic.com` directly.
- No secrets in the browser.
- Shared vault retrieval per send (unchanged) — vault-search call runs once regardless of per-pane model.
- Token meter's exact anchor logic unchanged; only the denominator updates on model switch.
- State mutations still go through `state.subscribe`-aware methods.

## Task breakdown (≈9 tasks)

- **T0**: extract `computeUsed` → `tokens.js`; add unit tests for anchor / slice / invalidation paths; `meter.js` imports and delegates.
- **T1**: `config.js` — add `DEFAULT_MODEL_KEY` + `getActiveModelKey()`; remove `ACTIVE_MODEL_KEY` + `ACTIVE_MODEL` exports. Update `send.js` and `app.js` consumers to read per-pane `model` or call `getActiveModelKey()` + `MODELS[key]`.
- **T2**: meter `updateContextWindow(n)` API. No-regression tests.
- **T3**: per-pane `modelKeyA` / `modelKeyB` state in `app.js`; `activePanes()` includes `model: MODELS[modelKey]` per pane.
- **T4**: `send.js` consumes `panes[i].model`; drops module-level `ACTIVE_MODEL` import in the hot path.
- **T5**: per-pane model dropdown in `pane.js`; wire change events in `app.js` to state + meter + localStorage.
- **T6**: sessions persistence — `currentSnapshot` captures per-pane `modelKey`; `loadEntry` restores (with fallback for missing); unknown `modelKey` triggers `console.warn` + fallback.
- **T7**: docs + second MODELS entry (`llama-3-local`); README "Adding providers" section; CLAUDE.md update.
- **T8**: full acceptance + cross-commit final review.

## Acceptance criteria

- Page load: Pane A shows a model dropdown with all MODELS keys; selected = whatever was in localStorage (or default).
- Switching Pane A's model: meter's denominator updates; persisted to localStorage.
- Reload: Pane A's last selection is restored.
- Compare on: Pane B gets its own dropdown, defaulted to Pane A's current selection.
- Pane A and Pane B can target different models; one send fires one request per pane against their respective endpoints; both stream independently.
- Save → reload page → load session: both panes restore with correct model, prompt, messages, vault config.
- Phase 3 saved sessions (no `modelKey`) load cleanly with each pane defaulting to `getActiveModelKey()`.
- An entry referencing a `modelKey` no longer in `MODELS` falls back with a console warning; doesn't crash.
- 49+ unit tests pass (41 existing + ~8 new for `computeUsed` + sessions modelKey round-trip + stream-shape regressions).
- All Phase 1–3 acceptance behaviors still pass.

## Risks

- **Per-pane endpoint latency variance**: Gemma on MLX vs a cloud proxy can differ by orders of magnitude. `Promise.all` waits for the slowest; meter for the fast pane sits at pending until both complete. Acceptable — compare visually is still useful.
- **Cloud-proxy CORS misconfiguration**: if the user's proxy doesn't set `Access-Control-Allow-Origin: *`, the browser blocks the request with a cryptic CORS error. Mitigation: README documents `--allowed-origins "*"` equivalents for the common proxies (litellm `--allow-cors`, fastapi CORS middleware, etc.).
- **`MODELS` key typos**: if a saved session references a key now removed from the registry, we fall back silently-plus-warn. Users may not notice the fallback happened. Acceptable; the `console.warn` is the breadcrumb.
- **Live model switching mid-send**: a user could change the selector while a stream is in flight. Current design — the stream already committed to the old endpoint; the change takes effect on the *next* send. Document this behavior; no code change needed (the selector change doesn't interrupt anything).
- **Multiple MODELS entries pointing at the same endpoint**: legal; useful for comparing two context-window settings or two prompts that "should" map to different model IDs. No code branch required.

## Phase 5+ follow-ups (explicitly out of scope)

- In-repo reference proxy (e.g., a tiny FastAPI app in `proxies/`).
- Per-provider cost display.
- A "download all saved sessions as Markdown" bulk export.
- Model-specific prompt templating if the portability assumption ever breaks.
- Multi-listener `pane.onUsage` (EventTarget pattern) — still single-listener for now; if a second observer is ever needed, cheap conversion.
