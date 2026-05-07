# Prompt Sandbox — Phase 4: Multi-Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `MODELS` registry a runtime surface: each pane owns a `<select>`, Pane A's choice persists across reloads, saved sessions capture per-pane `modelKey`, and meters re-denominate on switch.

**Architecture:** Remove module-level `ACTIVE_MODEL` reference. Runtime state owns `modelKeyA` / `modelKeyB` in `app.js`; `activePanes()` attaches `model: MODELS[key]` per pane; `send.js` reads `model` off the pane; `meter.js` gains `updateContextWindow(n)`; `pane.js` gains a `<select>` + `setModelKey` / `onModelChange`; `sessions.js` gains a testable `resolveModelKey` fallback helper.

**Tech Stack:** Vanilla JS ES modules, zero build, `node --test` for unit tests, manual browser acceptance for DOM modules.

**Spec:** `docs/superpowers/specs/2026-04-18-prompt-sandbox-phase-4-multi-model.md`

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `js/config.js` | modify | Remove `ACTIVE_MODEL_KEY` / `ACTIVE_MODEL`; add `DEFAULT_MODEL_KEY` + `getActiveModelKey()`; add `llama-3-local` entry (T7). |
| `js/tokens.js` | modify | Add `computeUsed({…})` pure fn — the anchor logic that lived in `meter.js`. |
| `js/tokens.test.js` | modify | Add ~5 tests for `computeUsed` paths. |
| `js/meter.js` | modify | Import `computeUsed`; add `updateContextWindow(n)` API; `contextWindow` becomes a mutable local. |
| `js/send.js` | modify | Drop `ACTIVE_MODEL` import. `streamOnePane` takes `model` from pane tuple; `fetch` reads `model.endpoint` / `model.id`. |
| `js/pane.js` | modify | `createPane` accepts `modelKeys` + `initialModelKey`; emits a `<select>` into `.pane-prompt`; exposes `setModelKey` + `onModelChange`. |
| `js/app.js` | modify | Own `modelKeyA` / `modelKeyB`; `activePanes()` returns `{state, pane, model}`; wire select → state + meter + localStorage; `currentSnapshot` / `loadEntry` handle `modelKey`. |
| `js/sessions.js` | modify | Add `resolveModelKey(saved, modelKeys, fallbackKey)` exported helper. |
| `js/sessions.test.js` | modify | Add ~3 tests for `resolveModelKey`. |
| `index.html` | modify | Add `.pane-model-select` style (flex row for select + meter in `.pane-prompt`). |
| `README.md` | modify | Replace "Swapping models" with "Adding providers" (three patterns). |
| `CLAUDE.md` | modify | Update config paragraph to reference `getActiveModelKey` + per-pane selector. |

---

## Task 0: Extract `computeUsed` into `tokens.js`

**Files:**
- Modify: `js/tokens.js`
- Modify: `js/tokens.test.js`
- Modify: `js/meter.js:31-61`

Pure-function extraction of the anchor-correctness logic that landed in Phase 3's meter. Makes the slice/invalidation branches Node-testable. Mechanical refactor; no behavior change.

- [ ] **Step 1: Write failing tests for `computeUsed`**

Append to `js/tokens.test.js`:

```js
import { computeUsed } from "./tokens.js";

test("computeUsed: no anchor → pure approx path", () => {
  const messages = [
    { role: "system", content: "a".repeat(40) },   // 10 + 3 = 13
    { role: "user",   content: "b".repeat(40) },   // 10 + 3 = 13
  ];
  const out = computeUsed({
    exactPromptTokens: 0,
    anchorMessageCount: 0,
    anchorSystemPrompt: null,
    messages,
    systemPrompt: "a".repeat(40),
    draftText: "d".repeat(20),     // 5
  });
  assert.equal(out.used, 13 + 13 + 5);
  assert.equal(out.anchorValid, false);
});

test("computeUsed: anchored and still valid → exact + slice-post-anchor + draft", () => {
  const messages = [
    { role: "system",    content: "sys" },
    { role: "user",      content: "u1" },
    { role: "assistant", content: "a1" },
    { role: "user",      content: "u2".repeat(4) },   // 8 chars → 2 + 3 = 5
  ];
  const out = computeUsed({
    exactPromptTokens: 100,
    anchorMessageCount: 3,          // anchor was set at end of turn 1
    anchorSystemPrompt: "sys",
    messages,
    systemPrompt: "sys",
    draftText: "",
  });
  // 100 (exact) + sumMessages(messages.slice(3)) + 0 draft
  assert.equal(out.used, 100 + 5);
  assert.equal(out.anchorValid, true);
});

test("computeUsed: anchor invalidated when messages shrink below anchor count", () => {
  const messages = [
    { role: "system", content: "sys" },
    { role: "user",   content: "u" },
  ];
  const out = computeUsed({
    exactPromptTokens: 50,
    anchorMessageCount: 4,          // was set when history was longer
    anchorSystemPrompt: "sys",
    messages,
    systemPrompt: "sys",
    draftText: "",
  });
  assert.equal(out.anchorValid, false);
  // Falls back to approx: sumMessages([sys, u]) = (1+3) + (1+3) = 8
  assert.equal(out.used, 8);
});

test("computeUsed: anchor invalidated when systemPrompt changed", () => {
  const messages = [
    { role: "system", content: "new-sys" },
    { role: "user",   content: "u" },
    { role: "assistant", content: "a" },
  ];
  const out = computeUsed({
    exactPromptTokens: 50,
    anchorMessageCount: 2,
    anchorSystemPrompt: "old-sys",
    messages,
    systemPrompt: "new-sys",
    draftText: "",
  });
  assert.equal(out.anchorValid, false);
  assert.equal(out.used, (2+3) + (1+3) + (1+3));   // 12, approx full
});

test("computeUsed: includes draftText in both paths", () => {
  const base = {
    messages: [{ role: "system", content: "sys" }],
    systemPrompt: "sys",
    draftText: "d".repeat(40),      // 10 tokens
  };
  const approx = computeUsed({ ...base, exactPromptTokens: 0, anchorMessageCount: 0, anchorSystemPrompt: null });
  const exact  = computeUsed({ ...base, exactPromptTokens: 100, anchorMessageCount: 1, anchorSystemPrompt: "sys" });
  assert.equal(approx.used, (1+3) + 10);
  assert.equal(exact.used,  100 + 0 + 10);   // nothing after anchor, + draft
});
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `node --test js/tokens.test.js`
Expected: 5 new FAIL with `computeUsed is not a function` or `undefined is not an object`.

- [ ] **Step 3: Implement `computeUsed` in `tokens.js`**

Append to `js/tokens.js`:

```js
export function computeUsed({
  exactPromptTokens,
  anchorMessageCount,
  anchorSystemPrompt,
  messages,
  systemPrompt,
  draftText,
}) {
  const draft = approxTokens(draftText);
  if (exactPromptTokens > 0) {
    const stillAnchored =
      messages.length >= anchorMessageCount &&
      systemPrompt === anchorSystemPrompt;
    if (stillAnchored) {
      return {
        used: exactPromptTokens + sumMessages(messages.slice(anchorMessageCount)) + draft,
        anchorValid: true,
      };
    }
  }
  return {
    used: sumMessages(messages) + draft,
    anchorValid: false,
  };
}
```

- [ ] **Step 4: Run tests, verify all pass**

Run: `node --test js/tokens.test.js`
Expected: 12 pass (7 existing + 5 new), 0 fail.

- [ ] **Step 5: Delegate from `meter.js` to `computeUsed`**

Replace `js/meter.js:1` import:

```js
import { breakdown, computeUsed } from "./tokens.js";
```

(Drop `approxTokens` and `sumMessages` from the import — they're now used only inside `computeUsed`.)

Replace the body of `render()` (currently `js/meter.js:31-61`) with:

```js
  function render() {
    const draftText = typeof getDraftText === "function" ? getDraftText() : "";

    const { used, anchorValid } = computeUsed({
      exactPromptTokens,
      anchorMessageCount,
      anchorSystemPrompt,
      messages:     state.messages,
      systemPrompt: state.systemPrompt,
      draftText,
    });

    // If we had an anchor but the state moved out from under it, clear it so
    // the next setExactPromptTokens starts fresh and the tooltip totalExact
    // stops lying.
    if (exactPromptTokens > 0 && !anchorValid) {
      invalidateAnchor();
    }

    usedEl.textContent = used.toLocaleString();

    const pct = Math.min(100, (used / contextWindow) * 100);
    fillEl.style.width = `${pct.toFixed(1)}%`;

    el.classList.toggle("amber", pct > 75 && pct <= 90);
    el.classList.toggle("red",   pct > 90);

    const b = breakdown({ messages: state.messages, draftText, exactPromptTokens });
    el.title = `system ≈ ${b.system}, history ≈ ${b.history}, draft ≈ ${b.draft}`;
  }
```

- [ ] **Step 6: Run full test suite, verify no regressions**

Run: `node --test js/*.test.js`
Expected: 46 pass (41 existing + 5 new computeUsed), 0 fail.

- [ ] **Step 7: Browser smoke test — meter still works**

Run: `./launch.command` → open `http://localhost:7777`.
Send a message. Verify the meter renders, turns amber/red appropriately, and shows a hover tooltip with `system ≈ N, history ≈ N, draft ≈ N`.

- [ ] **Step 8: Commit**

```bash
git add js/tokens.js js/tokens.test.js js/meter.js
git commit -m "Extract computeUsed into tokens.js with anchor-logic tests"
```

---

## Task 1: `config.js` migration — `DEFAULT_MODEL_KEY` + `getActiveModelKey()`

**Files:**
- Modify: `js/config.js`
- Modify: `js/send.js:4,41-49`
- Modify: `js/app.js:5,35`

Introduces the localStorage-backed active-key indirection. Removes `ACTIVE_MODEL_KEY` and `ACTIVE_MODEL` exports (Phase 3's shim). After this task, no module reads a module-level "active model" — they either take a `model` parameter or call `getActiveModelKey()` + index `MODELS`. Behavior is unchanged because we're still at one model.

- [ ] **Step 1: Update `js/config.js`**

Replace lines 1-10 with:

```js
export const MODELS = {
  "gemma-4-26b": {
    id:            "mlx-community/gemma-4-26B-A4B-it-4bit",
    endpoint:      "http://localhost:8080/v1/chat/completions",
    contextWindow: 128000,
  },
};

export const DEFAULT_MODEL_KEY = "gemma-4-26b";

export function getActiveModelKey() {
  try {
    const saved = localStorage.getItem("promptSandbox.modelKey");
    if (saved && Object.prototype.hasOwnProperty.call(MODELS, saved)) {
      return saved;
    }
    return DEFAULT_MODEL_KEY;
  } catch {
    return DEFAULT_MODEL_KEY;
  }
}
```

(Leave `VAULT_URL`, `STORAGE_KEY`, `DEFAULT_SYSTEM_PROMPT` untouched.)

- [ ] **Step 2: Update `js/send.js`**

Replace line 4:

```js
import { MODELS, getActiveModelKey } from "./config.js";
```

Update `streamOnePane` signature and its fetch (currently `js/send.js:34-50`). The **interim** shape (before T3/T4 per-pane threading) reads from `MODELS[getActiveModelKey()]` each call:

```js
async function streamOnePane({ state, pane, vaultMessage, vaultResults }) {
  const turnMessages = state.buildTurnMessages(vaultMessage);
  const model        = MODELS[getActiveModelKey()];

  const bubble = pane.addBubble("assistant", "Thinking…");
  bubble.classList.add("pending");

  try {
    const res = await fetch(model.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: model.id,
        messages: turnMessages,
        stream: true,
        max_tokens: 4096,
      }),
    });
```

(The rest of the function body is unchanged. T4 will replace this `const model = MODELS[getActiveModelKey()]` line with a parameter.)

- [ ] **Step 3: Update `js/app.js`**

Replace line 5:

```js
import { DEFAULT_SYSTEM_PROMPT, MODELS, getActiveModelKey } from "./config.js";
```

Replace the `attachMeter` body's `contextWindow` line (`js/app.js:35`):

```js
    contextWindow: MODELS[getActiveModelKey()].contextWindow,
```

- [ ] **Step 4: Run full test suite**

Run: `node --test js/*.test.js`
Expected: 46 pass, 0 fail.

- [ ] **Step 5: Browser smoke test**

Run: `./launch.command`. Open app. Verify:
- Page loads without console errors.
- Meter shows `/ 128,000` denominator.
- Sending a message works end-to-end.

- [ ] **Step 6: Commit**

```bash
git add js/config.js js/send.js js/app.js
git commit -m "Migrate config.js to getActiveModelKey() + drop ACTIVE_MODEL exports"
```

---

## Task 2: `meter.updateContextWindow(n)` API

**Files:**
- Modify: `js/meter.js`

Makes the meter's denominator mutable so pane-level model switches can re-denominate without tearing down the meter.

- [ ] **Step 1: Make `contextWindow` a mutable local in `meter.js`**

At `js/meter.js:19-20`, rename the destructured parameter so we can shadow-assign:

Change the top of the function signature + setup (`js/meter.js:3-19`) so the `contextWindow` parameter becomes an internal `let`:

```js
export function createMeter({ pane, state, contextWindow: initialContextWindow, getDraftText }) {
  let contextWindow = initialContextWindow;

  // Insert the meter element into the pane's prompt header area (after the preview).
  const header = pane.section.querySelector(".pane-prompt");
  const el = document.createElement("div");
  el.className = "meter";
  el.innerHTML = `
    <div class="meter-numbers">
      <span class="meter-used">0</span> / <span class="meter-max"></span>
    </div>
    <div class="meter-bar"><div class="meter-fill"></div></div>
  `;
  header.appendChild(el);

  const maxEl  = el.querySelector(".meter-max");
  const usedEl = el.querySelector(".meter-used");
  const fillEl = el.querySelector(".meter-fill");
  maxEl.textContent = contextWindow.toLocaleString();
```

- [ ] **Step 2: Add `updateContextWindow` to the returned object**

Replace the return block (`js/meter.js:66-78`) with:

```js
  return {
    setExactPromptTokens(n) {
      exactPromptTokens  = n;
      anchorMessageCount = state.messages.length;
      anchorSystemPrompt = state.systemPrompt;
      render();
    },
    updateContextWindow(newMax) {
      contextWindow = newMax;
      maxEl.textContent = newMax.toLocaleString();
      render();
    },
    render,
    destroy() {
      unsubState();
      el.remove();
    },
  };
```

- [ ] **Step 3: Run test suite — no regressions**

Run: `node --test js/*.test.js`
Expected: 46 pass, 0 fail. (Meter is DOM-bound; unit coverage unchanged.)

- [ ] **Step 4: Browser smoke test**

Open app. Send a message. In the devtools console:

```js
// Inspect one of the panes and poke the meter.
// (Won't be needed later — this just confirms the API works.)
```

Manual verification: meter renders correctly. The real exercise of `updateContextWindow` comes in Task 5.

- [ ] **Step 5: Commit**

```bash
git add js/meter.js
git commit -m "Meter: add updateContextWindow(n) for live denominator swaps"
```

---

## Task 3: Per-pane `modelKeyA` / `modelKeyB` in `app.js`

**Files:**
- Modify: `js/app.js`

Introduces the runtime state that T4 and T5 consume. `activePanes()` gains a `model` field. Still single-model in practice — no dropdown yet — but the plumbing is per-pane.

- [ ] **Step 1: Add `modelKeyA` / `modelKeyB` and update `activePanes()`**

Replace `js/app.js:11-20` (the pane setup + `activePanes`) with:

```js
// Pane A is always present; Pane B is created lazily by the Compare toggle.
const paneContainer = document.getElementById("pane-container");
const stateA = createPaneState(DEFAULT_SYSTEM_PROMPT);
const paneA  = createPane({ id: "A", container: paneContainer, initialPrompt: DEFAULT_SYSTEM_PROMPT });
let   stateB = null;
let   paneB  = null;

let modelKeyA = getActiveModelKey();
let modelKeyB = null;   // set by enterCompare(); copies modelKeyA

const activePanes = () => paneB
  ? [{ state: stateA, pane: paneA, model: MODELS[modelKeyA] },
     { state: stateB, pane: paneB, model: MODELS[modelKeyB] }]
  : [{ state: stateA, pane: paneA, model: MODELS[modelKeyA] }];
```

- [ ] **Step 2: Update `attachMeter` to use `modelKeyA` for Pane A**

Replace `attachMeter` (`js/app.js:31-44`) with a version that takes a `modelKey`:

```js
function attachMeter(pane, state, modelKey) {
  const meter = createMeter({
    pane,
    state,
    contextWindow: MODELS[modelKey].contextWindow,
    getDraftText: () => $input.value,
  });
  pane.onUsage = (usage) => {
    if (typeof usage.prompt_tokens === "number") {
      meter.setExactPromptTokens(usage.prompt_tokens);
    }
  };
  return meter;
}
```

Update the two callers:

At `js/app.js:56`:
```js
meterA = attachMeter(paneA, stateA, modelKeyA);
```

Inside `enterCompare()` (currently `js/app.js:133`), replace with:
```js
  meterB = attachMeter(paneB, stateB, modelKeyB);
```

- [ ] **Step 3: Initialize `modelKeyB` inside `enterCompare`**

Replace `enterCompare()` (`js/app.js:121-134`) with:

```js
function enterCompare() {
  if (paneB) return;
  modelKeyB = modelKeyA;   // sensible default; user can change Pane B independently
  stateB = createPaneState(DEFAULT_SYSTEM_PROMPT);
  paneB  = createPane({ id: "B", container: paneContainer, initialPrompt: DEFAULT_SYSTEM_PROMPT });
  paneB.applyReset.addEventListener("click", () => {
    stateB.applyPrompt(paneB.textarea.value);
    paneB.clearLog();
    paneB.refreshPreview();
  });
  paneContainer.classList.add("compare");
  $compareToggle.setAttribute("aria-pressed", "true");
  $compareToggle.textContent = "Single";
  meterB = attachMeter(paneB, stateB, modelKeyB);
}
```

Replace `exitCompare()` (`js/app.js:136-150`) — add `modelKeyB = null`:

```js
function exitCompare() {
  if (!paneB) return;
  if (stateB.messages.length > 1) {
    const ok = confirm("Exit compare mode? Pane B's conversation will be discarded.");
    if (!ok) return;
  }
  paneB.section.remove();
  meterB?.destroy();
  meterB    = null;
  paneB     = null;
  stateB    = null;
  modelKeyB = null;
  paneContainer.classList.remove("compare");
  $compareToggle.setAttribute("aria-pressed", "false");
  $compareToggle.textContent = "Compare";
}
```

- [ ] **Step 4: Run test suite**

Run: `node --test js/*.test.js`
Expected: 46 pass, 0 fail.

- [ ] **Step 5: Browser smoke test**

Open app. Verify single-pane still works. Click Compare — verify Pane B appears, meter renders. Send a message — both panes stream. No visible change vs. pre-Task; this is groundwork.

- [ ] **Step 6: Commit**

```bash
git add js/app.js
git commit -m "Per-pane modelKeyA/modelKeyB state; activePanes exposes model"
```

---

## Task 4: `send.js` consumes per-pane `model`

**Files:**
- Modify: `js/send.js`

Removes the `getActiveModelKey` lookup from the hot path — the pane tuple carries its own `model`. This is the first task that puts the new data pipe to work.

- [ ] **Step 1: Update `send.js` imports**

Replace `js/send.js:4`:

```js
// (config.js no longer imported — pane's model comes in as a param)
```

Actually, simply delete the `config.js` import line. The first three imports remain.

- [ ] **Step 2: Update `sendToPanes` to thread `model`**

Replace the end of `sendToPanes` (`js/send.js:30-32`) with:

```js
  // Fire one request per pane in parallel.
  await Promise.all(panes.map(({ state, pane, model }) =>
    streamOnePane({ state, pane, model, vaultMessage, vaultResults })));
}
```

- [ ] **Step 3: Update `streamOnePane` signature and `fetch` body**

Replace the top of `streamOnePane` (`js/send.js:34-50`) with:

```js
async function streamOnePane({ state, pane, model, vaultMessage, vaultResults }) {
  const turnMessages = state.buildTurnMessages(vaultMessage);

  const bubble = pane.addBubble("assistant", "Thinking…");
  bubble.classList.add("pending");

  try {
    const res = await fetch(model.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: model.id,
        messages: turnMessages,
        stream: true,
        max_tokens: 4096,
      }),
    });
```

(The rest of the function body is unchanged. Delete the `const model = MODELS[getActiveModelKey()]` line added in Task 1 Step 2.)

- [ ] **Step 4: Run test suite**

Run: `node --test js/*.test.js`
Expected: 46 pass, 0 fail. (`send.js` has no unit tests — `stream.test.js` covers SSE parsing, not the fetch layer.)

- [ ] **Step 5: Browser smoke test**

Open app. Send single-pane message — verify it streams. Click Compare, send — verify both panes stream against the same endpoint.

- [ ] **Step 6: Commit**

```bash
git add js/send.js
git commit -m "send.js: per-pane model parameter; drop config.js hot-path import"
```

---

## Task 5: Per-pane model dropdown in `pane.js` + wire-up

**Files:**
- Modify: `js/pane.js`
- Modify: `js/app.js`
- Modify: `index.html` (style only)

The visible feature lands here. Each pane gets a native `<select>` in its header, alongside the meter. Change handler updates state + meter + localStorage (A only).

- [ ] **Step 1: Extend `createPane` signature and render the `<select>`**

Replace the `createPane` signature (`js/pane.js:7`):

```js
export function createPane({ id, container, initialPrompt, modelKeys = [], initialModelKey = null }) {
```

Inside `createPane`, after the `applyReset` button is created and **before** `textareaWrap.appendChild(applyReset);` (currently around `js/pane.js:49`), add the select construction:

```js
  const modelSelect = document.createElement("select");
  modelSelect.className = "pane-model-select";
  for (const key of modelKeys) {
    const opt = document.createElement("option");
    opt.value       = key;
    opt.textContent = key;
    if (key === initialModelKey) opt.selected = true;
    modelSelect.appendChild(opt);
  }
```

Mount the select into the pane's collapsed-header row. Insert it into the header **before** the meter will be attached. Find the block at `js/pane.js:50-52`:

```js
  textareaWrap.appendChild(textarea);
  textareaWrap.appendChild(applyReset);
  header.appendChild(preview);
  header.appendChild(textareaWrap);
```

Add one line after:

```js
  header.appendChild(modelSelect);
```

The meter is appended later by `createMeter`; DOM order becomes: `[preview, textareaWrap (collapses), modelSelect, meter]`.

- [ ] **Step 2: Expose `setModelKey`, `onModelChange`, and the element**

Add to the returned object (`js/pane.js:75-121`). Insert these three fields alongside the existing ones:

```js
    modelSelect,

    setModelKey(key) {
      // Programmatic change — does NOT fire onModelChange subscribers.
      modelSelect.value = key;
    },

    onModelChange(fn) {
      // User-initiated changes fire fn(newKey). Programmatic setModelKey does not.
      modelSelect.addEventListener("change", () => fn(modelSelect.value));
    },
```

- [ ] **Step 3: Add minimal CSS for the select**

Add to `index.html` alongside the `.meter` rules (around line 274, inside `<style>`):

```css
  .pane-model-select {
    margin: 4px 14px 0;
    padding: 2px 6px;
    background: #1a1a1a;
    color: var(--fg);
    border: 1px solid var(--border);
    border-radius: 3px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 11px;
  }
```

- [ ] **Step 4: Wire Pane A's select at construction time in `app.js`**

Replace the Pane A `createPane` call (`js/app.js:14`):

```js
const paneA = createPane({
  id:              "A",
  container:       paneContainer,
  initialPrompt:   DEFAULT_SYSTEM_PROMPT,
  modelKeys:       Object.keys(MODELS),
  initialModelKey: modelKeyA,
});
```

Move this line **after** `let modelKeyA = getActiveModelKey();` so `modelKeyA` is defined at the callsite. The final order in `app.js`:

```js
const paneContainer = document.getElementById("pane-container");
const stateA = createPaneState(DEFAULT_SYSTEM_PROMPT);
let   stateB = null;
let   paneB  = null;

let modelKeyA = getActiveModelKey();
let modelKeyB = null;

const paneA = createPane({
  id:              "A",
  container:       paneContainer,
  initialPrompt:   DEFAULT_SYSTEM_PROMPT,
  modelKeys:       Object.keys(MODELS),
  initialModelKey: modelKeyA,
});

const activePanes = () => paneB
  ? [{ state: stateA, pane: paneA, model: MODELS[modelKeyA] },
     { state: stateB, pane: paneB, model: MODELS[modelKeyB] }]
  : [{ state: stateA, pane: paneA, model: MODELS[modelKeyA] }];
```

- [ ] **Step 5: Wire change handler for Pane A after meter attach**

Immediately after `meterA = attachMeter(paneA, stateA, modelKeyA);` (in the module body, not inside a function), add:

```js
paneA.onModelChange((newKey) => {
  modelKeyA = newKey;
  meterA.updateContextWindow(MODELS[newKey].contextWindow);
  try {
    localStorage.setItem("promptSandbox.modelKey", newKey);
  } catch { /* storage disabled — in-session change still works */ }
});
```

- [ ] **Step 6: Wire Pane B at `enterCompare` time**

Replace `enterCompare` (written in Task 3) with:

```js
function enterCompare() {
  if (paneB) return;
  modelKeyB = modelKeyA;
  stateB = createPaneState(DEFAULT_SYSTEM_PROMPT);
  paneB  = createPane({
    id:              "B",
    container:       paneContainer,
    initialPrompt:   DEFAULT_SYSTEM_PROMPT,
    modelKeys:       Object.keys(MODELS),
    initialModelKey: modelKeyB,
  });
  paneB.applyReset.addEventListener("click", () => {
    stateB.applyPrompt(paneB.textarea.value);
    paneB.clearLog();
    paneB.refreshPreview();
  });
  paneContainer.classList.add("compare");
  $compareToggle.setAttribute("aria-pressed", "true");
  $compareToggle.textContent = "Single";
  meterB = attachMeter(paneB, stateB, modelKeyB);
  paneB.onModelChange((newKey) => {
    modelKeyB = newKey;
    meterB.updateContextWindow(MODELS[newKey].contextWindow);
    // B is not persisted on purpose (spec §1).
  });
}
```

- [ ] **Step 7: Run test suite**

Run: `node --test js/*.test.js`
Expected: 46 pass, 0 fail.

- [ ] **Step 8: Browser acceptance — dropdown behavior**

Open app. Verify:
- Pane A has a dropdown showing `gemma-4-26b` (the only entry).
- Enter Compare — Pane B has its own dropdown defaulted to `gemma-4-26b`.
- (With only one entry in MODELS, switching is a no-op; a second entry arrives in T7 to exercise this fully.)

Open devtools → Application → Local Storage and look at `promptSandbox.modelKey` — should not exist yet (default path). Temporarily add a second MODELS entry in `js/config.js` (revert before commit), reload, switch Pane A's dropdown, and verify:
- Storage now shows `promptSandbox.modelKey` with the new value.
- Meter denominator updates.
- Reload — Pane A defaults to the stored key.

Revert the temporary MODELS entry if you added one. (T7 adds the real second entry.)

- [ ] **Step 9: Commit**

```bash
git add js/pane.js js/app.js index.html
git commit -m "Per-pane model dropdown; Pane A choice persists to localStorage"
```

---

## Task 6: Sessions persistence of `modelKey`

**Files:**
- Modify: `js/sessions.js`
- Modify: `js/sessions.test.js`
- Modify: `js/app.js`

Saved sessions gain per-pane `modelKey`. Legacy entries (Phase 3) and entries with unknown keys degrade gracefully via a new testable `resolveModelKey` helper.

- [ ] **Step 1: Write failing tests for `resolveModelKey`**

Append to `js/sessions.test.js`:

```js
import { resolveModelKey } from "./sessions.js";

test("resolveModelKey: known key passes through", () => {
  const out = resolveModelKey("gemma-4-26b", ["gemma-4-26b", "llama-3-local"], "gemma-4-26b");
  assert.equal(out, "gemma-4-26b");
});

test("resolveModelKey: missing key returns fallback without warn", (t) => {
  t.mock.method(console, "warn", () => {});
  const out = resolveModelKey(undefined, ["gemma-4-26b"], "gemma-4-26b");
  assert.equal(out, "gemma-4-26b");
  assert.equal(console.warn.mock.callCount(), 0);
});

test("resolveModelKey: unknown key returns fallback and warns", (t) => {
  t.mock.method(console, "warn", () => {});
  const out = resolveModelKey("llama-3-local", ["gemma-4-26b"], "gemma-4-26b");
  assert.equal(out, "gemma-4-26b");
  assert.equal(console.warn.mock.callCount(), 1);
});
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `node --test js/sessions.test.js`
Expected: 3 new FAIL with `resolveModelKey is not a function`.

- [ ] **Step 3: Implement `resolveModelKey` in `sessions.js`**

Append to `js/sessions.js`:

```js
export function resolveModelKey(saved, modelKeys, fallbackKey) {
  if (saved && modelKeys.includes(saved)) return saved;
  if (saved) {
    console.warn(`Unknown modelKey "${saved}" in saved session; falling back to "${fallbackKey}"`);
  }
  return fallbackKey;
}
```

- [ ] **Step 4: Run tests, verify all pass**

Run: `node --test js/*.test.js`
Expected: 49 pass, 0 fail.

- [ ] **Step 5: Include `modelKey` in `currentSnapshot` in `app.js`**

Replace `currentSnapshot` (`js/app.js:177-187`) with:

```js
function currentSnapshot() {
  const perPaneKey = [modelKeyA, modelKeyB];
  const panes = activePanes().map(({ state }, idx) => ({
    systemPrompt: state.systemPrompt,
    messages:     [...state.messages],
    modelKey:     perPaneKey[idx],
  }));
  const vaultConfig = {
    enabled: $useVault.checked,
    topK:    Math.max(1, Math.min(20, parseInt($topK.value, 10) || 5)),
  };
  return { panes, vaultConfig };
}
```

- [ ] **Step 6: Restore `modelKey` in `loadEntry` in `app.js`**

Update the import at `js/app.js:8`:

```js
import { createSessionsStore, resolveModelKey } from "./sessions.js";
```

Replace the body of `loadEntry` (`js/app.js:189-238`) with:

```js
function loadEntry(entry) {
  const paneCount = entry.panes.length;
  const modelKeys = Object.keys(MODELS);
  const fallback  = getActiveModelKey();

  const keyA = resolveModelKey(entry.panes[0].modelKey, modelKeys, fallback);
  const keyB = paneCount > 1
    ? resolveModelKey(entry.panes[1].modelKey, modelKeys, fallback)
    : null;

  if (paneCount === 1) {
    if (paneB && stateB && stateB.messages.length > 1) {
      const ok = confirm("Loading this session will exit compare mode and discard Pane B's conversation. Continue?");
      if (!ok) return;
    }
    if (paneB) {
      stateB.loadSnapshot({
        systemPrompt: stateB.systemPrompt,
        messages: [{ role: "system", content: stateB.systemPrompt }],
      });
      exitCompare();
    }
    stateA.loadSnapshot({
      systemPrompt: entry.panes[0].systemPrompt,
      messages: [...entry.panes[0].messages],
    });
    paneA.textarea.value = entry.panes[0].systemPrompt;
    paneA.refreshPreview();
    paneA.renderFromMessages(stateA.messages);

    // Apply modelKey for Pane A: update runtime, selector, meter, and persist.
    modelKeyA = keyA;
    paneA.setModelKey(keyA);
    meterA.updateContextWindow(MODELS[keyA].contextWindow);
    try { localStorage.setItem("promptSandbox.modelKey", keyA); } catch { /* ignore */ }
  } else {
    if (!paneB) enterCompare();
    stateA.loadSnapshot({
      systemPrompt: entry.panes[0].systemPrompt,
      messages: [...entry.panes[0].messages],
    });
    paneA.textarea.value = entry.panes[0].systemPrompt;
    paneA.refreshPreview();
    paneA.renderFromMessages(stateA.messages);

    stateB.loadSnapshot({
      systemPrompt: entry.panes[1].systemPrompt,
      messages: [...entry.panes[1].messages],
    });
    paneB.textarea.value = entry.panes[1].systemPrompt;
    paneB.refreshPreview();
    paneB.renderFromMessages(stateB.messages);

    modelKeyA = keyA;
    paneA.setModelKey(keyA);
    meterA.updateContextWindow(MODELS[keyA].contextWindow);
    try { localStorage.setItem("promptSandbox.modelKey", keyA); } catch { /* ignore */ }

    modelKeyB = keyB;
    paneB.setModelKey(keyB);
    meterB.updateContextWindow(MODELS[keyB].contextWindow);
  }

  $useVault.checked = !!entry.vaultConfig?.enabled;
  $topK.value       = String(entry.vaultConfig?.topK ?? 5);

  sessionPanel.close();
}
```

- [ ] **Step 7: Run full test suite**

Run: `node --test js/*.test.js`
Expected: 49 pass, 0 fail.

- [ ] **Step 8: Browser acceptance — save/load round-trip**

1. Open app, send a message, save session "sp-test-a".
2. Refresh the page — live state resets.
3. Load "sp-test-a" — messages restore; Pane A's model is `gemma-4-26b`; meter at `/128,000`.
4. Enter Compare, send a message in both panes, save "sp-test-ab".
5. Reload, load "sp-test-ab" — both panes restore with messages and models.
6. In devtools, manually inject a legacy entry (drop `modelKey` from `panes[0]`) into `localStorage["promptSandbox.sessions"]`. Load it — verify no crash, pane loads with fallback. (This is also covered by the unit test.)
7. In devtools, inject an entry with `modelKey: "nonexistent-model"`. Load — verify `console.warn` fires and fallback applies.

- [ ] **Step 9: Commit**

```bash
git add js/sessions.js js/sessions.test.js js/app.js
git commit -m "Sessions: persist per-pane modelKey with resolveModelKey fallback"
```

---

## Task 7: Docs + second MODELS entry

**Files:**
- Modify: `js/config.js`
- Modify: `README.md`
- Modify: `CLAUDE.md`

Ship the example second model so the dropdown has something to switch between. Rewrite the README's model-swap section to cover local servers, proxied cloud, and OpenAI-compatible shape.

- [ ] **Step 1: Add `llama-3-local` to `MODELS`**

Update `js/config.js` `MODELS`:

```js
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

- [ ] **Step 2: Rewrite README's "Swapping models" → "Adding providers"**

Find the "Swapping models" section in `README.md` (run `grep -n "Swapping models" README.md` to locate). Replace that section with:

```markdown
## Adding providers

The UI speaks **only** OpenAI-compatible `/v1/chat/completions` with SSE streaming over HTTP to a local endpoint. Any provider you want to use has to fit that shape and has to be reachable from the browser with permissive CORS.

Three patterns:

### 1. Local OpenAI-compatible server (MLX, llama.cpp, vLLM)

Drop a new entry into `MODELS` in `js/config.js` pointing at the server's port. Example for llama.cpp running on 8091:

```js
"llama-3-local": {
  id:            "meta-llama/Meta-Llama-3-8B-Instruct",
  endpoint:      "http://localhost:8091/v1/chat/completions",
  contextWindow: 8192,
},
```

The server must run with permissive CORS. For `llama-server`:

```bash
llama-server --model path/to/model.gguf --port 8091 --host 127.0.0.1
```

(llama-server allows all origins by default. For `mlx_lm.server` use `--allowed-origins "*"`, already set in `_run-mlx.sh`.)

### 2. Cloud via local proxy (OpenAI, Anthropic, any API key)

The browser can't talk to `api.openai.com` directly — API keys don't belong in a browser, and CORS would block it anyway. Run a small local proxy that holds the key and speaks OpenAI shape to `localhost`. [LiteLLM](https://github.com/BerriAI/litellm) is the simplest option:

```bash
pip install 'litellm[proxy]'
litellm --model openai/gpt-4o --port 8090
```

Then in `MODELS`:

```js
"gpt-4o-via-litellm": {
  id:            "openai/gpt-4o",
  endpoint:      "http://localhost:8090/v1/chat/completions",
  contextWindow: 128000,
},
```

If your proxy blocks browser CORS, add `--config` with an allow-origins setting or front it with a tiny CORS-adding shim.

### 3. Native Anthropic via proxy

Same as (2). LiteLLM translates Anthropic's API to OpenAI shape so the browser sees a consistent contract:

```bash
litellm --model claude-opus-4-7 --port 8092
```

```js
"claude-opus-4-7-via-litellm": {
  id:            "claude-opus-4-7",
  endpoint:      "http://localhost:8092/v1/chat/completions",
  contextWindow: 200000,
},
```

### Switching at runtime

Each pane's header has a dropdown listing every `MODELS` key. Pane A's choice is persisted to `localStorage` across reloads. Pane B (Compare mode) defaults to Pane A's current choice and is transient.
```

- [ ] **Step 3: Update `CLAUDE.md`**

Find the "Key conventions" bullet referencing model swaps (around line 41). Replace:

> **Config lives in `js/config.js`** — `MODELS` map + `ACTIVE_MODEL_KEY` + `ACTIVE_MODEL`, plus `VAULT_URL`, `STORAGE_KEY`, `DEFAULT_SYSTEM_PROMPT`. Swap models by changing `ACTIVE_MODEL_KEY`. `send.js` reads `ACTIVE_MODEL.id` / `.endpoint`; `meter.js` reads `.contextWindow`.

with:

> **Config lives in `js/config.js`** — `MODELS` map + `DEFAULT_MODEL_KEY` + `getActiveModelKey()`, plus `VAULT_URL`, `STORAGE_KEY`, `DEFAULT_SYSTEM_PROMPT`. Each pane owns a `modelKey` (Pane A's persists to `localStorage["promptSandbox.modelKey"]`); the header dropdown in `pane.js` is the runtime UI. `send.js` takes `model` per pane from `activePanes()`; `meter.js` reads `.contextWindow` at construction and allows live updates via `updateContextWindow(n)`.

Also add to the Key conventions list (as a new bullet):

> - **Per-pane model picker is in the pane's header DOM** — pane.js exposes `modelSelect`, `setModelKey` (programmatic, no event), `onModelChange(fn)` (user change). App.js wires Pane A's change to localStorage + meter; Pane B is in-session only.

- [ ] **Step 4: Run test suite**

Run: `node --test js/*.test.js`
Expected: 49 pass, 0 fail.

- [ ] **Step 5: Browser acceptance — two-model dropdown**

Open app. Verify the Pane A dropdown now lists **both** keys. Switch to `llama-3-local` — the meter denominator should change from 128,000 to 8,192. Open devtools Storage — `promptSandbox.modelKey` should be `llama-3-local`. Reload — Pane A defaults to `llama-3-local`.

Switch back to `gemma-4-26b` to leave the environment in the expected state.

(No actual llama.cpp server needs to be running; sending against `llama-3-local` will fail with a network error in the bubble, which is expected and fine for this smoke test.)

- [ ] **Step 6: Commit**

```bash
git add js/config.js README.md CLAUDE.md
git commit -m "Docs + llama-3-local example; 'Adding providers' patterns"
```

---

## Task 8: Full acceptance + code review

**Files:** no code changes — verification and review.

- [ ] **Step 1: Run the entire acceptance criteria list from the spec**

Work through each bullet from the spec's "Acceptance criteria" section. Tick each one off mentally or on paper. The key points:

1. Page load: Pane A's dropdown shows both MODELS keys, selected from localStorage or `DEFAULT_MODEL_KEY`. ✓
2. Switching Pane A's model updates the meter denominator and persists. ✓
3. Reload restores Pane A's last selection. ✓
4. Compare on: Pane B dropdown defaults to Pane A's current selection. ✓
5. Different per-pane models: one send fires one request per pane against respective endpoints. Test by setting Pane A to `gemma-4-26b`, Pane B to `llama-3-local` (will error in B since no llama-server running — **that's fine**); observe A streams and B errors with HTTP error. Network tab should show two requests to different ports.
6. Save → reload → load restores both panes' model + prompt + messages.
7. Phase 3 saved sessions (no `modelKey`) load with fallback. (Manually inject a session JSON without `modelKey` to test.)
8. Entry with unknown `modelKey` falls back with `console.warn`; doesn't crash.

- [ ] **Step 2: Run full test suite**

Run: `node --test js/*.test.js`
Expected: 49 pass, 0 fail.

- [ ] **Step 3: Invoke requesting-code-review skill**

Use the `superpowers:requesting-code-review` skill to spawn a reviewer against the cumulative Phase 4 diff (commits from T0 through T7 on this branch, compared to the pre-Phase-4 tip). The reviewer should verify:

- No `ACTIVE_MODEL` or `ACTIVE_MODEL_KEY` references anywhere.
- `send.js` no longer imports from `config.js`.
- `meter.js` no longer imports `approxTokens` or `sumMessages` directly.
- All acceptance criteria from the spec have corresponding code.
- No placeholder comments, dead code, or `TODO`s.

- [ ] **Step 4: Address any review findings**

Follow the `superpowers:receiving-code-review` skill. Fix anything that's a genuine issue; defend anything that's a preference collision.

- [ ] **Step 5: Final commit if any review fixes**

Only if Step 4 produced changes:

```bash
git add -A
git commit -m "Phase 4 review fixes"
```

---

## Risks & mitigations

(From the spec — reproduced here so the executing agent has them in one place.)

- **Live model switching mid-send**: the dropdown change doesn't interrupt an in-flight stream. The change takes effect on the *next* send. No code needed; behavior is emergent from the existing design.
- **Cloud-proxy CORS**: users following the README's proxy pattern need permissive CORS on their proxy. README calls this out.
- **`MODELS` key removed while saved sessions reference it**: `resolveModelKey` falls back with `console.warn`. Covered by Task 6.
- **Per-pane endpoint latency variance**: `Promise.all` waits for the slowest. Acceptable — each pane's meter updates independently as its own stream completes.
