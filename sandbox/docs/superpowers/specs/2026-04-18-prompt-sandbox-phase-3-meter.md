# Prompt Sandbox — Phase 3: Token/Context Meter + Structural Polish

**Date:** 2026-04-18
**Status:** Approved design, awaiting implementation plan.
**Parent project:** `prompt-sandbox`
**Prior specs:**
- `docs/superpowers/specs/2026-04-18-prompt-sandbox-ab-compare.md` (Phase 1)
- `docs/superpowers/specs/2026-04-18-prompt-sandbox-phase-2-persistence.md` (Phase 2)

## Context

Phase 1 shipped A/B compare + UI refresh. Phase 2 shipped persistence (Sessions + Markdown export). Phase 3 is the final planned phase: a per-pane token / context meter that shows how much of the model's context window a conversation is consuming, and does so in a way that's not tied to any specific model or backend.

Guiding principle for this phase: **the architecture should survive swapping the underlying LLM.** Nothing in Phase 3 may introduce a dependency on Gemma-on-MLX specifically. The meter uses OpenAI-compatible `usage.prompt_tokens` (available on MLX, llama.cpp server, OpenAI, and most proxies). The only model-specific knob is a context-window size, which becomes configuration.

Phase 3 also bundles the five structural carry-forwards flagged by the Phase 2 final review. These clean up the seams that the meter needs, and prep the codebase for future model-switching.

## Goals

- **Per-pane token meter**: shows `<current> / <context-window>` as a numeric readout + progress bar, updated live as the user types and after each model response.
- **Portable by construction**: no tokenizer dependency, no Gemma-only code paths, no MLX-specific fields read anywhere except through the MODELS map.
- **Model registry**: evolve `js/config.js` from flat constants to a `MODELS` map with a single `ACTIVE_MODEL_KEY` pointer. Switching models is one line in `config.js`.
- **Clean state observation**: state mutations go through methods; meter subscribes to state changes rather than polling.
- Continue the "one HTML file, no build, no npm" constraint.

## Non-goals

- No tokenizer library (tiktoken, js-tiktoken, etc.). No npm.
- No model-switcher UI. The MODELS map supports one becoming easy later; Phase 3 doesn't add the UI.
- No per-turn token badge on individual bubbles.
- No automatic truncation / "context compression."
- No cost ($) display. Local model, no dollars.
- No historical token-usage graph.
- No meter for vault-retrieval snippets separately from the combined prompt (vault text is part of `prompt_tokens` after injection; that's accurate enough).

## Design

### 1. Model registry in `js/config.js`

Replace the current flat constants with a registry:

```javascript
export const MODELS = {
  "gemma-4-26b": {
    id:            "mlx-community/gemma-4-26B-A4B-it-4bit",
    endpoint:      "http://localhost:8080/v1/chat/completions",
    contextWindow: 128000,
  },
};

export const ACTIVE_MODEL_KEY = "gemma-4-26b";
export const ACTIVE_MODEL     = MODELS[ACTIVE_MODEL_KEY];

// Unchanged from today:
export const VAULT_URL   = "http://localhost:8100";
export const STORAGE_KEY = "promptSandbox.sessions";
export const DEFAULT_SYSTEM_PROMPT = `…`;
```

- `send.js` imports `ACTIVE_MODEL` and uses `ACTIVE_MODEL.id` / `.endpoint` where it previously used `MODEL` / `API_URL`.
- Meter imports `ACTIVE_MODEL.contextWindow`.
- Backward-compat shim: also export legacy `API_URL` and `MODEL` as `ACTIVE_MODEL.endpoint` / `ACTIVE_MODEL.id` so any missed reference keeps working. Remove the shim at end of Phase 3 after a grep pass.

### 2. Task 0 pre-work (before meter features)

Five cleanups from the Phase 2 final review. Land in this order:

- **Ic — state.loadSnapshot + state.subscribe**:
  - Add `state.loadSnapshot({ systemPrompt, messages })` method: replaces both `systemPrompt` and `messages` atomically.
  - Add `state.subscribe(fn)` returning an unsubscribe function; `fn()` is called (no args) after every mutating method (`addUser`, `addAssistant`, `reset`, `applyPrompt`, `popLastUser`, `loadSnapshot`).
  - Refactor `index.html`'s `loadEntry` to call `state.loadSnapshot(...)` per pane instead of direct `state.messages = [...]` assignments.
  - Eliminates the "pre-clear stateB.messages to bypass exitCompare's confirm" hack: `loadEntry` can use `loadSnapshot` to set an empty-but-valid state on Pane B just before calling `exitCompare`, and the check `stateB.messages.length > 1` trivially becomes false.
  - Tests: new cases in `state.test.js` for `loadSnapshot` and `subscribe`.

- **Id — split `js/ui.js`**:
  - `js/session-panel.js`: takes `createSessionPanel`, `renderSaveSlot`, `renderSessionList`, `formatAge`.
  - `js/export.js`: takes `buildMarkdown`, `triggerMarkdownDownload`, `renderExportSlot`, `slugify`.
  - `js/ui.js`: keeps only `renderSources`. Becomes ~15 lines.
  - `index.html` (will become `js/app.js` in IIa) updates imports accordingly.

- **IIa — pull `index.html` script → `js/app.js`**:
  - Create `js/app.js` containing the current `<script type="module">` body.
  - `index.html` keeps styles + markup + a one-line `<script type="module" src="./js/app.js"></script>` loader.
  - `index.html` ends up ~260 lines (down from ~530), almost all CSS + markup.

- **Ia — Markdown frontmatter → block-style YAML**:
  - Change `buildMarkdown` to emit:
    ```
    ---
    name: "<escaped-name>"
    exported: 2026-04-18T21:44:00Z
    vault:
      enabled: true
      topK: 3
    ---
    ```
  - Escape double-quotes in `name`.
  - Works with Obsidian, YAML parsers, standard frontmatter readers.

- **MODELS map** (the new item):
  - Already described above. Land with Ic + the other items, ideally first so later tasks reference `ACTIVE_MODEL` already.

### 3. New module: `js/tokens.js`

Pure, DOM-free; node-testable.

```javascript
// Approximate token count from characters. ~4 chars/token for English.
// Good enough for live "how close am I to the limit" feedback.
export function approxTokens(text) { ... }

// Sum approximate tokens across messages, skipping empty contents.
export function sumMessages(messages) { ... }

// Break down an exact count across system / history / approx-preview.
// Used for the tooltip on hover.
export function breakdown({ messages, draftText, exactPromptTokens }) { ... }
```

- `approxTokens(text)` = `Math.ceil(text.length / 4)`.
- `sumMessages(messages)` = sum of `approxTokens(m.content)` over the array, plus a small fixed overhead (~3) per message for role-tag tokens.
- `breakdown(...)` returns `{ system, history, draft, totalExact, totalApprox }`.
- Tests in `js/tokens.test.js` cover empty input, ASCII, multi-byte (emoji), and overhead accounting.

### 4. Meter module: `js/meter.js`

DOM-facing; a per-pane factory.

```javascript
export function createMeter({ pane, state, contextWindow, getDraftText }) {
  // Renders a meter element inside pane.section's header area.
  // Subscribes to state changes and to input events on pane's draft textarea.
  // Exposes:
  //   setExactPromptTokens(n)   // called by send.js after stream completes
  //   destroy()                 // called when a pane is torn down (Compare exit)
}
```

- Renders:

  ```html
  <div class="meter">
    <div class="meter-numbers"><span class="meter-used">0</span> / <span class="meter-max">128,000</span></div>
    <div class="meter-bar"><div class="meter-fill"></div></div>
  </div>
  ```

- The "used" value is computed as:
  - **Exact anchor**: `exactPromptTokens` from the last completed send (0 before the first send).
  - **Approx delta**: `approxTokens(draftText)` + approximate tokens for any user/assistant messages that landed *after* the exact anchor was set (there usually aren't any, but A/B with staggered completion could create one).
  - **Sum**: `used = exactPromptTokens + approxDelta`.
- Progress bar color:
  - `<= 75%` — `--accent` (blue)
  - `> 75%` — `#e0a54a` (amber)
  - `> 90%` — `var(--error)` (red)
- Tooltip (hover) shows the `breakdown(...)` output: "system ≈ 42, history ≈ 1,184, draft ≈ 21".
- The meter listens to `state.subscribe(...)` for message-array changes and to the pane's draft input element for `input` events.
- `createMeter` returns a `{ setExactPromptTokens, destroy }` handle.

### 5. Data flow

1. **On pane creation** (in `js/app.js`):
   ```javascript
   const meterA = createMeter({ pane: paneA, state: stateA, contextWindow: ACTIVE_MODEL.contextWindow, getDraftText: () => $input.value });
   ```
   Compare-mode enter creates `meterB` with the same shape; Compare-mode exit destroys it.

2. **On draft input**: the pane's draft textarea fires `input` events; the meter recomputes `approxDelta` live.

3. **On state mutation** (addUser, addAssistant, applyPrompt, loadSnapshot, reset, popLastUser): `state.subscribe` fires; meter re-renders.

4. **On stream completion** in `js/send.js`'s `streamOnePane`:
   - OpenAI-compatible SSE streams deliver a final chunk with `usage.prompt_tokens` populated (MLX confirmed). Capture it in the SSE parser.
   - `streamOnePane` calls `meter.setExactPromptTokens(usage.prompt_tokens)` on success.
   - If `usage` is absent (some proxies don't emit it), leave the last exact value unchanged — approximate will still track.

### 6. Extracting `usage` from the SSE stream

Extend `js/stream.js`'s `extractSSEDelta` to also surface `usage`. The OpenAI wire format places `usage` on the terminal chunk alongside (or instead of) a delta. Current shape:

```javascript
{ reasoning, content, done }   // null, or { done: true }
```

New shape:

```javascript
{ reasoning, content, done, usage }   // usage present only on the terminal chunk
```

`extractSSEDelta` returns `{ usage }` on the chunk that carries it, without `reasoning`/`content`. Existing callers ignore the extra field. Tests in `stream.test.js` cover the usage-carrying chunk.

### 7. UI placement

The meter lives inside the pane's `<header class="pane-prompt">`, after the existing collapsed preview button and inside a new row. In collapsed state the prompt preview + meter share a single row:

```
[ Role: You are my Lead Strategic Adv…  ][ 1,247 / 128,000 ░▒ 1% ]
```

In expanded (prompt textarea visible) state the meter sits below the textarea:

```
[textarea ...................................]
[Apply & Reset]                                         1,247 / 128,000 ░▒ 1%
```

Independent per pane in A/B mode; each meter pulls its own `state` + its own draft element. (In compare mode the shared input feeds both panes' drafts — both meters read the same draft text.)

### 8. Non-DOM testing strategy

Four test files after Phase 3:
- `js/stream.test.js` — extended with `usage`-chunk tests.
- `js/state.test.js` — extended with `loadSnapshot` and `subscribe` tests.
- `js/sessions.test.js` — unchanged.
- `js/tokens.test.js` — new, ~10 tests for `approxTokens` / `sumMessages` / `breakdown`.
- `js/meter.js` itself has no unit tests (DOM-facing); verified via browser acceptance.

## Acceptance criteria

- `js/config.js` exports `MODELS`, `ACTIVE_MODEL_KEY`, `ACTIVE_MODEL`. Legacy `API_URL` / `MODEL` either removed or exported as shims; a final grep confirms no other file references the legacy names.
- `state.loadSnapshot` and `state.subscribe` present; `loadEntry` in `app.js` uses them; `exitCompare` bypass trick is gone.
- `js/session-panel.js` and `js/export.js` exist; `js/ui.js` is down to `renderSources`.
- `js/app.js` owns the current `<script type="module">` body; `index.html` contains a single `<script type="module" src="./js/app.js">` tag.
- Markdown export uses block-style YAML frontmatter; a test-written file drops cleanly into an Obsidian vault with the frontmatter recognized.
- Meter visible in pane header; renders "0 / 128,000" at load with default prompt (approx for the system prompt only, which is ~80 tokens).
- Typing in the input updates the meter's numerator approximately live.
- Sending a message → on completion, meter's numerator snaps to the MLX-reported exact value.
- Bar goes amber >75%, red >90%.
- Compare on → Pane B has its own meter; both pull from the same draft textarea.
- `node --test js/*.test.js` reports 38+ tests passing (28 existing + 10 new for tokens + state extensions + stream extension).
- All Phase 1 and Phase 2 behaviors still pass (regression).

## Risks

- **`usage` missing from streaming terminal chunk**: some OpenAI-compatible servers omit it. Mitigation: `meter.setExactPromptTokens` simply isn't called; meter stays on the approximate path. No stuck state.
- **`approxTokens` inaccuracy for non-English**: chars/4 under-counts CJK and over-counts emoji-heavy text. Not a bug; documented limitation. If future models change tokenizer radically, meter only misleads by ±25%.
- **Subscribe cascade**: if every `addUser` fires subscribers that each call DOM-writing code, rapid sends could burst. Mitigation: meter's re-render is already just two `textContent` writes + one style update — cheap. If this becomes a problem we rAF-batch in a follow-up.
- **MODELS map shim collision**: if Phase 4 adds a real model switcher, the legacy `API_URL` / `MODEL` shims will need to go. Fine — they're marked as shims from the start.

## Verification

- Start the stack: `./launch.command`.
- **Regression**:
  - Send a message — streams as before.
  - Compare on/off — both panes stream in parallel.
  - Vault toggle — retrieval + splice works.
  - Save / Load / Delete / Export — all still work.
  - Export output now has block-style `vault: {enabled: ..., topK: ...}` frontmatter.
- **Meter**:
  - Initial load: meter shows `<≈system tokens> / 128,000`, ~1% bar.
  - Type 100 chars in the input: meter ticks up by ~25 tokens.
  - Send: numerator jumps to the exact value MLX reports (visible in DevTools Network response).
  - Stuff the prompt until the bar goes amber, then red — colors change at the 75% / 90% boundaries.
  - Hover the meter: tooltip shows the breakdown.
  - Compare on: Pane B gets its own meter; typing in the shared input updates both.
- **Model-swap smoke** (no new code):
  - Edit `ACTIVE_MODEL_KEY` in `config.js` to a non-existent key. Reload. Expect a clear console error or a graceful fallback (decide in implementation).

## Phase 4+ follow-ups (out of scope for Phase 3)

- Model switcher UI (dropdown of `Object.keys(MODELS)`).
- Multi-origin MODELS entries (OpenAI, Anthropic-via-proxy).
- Automatic context compression (drop oldest turns when >90%).
- Per-turn token badges on individual bubbles.
- Cost estimation once a paid API is in the mix.
- Tokenizer library evaluation if the approximate count becomes consistently misleading.
