# Prompt Sandbox Phase 2 — Persistence Cluster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a unified Sessions list (save / load / delete of prompt + optional messages) with Markdown export and A/B-aware restore, backed by `localStorage`. Fix the two Phase 1 carry-forward bugs and do the two structural cleanups that unblock Phase 3.

**Architecture:** A new `js/sessions.js` module factored as a storage-injected store (`createSessionsStore(storage)`) exposes four CRUD operations and has node-native tests against a fake storage. A new `js/pane.js` owns per-pane DOM (split out of `ui.js`) and gains a `renderFromMessages(messages)` helper used on load. A new `js/config.js` centralizes constants. `js/ui.js` keeps `renderSources` and gains `renderSessionPanel` plus Markdown-export helpers. The entry block in `index.html` wires the Sessions ▾ dropdown to the store + panel.

**Tech Stack:** Vanilla JavaScript (ES modules), CSS custom properties, `localStorage`, Node 22 `node:test` + `node:assert/strict`. No package.json, no npm, no build.

**Spec:** `docs/superpowers/specs/2026-04-18-prompt-sandbox-phase-2-persistence.md`.

---

## File layout after this plan

```
prompt-sandbox/
├── index.html                 ← markup + styles + entry <script type="module">
├── js/
│   ├── config.js              ← NEW: constants (API_URL, MODEL, VAULT_URL, DEFAULT_SYSTEM_PROMPT, STORAGE_KEY)
│   ├── stream.js              ← unchanged
│   ├── stream.test.js         ← unchanged
│   ├── state.js               ← extended: popLastUser()
│   ├── state.test.js          ← extended: popLastUser test
│   ├── vault.js               ← unchanged public API; imports VAULT_URL from config.js
│   ├── pane.js                ← NEW: createPane + oneLinePreview + renderFromMessages (split from ui.js)
│   ├── ui.js                  ← trimmed: keeps renderSources; gains renderSessionPanel + exportToMarkdown helpers
│   ├── send.js                ← fixes: I-1 catch, I-2 empty-stream; imports from config.js
│   ├── sessions.js            ← NEW: createSessionsStore factory
│   └── sessions.test.js       ← NEW: node --test against a FakeStorage
```

## Task-map back to spec

| Spec section | Implementing task |
|---|---|
| §1 Data model / storage | 4 |
| §2 UI surface (panel) | 5 |
| §3 Save | 6 |
| §3 Load (A/B-aware) | 7 |
| §3 Delete | 8 |
| §4 Export | 9 |
| §5 Task-0 pre-work: I-1 | 0 |
| §5 Task-0 pre-work: I-2 | 1 |
| §5 Task-0 pre-work: config.js | 2 |
| §5 Task-0 pre-work: ui.js split | 3 |
| §6 sessions.js module | 4 |
| §7 Testing plan | 4 (sessions.test) + 0 (state.test) |
| Acceptance criteria | 10 |

---

## Task 0: Fix I-1 — pop dangling user message on stream failure (TDD)

**Why:** The Phase 1 final code review flagged that `state.addUser(userText)` runs in `sendToPanes` before the fetch, but `state.addAssistant` only runs on success. A fetch failure leaves `state.messages` ending with a user turn and no assistant reply, which poisons subsequent sends and will corrupt exported conversations. Phase 2 must fix this before export lands.

**Files:**
- Modify: `js/state.js` — add `popLastUser()` method.
- Modify: `js/state.test.js` — add a test.
- Modify: `js/send.js` — call `state.popLastUser()` inside `streamOnePane`'s catch, after writing the error bubble.

**Steps:**

- [ ] **Step 1: Write the failing test**

Append to `js/state.test.js`:

```javascript
test("popLastUser removes only a trailing user message", () => {
  const s = createPaneState("sp");
  s.addUser("hi");
  s.addAssistant("ok");
  s.addUser("second");
  // Messages: [system, user, assistant, user]
  assert.equal(s.popLastUser(), true);
  assert.deepEqual(s.messages, [
    { role: "system", content: "sp" },
    { role: "user", content: "hi" },
    { role: "assistant", content: "ok" },
  ]);
  // Next pop should be a no-op (tail is assistant, not user).
  assert.equal(s.popLastUser(), false);
  assert.equal(s.messages.length, 3);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `node --test js/state.test.js`
Expected: the new test fails with `s.popLastUser is not a function`.

- [ ] **Step 3: Implement popLastUser**

In `js/state.js`, add inside the returned object (anywhere among the methods):

```javascript
popLastUser() {
  const last = this.messages[this.messages.length - 1];
  if (!last || last.role !== "user") return false;
  this.messages.pop();
  return true;
},
```

- [ ] **Step 4: Run tests**

Run: `node --test js/*.test.js`
Expected: 17 pass / 0 fail.

- [ ] **Step 5: Wire into send.js**

In `js/send.js`'s `streamOnePane`, the catch block currently is:

```javascript
} catch (err) {
  bubble.classList.add("error");
  bubble.textContent = `⚠ ${err.message}`;
}
```

Change to:

```javascript
} catch (err) {
  bubble.classList.add("error");
  bubble.textContent = `⚠ ${err.message}`;
  state.popLastUser();
}
```

- [ ] **Step 6: Sanity-check**

Run: `node --check js/send.js && node --test js/*.test.js 2>&1 | tail -5`
Expected: syntax OK, 17/17 pass.

- [ ] **Step 7: Commit**

```bash
git add js/state.js js/state.test.js js/send.js
git commit -m "$(cat <<'EOF'
Fix I-1: pop dangling user message on stream failure

Phase 1 final review flagged that sendToPanes calls state.addUser before
the fetch, but state.addAssistant only runs on success. A thrown fetch
leaves a user turn in state.messages with no assistant reply, which
poisons subsequent sends and will appear in Phase 2's Markdown exports.

Adds state.popLastUser() (no-op when tail is not a user turn) and calls
it from streamOnePane's catch after writing the error bubble. The
visible error bubble remains so the user sees what happened; the state
is left sendable again.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 1: Fix I-2 — empty-stream [DONE] no longer sticks in "Thinking…"

**Why:** If the model returns `[DONE]` with zero content/reasoning deltas (rare but real for misconfigured max_tokens, server aborts, or certain prompt injections), `initSpans()` never runs and the pending bubble pulses forever. `state.addAssistant("")` also pushes an empty message into history.

**Files:**
- Modify: `js/send.js` — post-loop guard inside `streamOnePane`.

**Steps:**

- [ ] **Step 1: Add the guard in send.js**

In `js/send.js`, find the section where the stream loop finishes and we call `state.addAssistant(content || reasoning)`. Currently:

```javascript
// Flush the decoder's internal state and any residual event.
buffer += decoder.decode();
if (buffer.trim()) {
  const { events } = parseSSEBuffer(buffer + "\n\n");
  applyEvents(events);
}

state.addAssistant(content || reasoning);
if (vaultResults) renderSources(bubble, vaultResults);
```

Change the final three lines to:

```javascript
state.addAssistant(content || reasoning);
if (!reasoningEl) {
  // [DONE] arrived with zero deltas — keep the bubble visible but not spinning.
  bubble.classList.remove("pending");
  bubble.textContent = "(empty response)";
}
if (vaultResults) renderSources(bubble, vaultResults);
```

Note: `state.addAssistant(content || reasoning)` with both empty strings becomes `state.addAssistant("")`. That's acceptable — the history line is honest (the assistant gave nothing) and `popLastUser()` from Task 0 isn't appropriate here (there was no exception). The exported Markdown for this case will show `**Assistant:**` followed by an empty line, which is accurate.

- [ ] **Step 2: Sanity-check**

Run: `node --check js/send.js && node --test js/*.test.js 2>&1 | tail -5`
Expected: syntax OK, 17/17 pass.

- [ ] **Step 3: Commit**

```bash
git add js/send.js
git commit -m "$(cat <<'EOF'
Fix I-2: empty-stream [DONE] no longer sticks in "Thinking…"

If the model ends with [DONE] and emitted no content/reasoning deltas,
initSpans() never ran, so the pending bubble kept pulsing forever. Now,
after the final buffer flush, if no spans were created, clear the
pending class and set the bubble text to "(empty response)".

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Create js/config.js — centralize constants

**Why:** Phase 1 left `API_URL` / `MODEL` in `send.js`, `VAULT_URL` in `vault.js`, and `DEFAULT_SYSTEM_PROMPT` in `index.html`. Phase 2 adds `STORAGE_KEY`. Phase 3 will add a context-window size for the meter. Centralizing now avoids cross-module imports just for a constant.

**Files:**
- Create: `js/config.js`
- Modify: `js/send.js`, `js/vault.js`, `index.html` — import from `config.js`.

**Steps:**

- [ ] **Step 1: Create js/config.js**

```javascript
export const API_URL   = "http://localhost:8080/v1/chat/completions";
export const MODEL     = "mlx-community/gemma-4-26B-A4B-it-4bit";
export const VAULT_URL = "http://localhost:8100";

export const STORAGE_KEY = "promptSandbox.sessions";

export const DEFAULT_SYSTEM_PROMPT = `Role: You are my Lead Strategic Advisor and Decision Scientist.
Objective: Help me reach better conclusions by identifying my blind spots and logical fallacies.
Protocol:
Steel-manning: Before critiquing, summarize my argument back to me to prove you understand it perfectly.
Pre-Mortem: If I propose a plan, tell me three specific ways it could realistically fail in 12 months.
Inversion: Ask me, "What would I have to do to ensure this project fails?" to help me avoid those pitfalls.
Occam's Razor: Challenge me to find the simplest possible version of my idea.
Second-Order Effects: Always ask "And then what?" to explore the long-term consequences of my choice.
Tone: Brutally honest, intellectually rigorous, and concise. No fluff.`;
```

- [ ] **Step 2: Update js/send.js to import from config**

Replace the top of `js/send.js`:

```javascript
import { parseSSEBuffer, extractSSEDelta } from "./stream.js";
import { fetchVaultContext }                from "./vault.js";
import { renderSources }                    from "./ui.js";

const API_URL = "http://localhost:8080/v1/chat/completions";
const MODEL   = "mlx-community/gemma-4-26B-A4B-it-4bit";
```

With:

```javascript
import { parseSSEBuffer, extractSSEDelta } from "./stream.js";
import { fetchVaultContext }                from "./vault.js";
import { renderSources }                    from "./ui.js";
import { API_URL, MODEL }                   from "./config.js";
```

- [ ] **Step 3: Update js/vault.js to import from config**

Replace:

```javascript
const VAULT_URL = "http://localhost:8100";
```

With:

```javascript
import { VAULT_URL } from "./config.js";
```

(Place the import at the top of the file.)

- [ ] **Step 4: Update index.html to import DEFAULT_SYSTEM_PROMPT**

In the `<script type="module">` block, replace the existing inline `const DEFAULT_SYSTEM_PROMPT = \`…\`;` declaration with an import at the top of the script block:

```javascript
import { DEFAULT_SYSTEM_PROMPT } from "./js/config.js";
```

Add this after the existing imports (`createPaneState`, `createPane`, `sendToPanes`, `pingVaultHealth`, `reindexVault`).

Then delete the old inline `DEFAULT_SYSTEM_PROMPT` template-literal block.

- [ ] **Step 5: Sanity-check**

```bash
node --check js/config.js && node --check js/send.js && node --check js/vault.js && echo "all syntax ok"
node --test js/*.test.js 2>&1 | tail -5
curl -s http://localhost:7777/ | grep -c "DEFAULT_SYSTEM_PROMPT"
# Expected: 1 (import only — no inline declaration)
curl -s http://localhost:7777/js/config.js | grep -c "DEFAULT_SYSTEM_PROMPT"
# Expected: 1 (the export)
```

- [ ] **Step 6: Manual browser smoke check**

Hard-refresh `http://localhost:7777/`. Default prompt still shows; sends still work; vault toggle still works. No console errors.

- [ ] **Step 7: Commit**

```bash
git add js/config.js js/send.js js/vault.js index.html
git commit -m "$(cat <<'EOF'
Create js/config.js to centralize constants

Hoists API_URL, MODEL, VAULT_URL, and DEFAULT_SYSTEM_PROMPT into one
module, adds STORAGE_KEY for Phase 2, and rewires send.js, vault.js,
and index.html to import from it. No behavior change; preps the single
import point Phase 3's context-window meter will also use.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Split js/ui.js → js/pane.js (and add renderFromMessages)

**Why:** `js/ui.js` mixes per-pane DOM (`createPane`, `oneLinePreview`) with the render-sources helper. Phase 2 adds session-panel and Markdown-export helpers that don't belong with per-pane DOM. Split now keeps ui.js focused. Also add the `renderFromMessages` method to the pane handle, needed by Task 7's load flow.

**Files:**
- Create: `js/pane.js`
- Modify: `js/ui.js`
- Modify: `index.html` — update imports.

**Steps:**

- [ ] **Step 1: Create js/pane.js with createPane + oneLinePreview**

Move the existing `oneLinePreview` and `createPane` code verbatim from `js/ui.js` into a new `js/pane.js`. After the move, `js/pane.js` should start with:

```javascript
function oneLinePreview(text) {
  const firstLine = text.split("\n", 1)[0].trim();
  if (firstLine.length <= 60) return firstLine || "(empty prompt — click to edit)";
  return firstLine.slice(0, 57) + "…";
}

export function createPane({ id, container, initialPrompt }) {
  // ... existing body ...
}
```

**IMPORTANT**: Inside `createPane`, the `addBubble` / `addLogNote` / `clearLog` methods currently live on the returned object. Add a new `renderFromMessages(messages)` method that rebuilds the log from an array of `{role, content}` objects:

Insert this into the returned object **after** `clearLog`:

```javascript
renderFromMessages(messages) {
  log.innerHTML = "";
  for (const msg of messages) {
    if (msg.role === "system") continue;   // system message is the prompt, rendered in the header not the log
    this.addBubble(msg.role, msg.content);
  }
},
```

Note: `this.addBubble(...)` requires the method to be called via the handle. Because we're inside an object literal where `addBubble` is also defined as a shorthand method, `this` is bound correctly at call time. If the pane handle is ever destructured (`const { renderFromMessages } = pane`), this `this` binding breaks — callers must always invoke as `pane.renderFromMessages(...)`.

- [ ] **Step 2: Update js/ui.js — keep only renderSources**

`js/ui.js` should now contain only:

```javascript
export function renderSources(bubble, results) {
  const line = document.createElement("span");
  line.className = "sources";
  line.appendChild(document.createTextNode("Sources: "));
  results.forEach((r, i) => {
    const name = r.path.split("/").pop();
    const item = document.createElement("span");
    item.textContent = name;
    item.title       = r.snippet;
    line.appendChild(item);
    if (i < results.length - 1) line.appendChild(document.createTextNode(", "));
  });
  bubble.appendChild(line);
}
```

Remove the `createPane` and `oneLinePreview` that now live in `pane.js`.

- [ ] **Step 3: Update js/send.js import**

`js/send.js` imports `renderSources` from `./ui.js` — unchanged.

- [ ] **Step 4: Update index.html import**

In the `<script type="module">` block, change:

```javascript
import { createPane } from "./js/ui.js";
```

To:

```javascript
import { createPane } from "./js/pane.js";
```

- [ ] **Step 5: Sanity-check**

```bash
node --check js/pane.js && node --check js/ui.js && echo "syntax ok"
node --test js/*.test.js 2>&1 | tail -5
# Expected: 17/17 pass (unchanged)
curl -s http://localhost:7777/js/pane.js | head -5
curl -s http://localhost:7777/js/ui.js | head -5
```

- [ ] **Step 6: Manual browser smoke check**

Hard-refresh `http://localhost:7777/`. Pane renders, Compare still works, send still works, sources chips still render. No console errors.

- [ ] **Step 7: Commit**

```bash
git add js/pane.js js/ui.js index.html
git commit -m "$(cat <<'EOF'
Split js/pane.js out of js/ui.js; add renderFromMessages

Moves createPane + oneLinePreview into their own module so ui.js can
grow session-panel and export helpers without co-mingling with per-pane
DOM. Pane handle gains renderFromMessages(messages) which clears the
log and replays non-system messages via addBubble — used by Task 7's
session load flow to restore a saved conversation without re-streaming.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Create js/sessions.js (factory + tests)

**Why:** This is the persistence layer. TDD-able because the entire module is storage I/O + array ops; we inject a fake storage in tests.

**Files:**
- Create: `js/sessions.js`
- Create: `js/sessions.test.js`

**Steps:**

- [ ] **Step 1: Write the failing tests**

Create `js/sessions.test.js`:

```javascript
import { test } from "node:test";
import assert from "node:assert/strict";
import { createSessionsStore } from "./sessions.js";

class FakeStorage {
  constructor(seed = {}) { this.data = { ...seed }; }
  getItem(k)       { return Object.prototype.hasOwnProperty.call(this.data, k) ? this.data[k] : null; }
  setItem(k, v)    { this.data[k] = String(v); }
  removeItem(k)    { delete this.data[k]; }
}

const samplePane = { systemPrompt: "sp", messages: [{ role: "system", content: "sp" }] };
const sampleVault = { enabled: false, topK: 5 };

test("load: empty storage returns []", () => {
  const store = createSessionsStore(new FakeStorage());
  assert.deepEqual(store.load(), []);
});

test("load: corrupt JSON returns [] and does not throw", (t) => {
  t.mock.method(console, "warn", () => {});
  const fake = new FakeStorage({ "promptSandbox.sessions": "{not json" });
  const store = createSessionsStore(fake);
  assert.deepEqual(store.load(), []);
  assert.equal(console.warn.mock.callCount(), 1);
});

test("save: prepends new entry with id + timestamps", () => {
  const store = createSessionsStore(new FakeStorage());
  const entry = store.save({ name: "first", panes: [samplePane], vaultConfig: sampleVault });
  assert.match(entry.id, /^sess-\d+-[a-z0-9]{6}$/);
  assert.equal(entry.name, "first");
  assert.match(entry.createdAt, /^\d{4}-\d{2}-\d{2}T/);
  assert.equal(entry.createdAt, entry.updatedAt);
  assert.deepEqual(store.load()[0], entry);
});

test("save: newest entries come first", () => {
  const store = createSessionsStore(new FakeStorage());
  store.save({ name: "one",   panes: [samplePane], vaultConfig: sampleVault });
  store.save({ name: "two",   panes: [samplePane], vaultConfig: sampleVault });
  store.save({ name: "three", panes: [samplePane], vaultConfig: sampleVault });
  const all = store.load();
  assert.deepEqual(all.map(e => e.name), ["three", "two", "one"]);
});

test("save: trims to cap of 100 on overflow", () => {
  const store = createSessionsStore(new FakeStorage());
  for (let i = 0; i < 105; i++) {
    store.save({ name: `n${i}`, panes: [samplePane], vaultConfig: sampleVault });
  }
  const all = store.load();
  assert.equal(all.length, 100);
  // Newest first; oldest 5 dropped.
  assert.equal(all[0].name,  "n104");
  assert.equal(all[99].name, "n5");
});

test("rename: updates name + updatedAt, leaves createdAt alone", async () => {
  const store = createSessionsStore(new FakeStorage());
  const created = store.save({ name: "before", panes: [samplePane], vaultConfig: sampleVault });
  await new Promise(r => setTimeout(r, 10));   // ensure timestamp advances
  const updated = store.rename(created.id, "after");
  assert.equal(updated.name, "after");
  assert.equal(updated.createdAt, created.createdAt);
  assert.notEqual(updated.updatedAt, created.createdAt);
});

test("rename: unknown id returns null", () => {
  const store = createSessionsStore(new FakeStorage());
  assert.equal(store.rename("sess-missing", "x"), null);
});

test("delete: removes by id and returns true", () => {
  const store = createSessionsStore(new FakeStorage());
  const a = store.save({ name: "a", panes: [samplePane], vaultConfig: sampleVault });
  const b = store.save({ name: "b", panes: [samplePane], vaultConfig: sampleVault });
  assert.equal(store.delete(a.id), true);
  assert.deepEqual(store.load().map(e => e.id), [b.id]);
});

test("delete: unknown id returns false", () => {
  const store = createSessionsStore(new FakeStorage());
  assert.equal(store.delete("sess-missing"), false);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test js/sessions.test.js`
Expected: all 9 tests fail — module not found.

- [ ] **Step 3: Write js/sessions.js**

```javascript
import { STORAGE_KEY } from "./config.js";

const CAP = 100;

export function createSessionsStore(storage) {
  function readRaw() {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (err) {
      console.warn("Failed to parse sessions from storage:", err);
      return [];
    }
  }

  function writeRaw(entries) {
    storage.setItem(STORAGE_KEY, JSON.stringify(entries));
  }

  function nowIso() {
    return new Date().toISOString();
  }

  function newId() {
    const rand = Math.random().toString(36).slice(2, 8).padEnd(6, "0");
    return `sess-${Date.now()}-${rand}`;
  }

  return {
    load() {
      return readRaw();
    },

    save({ name, panes, vaultConfig }) {
      const now = nowIso();
      const entry = {
        id:        newId(),
        name,
        createdAt: now,
        updatedAt: now,
        panes,
        vaultConfig,
      };
      const entries = readRaw();
      entries.unshift(entry);
      if (entries.length > CAP) entries.length = CAP;
      writeRaw(entries);
      return entry;
    },

    rename(id, newName) {
      const entries = readRaw();
      const entry = entries.find(e => e.id === id);
      if (!entry) return null;
      entry.name = newName;
      entry.updatedAt = nowIso();
      writeRaw(entries);
      return entry;
    },

    delete(id) {
      const entries = readRaw();
      const idx = entries.findIndex(e => e.id === id);
      if (idx === -1) return false;
      entries.splice(idx, 1);
      writeRaw(entries);
      return true;
    },
  };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test js/sessions.test.js`
Expected: all 9 tests pass.

- [ ] **Step 5: Run all tests**

Run: `node --test js/*.test.js`
Expected: 26 pass / 0 fail (9 stream + 8 state + 9 sessions).

- [ ] **Step 6: Commit**

```bash
git add js/sessions.js js/sessions.test.js
git commit -m "$(cat <<'EOF'
Add js/sessions.js persistence store with node:test coverage

createSessionsStore(storage) is a thin factory over storage.getItem /
setItem (localStorage in the browser, a FakeStorage in tests). Exposes
load / save / rename / delete. Save prepends newest-first, assigns a
stable sess-<ts>-<rand6> id, stamps createdAt/updatedAt, and silently
trims to a soft cap of 100 entries. Load swallows JSON.parse failures
(via a console.warn) so a corrupted storage entry doesn't brick the UI.

9 tests covering empty storage, corrupt storage, prepend order, cap
trim, rename (existing + missing id), and delete (existing + missing).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Session panel scaffold (button + floating panel + open/close)

**Why:** DOM scaffolding before wiring behavior. When this task is done, clicking "Sessions ▾" opens an empty floating panel with placeholder sections; clicking outside or pressing Esc closes it. No Save / Load / Delete / Export wired yet.

**Files:**
- Modify: `index.html` — controls-strip HTML, CSS for the panel, JS wiring.
- Modify: `js/ui.js` — add `createSessionPanel({ anchor, onOpen, onClose })` factory returning the panel element plus `open/close/isOpen` methods and a reference to the inner regions (`saveSlot`, `listSlot`, `exportSlot`) where later tasks attach content.

**Steps:**

- [ ] **Step 1: Add the Sessions button to the controls strip**

In `index.html`, inside `<header class="vault-controls">`, insert after `<button id="new-session">`:

```html
<button id="sessions-toggle" class="secondary" aria-haspopup="true" aria-expanded="false">Sessions ▾</button>
```

- [ ] **Step 2: Add the floating-panel markup as a sibling of the header**

Still in `index.html`, immediately after the closing `</header>` of `vault-controls` and before `<main class="pane-container">`, add:

```html
<div id="sessions-panel" class="sessions-panel" hidden>
  <div class="sessions-panel-save"   id="sessions-save-slot"></div>
  <div class="sessions-panel-list"   id="sessions-list-slot">
    <div class="sessions-empty">No saved sessions yet.</div>
  </div>
  <div class="sessions-panel-export" id="sessions-export-slot"></div>
</div>
```

- [ ] **Step 3: Add panel CSS**

In `<style>`, append:

```css
.sessions-panel {
  position: absolute;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
  min-width: 280px;
  max-width: 420px;
  max-height: 60vh;
  overflow-y: auto;
  z-index: 100;
  display: flex;
  flex-direction: column;
  color: var(--fg);
  font-size: 13px;
}
.sessions-panel[hidden] { display: none; }
.sessions-panel-save,
.sessions-panel-export { padding: 10px; border-bottom: 1px solid var(--border); }
.sessions-panel-export { border-bottom: 0; border-top: 1px solid var(--border); }
.sessions-panel-list  { flex: 1; overflow-y: auto; }
.sessions-empty { padding: 14px; color: var(--muted); text-align: center; }
```

- [ ] **Step 4: Add panel factory to js/ui.js**

Append to `js/ui.js` (after the `renderSources` export):

```javascript
export function createSessionPanel({ panelEl, anchor }) {
  const saveSlot   = panelEl.querySelector(".sessions-panel-save");
  const listSlot   = panelEl.querySelector(".sessions-panel-list");
  const exportSlot = panelEl.querySelector(".sessions-panel-export");

  let onDocClick = null;
  let onEscKey   = null;

  function positionBelowAnchor() {
    const rect = anchor.getBoundingClientRect();
    panelEl.style.left = `${rect.left}px`;
    panelEl.style.top  = `${rect.bottom + 4}px`;
  }

  function open() {
    if (!panelEl.hidden) return;
    positionBelowAnchor();
    panelEl.hidden = false;
    anchor.setAttribute("aria-expanded", "true");
    // Close on outside click. Defer until current event settles so the
    // click that opened the panel doesn't immediately close it.
    setTimeout(() => {
      onDocClick = (e) => {
        if (panelEl.contains(e.target) || anchor.contains(e.target)) return;
        close();
      };
      document.addEventListener("click", onDocClick);
    }, 0);
    onEscKey = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onEscKey);
  }

  function close() {
    if (panelEl.hidden) return;
    panelEl.hidden = true;
    anchor.setAttribute("aria-expanded", "false");
    if (onDocClick) { document.removeEventListener("click",   onDocClick); onDocClick = null; }
    if (onEscKey)   { document.removeEventListener("keydown", onEscKey);   onEscKey   = null; }
  }

  function toggle() { panelEl.hidden ? open() : close(); }

  anchor.addEventListener("click", toggle);

  return { open, close, toggle, saveSlot, listSlot, exportSlot, isOpen: () => !panelEl.hidden };
}
```

- [ ] **Step 5: Wire the panel in index.html**

In the `<script type="module">` block, add after the import of `createPane`:

```javascript
import { createSessionPanel, renderSources } from "./js/ui.js";
```

(Note the combined import — `renderSources` is already imported by `send.js`, but `ui.js` is a legal import source from `index.html` too. If `renderSources` is NOT already imported at the index.html level, the line above only needs `createSessionPanel`. Remove `renderSources` if it's not referenced in index.html directly.)

Near the bottom of the script block (after the Compare-toggle wiring), add:

```javascript
const $sessionsToggle = document.getElementById("sessions-toggle");
const $sessionsPanel  = document.getElementById("sessions-panel");
const sessionPanel = createSessionPanel({ panelEl: $sessionsPanel, anchor: $sessionsToggle });
```

- [ ] **Step 6: Static checks**

```bash
node --check js/ui.js && echo "ui.js syntax ok"
node --test js/*.test.js 2>&1 | tail -5
# Expected: 26/26 pass
curl -s http://localhost:7777/ | grep -c 'id="sessions-toggle"'
# Expected: 1
curl -s http://localhost:7777/ | grep -c 'id="sessions-panel"'
# Expected: 1
```

- [ ] **Step 7: Manual browser check (request)**

Ask the user to hard-refresh and confirm:
- "Sessions ▾" button visible in the controls strip, between "New session" and the health dot.
- Click the button — a small panel opens under it with "No saved sessions yet." placeholder.
- Click outside the panel → it closes.
- Open again, press Esc → closes.
- No console errors.

- [ ] **Step 8: Commit**

```bash
git add index.html js/ui.js
git commit -m "$(cat <<'EOF'
Session panel scaffold: button, floating panel, open/close wiring

Adds the Sessions ▾ button to the controls strip and a floating panel
anchored below it. createSessionPanel in ui.js owns positioning, outside-
click and Escape handling; exposes save/list/export slot elements that
the next three tasks will populate.

Empty state shows "No saved sessions yet." until Task 4's store is
actually wired up.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Save flow (Save current → inline name entry → store.save)

**Why:** Wires the first real interaction. At task end, clicking "Save current…" in the panel morphs into an inline name entry, Save commits to storage, and the list slot re-renders showing the new entry.

**Files:**
- Modify: `js/ui.js` — add `renderSaveSlot(saveSlot, { onSave })` and `renderSessionList(listSlot, entries, { onClick, onDelete })` helpers.
- Modify: `index.html` — `createSessionsStore(localStorage)` instantiation; wire save flow.

**Steps:**

- [ ] **Step 1: Add renderSaveSlot to js/ui.js**

```javascript
export function renderSaveSlot(slot, { defaultName, onSave }) {
  slot.innerHTML = "";

  const button = document.createElement("button");
  button.textContent = "Save current…";
  button.className   = "secondary sessions-save-button";
  button.style.width = "100%";

  const form = document.createElement("div");
  form.className = "sessions-save-form";
  form.hidden = true;
  form.style.display = "flex";
  form.style.gap = "6px";

  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "Name this session";
  input.style.flex = "1";
  input.style.background = "#111";
  input.style.color = "var(--fg)";
  input.style.border = "1px solid var(--border)";
  input.style.borderRadius = "4px";
  input.style.padding = "6px 8px";

  const saveBtn = document.createElement("button");
  saveBtn.textContent = "Save";

  const cancelBtn = document.createElement("button");
  cancelBtn.textContent = "Cancel";
  cancelBtn.className = "secondary";

  form.append(input, saveBtn, cancelBtn);
  slot.append(button, form);

  function openForm() {
    input.value = defaultName();
    button.hidden = true;
    form.hidden   = false;
    form.style.display = "flex";
    input.focus();
    input.select();
  }
  function closeForm() {
    button.hidden = false;
    form.hidden   = true;
    form.style.display = "none";
  }
  function commit() {
    const name = input.value.trim();
    if (!name) return;        // require non-empty; cheap client-side guard
    onSave(name);
    closeForm();
  }

  button.addEventListener("click", openForm);
  saveBtn.addEventListener("click", commit);
  cancelBtn.addEventListener("click", closeForm);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter")  { e.preventDefault(); commit();    }
    if (e.key === "Escape") { e.preventDefault(); closeForm(); }
  });
}
```

- [ ] **Step 2: Add renderSessionList to js/ui.js**

```javascript
export function renderSessionList(slot, entries, { onClick, onDelete }) {
  slot.innerHTML = "";
  if (entries.length === 0) {
    const empty = document.createElement("div");
    empty.className = "sessions-empty";
    empty.textContent = "No saved sessions yet.";
    slot.appendChild(empty);
    return;
  }
  for (const entry of entries) {
    const row = document.createElement("div");
    row.className = "sessions-row";
    row.style.padding = "8px 10px";
    row.style.cursor  = "pointer";
    row.style.display = "flex";
    row.style.gap     = "8px";
    row.style.alignItems = "center";
    row.style.borderBottom = "1px solid var(--border)";

    const dots = document.createElement("span");
    dots.textContent = entry.panes
      .map(p => p.messages.length > 1 ? "●" : "○")
      .join("");
    dots.style.color = "var(--muted)";
    dots.style.fontSize = "11px";
    dots.style.width = "22px";

    const name = document.createElement("span");
    name.textContent = entry.name;
    name.style.flex = "1";
    name.style.overflow = "hidden";
    name.style.textOverflow = "ellipsis";
    name.style.whiteSpace = "nowrap";

    const age = document.createElement("span");
    age.textContent = formatAge(entry.createdAt);
    age.style.color = "var(--muted)";
    age.style.fontSize = "11px";

    const del = document.createElement("button");
    del.textContent = "✕";
    del.className   = "secondary";
    del.style.padding = "2px 6px";
    del.style.fontSize = "11px";
    del.addEventListener("click", (e) => {
      e.stopPropagation();
      onDelete(entry);
    });

    row.append(dots, name, age, del);
    row.addEventListener("click", () => onClick(entry));
    slot.appendChild(row);
  }
}

function formatAge(iso) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const day    = 86400000;
  const days   = Math.floor(diffMs / day);
  if (days < 1) return "today";
  if (days < 2) return "1d";
  if (days < 30) return `${days}d`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo`;
  return `${Math.floor(months / 12)}y`;
}
```

- [ ] **Step 3: Wire save into index.html**

In the script block, update the imports line that was added in Task 5:

```javascript
import { createSessionPanel, renderSaveSlot, renderSessionList } from "./js/ui.js";
```

Add a new import at the top:

```javascript
import { createSessionsStore } from "./js/sessions.js";
```

Below the existing `const sessionPanel = createSessionPanel(...)`, add:

```javascript
const sessionsStore = createSessionsStore(localStorage);

function autoName() {
  // First user message's first 40 chars, at a word boundary if possible.
  for (const { state } of activePanes()) {
    const firstUser = state.messages.find(m => m.role === "user");
    if (firstUser) {
      const raw = firstUser.content.trim().split("\n", 1)[0];
      if (raw.length <= 40) return raw;
      const cut = raw.slice(0, 40);
      const lastSpace = cut.lastIndexOf(" ");
      return lastSpace > 10 ? cut.slice(0, lastSpace) : cut;
    }
  }
  return `Untitled ${new Date().toISOString().slice(0, 16).replace("T", " ")}`;
}

function currentSnapshot() {
  const panes = activePanes().map(({ state }) => ({
    systemPrompt: state.systemPrompt,
    messages:     [...state.messages],
  }));
  const vaultConfig = {
    enabled: $useVault.checked,
    topK:    Math.max(1, Math.min(20, parseInt($topK.value, 10) || 5)),
  };
  return { panes, vaultConfig };
}

function refreshSessionList() {
  renderSessionList(sessionPanel.listSlot, sessionsStore.load(), {
    onClick:  () => {},       // Task 7 will fill in
    onDelete: () => {},       // Task 8 will fill in
  });
}

renderSaveSlot(sessionPanel.saveSlot, {
  defaultName: autoName,
  onSave: (name) => {
    const { panes, vaultConfig } = currentSnapshot();
    sessionsStore.save({ name, panes, vaultConfig });
    refreshSessionList();
  },
});

refreshSessionList();
```

- [ ] **Step 4: Static checks**

```bash
node --check js/ui.js && echo "ok"
node --test js/*.test.js 2>&1 | tail -5
# 26/26
```

- [ ] **Step 5: Manual browser check (request)**

User:
- Send a message so there's some history.
- Click Sessions ▾, click "Save current…", adjust the name, press Enter.
- Panel closes the form and shows the new entry in the list with "●" (has convo) and the age.
- Refresh the page — re-open the panel — entry still there.
- Open DevTools → Application → Local Storage → `http://localhost:7777` → confirm `promptSandbox.sessions` key exists with the expected JSON.

- [ ] **Step 6: Commit**

```bash
git add js/ui.js index.html
git commit -m "$(cat <<'EOF'
Session save flow: inline name entry + list render

renderSaveSlot morphs the Save button into a name-entry row on click
(Enter confirms, Esc cancels). renderSessionList draws entry rows with
pane-count dots (● = has convo, ○ = prompt only), name, relative age,
and a trailing ✕ delete button (wired in Task 8). index.html wires the
store, an autoName() helper (first user message or timestamped
fallback), and currentSnapshot() which captures active pane states +
vault config.

Load + Delete + Export slots still no-ops; follow in Tasks 7-9.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Load flow (A/B-aware restore)

**Why:** Clicking a list entry restores the saved state. Single-pane entries restore into pane A (with a confirm if currently in compare mode with non-empty Pane B). Two-pane entries enter compare mode if needed, replacing both panes.

**Files:**
- Modify: `index.html` — fill in the `onClick` handler.

**Steps:**

- [ ] **Step 1: Replace refreshSessionList to include a real onClick**

In `index.html`, find the `refreshSessionList` function and change its body. Above it, add a `loadEntry` function. The resulting block should read:

```javascript
function loadEntry(entry) {
  const paneCount = entry.panes.length;

  if (paneCount === 1) {
    // Single-pane entry.
    if (paneB && stateB && stateB.messages.length > 1) {
      const ok = confirm("Loading this session will exit compare mode and discard Pane B's conversation. Continue?");
      if (!ok) return;
    }
    if (paneB) exitCompare();   // no-op confirm because we already cleared it; see note below
    // Replace pane A's state.
    stateA.applyPrompt(entry.panes[0].systemPrompt);
    stateA.messages = [...entry.panes[0].messages];
    paneA.textarea.value = entry.panes[0].systemPrompt;
    paneA.refreshPreview();
    paneA.renderFromMessages(stateA.messages);
  } else {
    // Two-pane entry: enter compare mode if needed.
    if (!paneB) enterCompare();
    stateA.applyPrompt(entry.panes[0].systemPrompt);
    stateA.messages = [...entry.panes[0].messages];
    paneA.textarea.value = entry.panes[0].systemPrompt;
    paneA.refreshPreview();
    paneA.renderFromMessages(stateA.messages);

    stateB.applyPrompt(entry.panes[1].systemPrompt);
    stateB.messages = [...entry.panes[1].messages];
    paneB.textarea.value = entry.panes[1].systemPrompt;
    paneB.refreshPreview();
    paneB.renderFromMessages(stateB.messages);
  }

  // Restore vault config.
  $useVault.checked = !!entry.vaultConfig?.enabled;
  $topK.value       = String(entry.vaultConfig?.topK ?? 5);

  sessionPanel.close();
}

function refreshSessionList() {
  renderSessionList(sessionPanel.listSlot, sessionsStore.load(), {
    onClick:  loadEntry,
    onDelete: () => {},   // Task 8
  });
}
```

**Note on the double-confirm for exitCompare**: `exitCompare()` itself shows a confirm when Pane B has a conversation. If the user has already confirmed via our outer dialog, we don't want to confirm again. The simplest fix is to skip the redundant confirm by clearing `stateB.messages` first so `exitCompare`'s check passes:

Replace the block inside the single-pane branch of `loadEntry`:

```javascript
    if (paneB) exitCompare();
```

with:

```javascript
    if (paneB) {
      stateB.messages = [{ role: "system", content: stateB.systemPrompt }];   // bypass exitCompare's confirm
      exitCompare();
    }
```

- [ ] **Step 2: Static checks**

```bash
node --check index.html 2>/dev/null || true   # HTML isn't parseable by node; skip.
curl -s http://localhost:7777/ | grep -c 'function loadEntry'
# Expected: 1
node --test js/*.test.js 2>&1 | tail -5
# Expected: 26/26 pass
```

- [ ] **Step 3: Manual browser check (request)**

User:
- Save a single-pane session after typing a few messages. Clear the conversation (New session). Open Sessions ▾, click the saved entry → conversation restores, prompt restores, vault settings restore.
- Save an A/B session: enter compare, give B a different prompt, send messages in both, then Save. Exit compare. Open Sessions ▾, click the two-pane entry → compare mode re-enters, both panes restored.
- Save a single-pane session. Enter compare mode, populate B. Click the saved single-pane entry → outer confirm fires ("Loading this session will exit compare mode…"). Click OK → single-pane state restored.

- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "$(cat <<'EOF'
Session load flow (A/B-aware)

Clicking a list entry restores pane state, textarea, preview, log, and
vault config. Single-pane entries: exit compare if on (with outer
confirm when Pane B is dirty; bypasses exitCompare's inner confirm by
pre-clearing stateB.messages). Two-pane entries: enter compare if off,
then replace both panes.

Leans on pane.renderFromMessages (added in Task 3) to rebuild logs from
the persisted messages array without re-streaming.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Delete flow

**Why:** Trivial wiring to finish the Sessions CRUD.

**Files:**
- Modify: `index.html` — fill in `onDelete`.

**Steps:**

- [ ] **Step 1: Wire onDelete**

Replace the `refreshSessionList` again:

```javascript
function refreshSessionList() {
  renderSessionList(sessionPanel.listSlot, sessionsStore.load(), {
    onClick: loadEntry,
    onDelete: (entry) => {
      const ok = confirm(`Delete '${entry.name}'? This cannot be undone.`);
      if (!ok) return;
      sessionsStore.delete(entry.id);
      refreshSessionList();
    },
  });
}
```

- [ ] **Step 2: Manual browser check**

User: save a session, open Sessions ▾, click ✕ on the row → confirm fires; on OK the row disappears and localStorage reflects the deletion.

- [ ] **Step 3: Commit**

```bash
git add index.html
git commit -m "$(cat <<'EOF'
Session delete flow with confirm

Wires the ✕ button on each session row to sessionsStore.delete with a
native confirm. Refreshes the list after deletion so the row vanishes
in place.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Export current as Markdown

**Why:** Final feature of Phase 2. The "Export current as Markdown" button in the panel's export slot takes the current active pane(s) and downloads a `.md` file.

**Files:**
- Modify: `js/ui.js` — add `buildMarkdown(snapshot)` + `triggerMarkdownDownload({name, markdown})` helpers, and `renderExportSlot(slot, { onExport })`.
- Modify: `index.html` — wire the export button.

**Steps:**

- [ ] **Step 1: Add Markdown builders to js/ui.js**

```javascript
export function buildMarkdown(snapshot, exportedName) {
  const { panes, vaultConfig } = snapshot;
  const frontmatter = [
    "---",
    `name: ${exportedName}`,
    `exported: ${new Date().toISOString()}`,
    `vault: { enabled: ${vaultConfig.enabled}, topK: ${vaultConfig.topK} }`,
    "---",
    "",
  ].join("\n");

  const sections = panes.map((pane, idx) => {
    const header = panes.length > 1 ? `## Pane ${idx === 0 ? "A" : "B"}\n\n` : "";
    const prompt = pane.systemPrompt
      .split("\n")
      .map(line => `> ${line}`)
      .join("\n");
    const turns = pane.messages
      .filter(m => m.role !== "system")
      .map(m => {
        const label = m.role === "user" ? "**You:**" : "**Assistant:**";
        return `${label}\n\n${m.content}\n`;
      })
      .join("\n");
    return `${header}${prompt}\n\n${turns}`;
  });

  return frontmatter + sections.join("\n");
}

export function triggerMarkdownDownload({ filename, markdown }) {
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function renderExportSlot(slot, { onExport }) {
  slot.innerHTML = "";
  const button = document.createElement("button");
  button.textContent = "Export current as Markdown";
  button.className   = "secondary";
  button.style.width = "100%";
  button.addEventListener("click", onExport);
  slot.appendChild(button);
}

function slugify(name) {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40) || "prompt-sandbox";
}

// Re-export slugify only if index.html needs it externally; otherwise keep private.
export { slugify };
```

- [ ] **Step 2: Wire the export button in index.html**

Update the `ui.js` import line:

```javascript
import {
  createSessionPanel, renderSaveSlot, renderSessionList,
  renderExportSlot, buildMarkdown, triggerMarkdownDownload, slugify,
} from "./js/ui.js";
```

Below the `renderSaveSlot(...)` call, add:

```javascript
renderExportSlot(sessionPanel.exportSlot, {
  onExport: () => {
    const snapshot = currentSnapshot();
    const name     = autoName();
    const markdown = buildMarkdown(snapshot, name);
    const date     = new Date().toISOString().slice(0, 10);
    triggerMarkdownDownload({
      filename: `${slugify(name)}-${date}.md`,
      markdown,
    });
    sessionPanel.close();
  },
});
```

- [ ] **Step 3: Static checks**

```bash
node --check js/ui.js
node --test js/*.test.js 2>&1 | tail -5
# Expected: 26/26 pass
```

- [ ] **Step 4: Manual browser check (request)**

User:
- Send messages in single-pane mode, click Sessions ▾ → "Export current as Markdown". A `.md` file downloads.
- Open the downloaded file in a text editor: verify frontmatter, blockquoted system prompt, "**You:**" / "**Assistant:**" turn labels, correct order.
- Enter compare mode, send to both, Export. File now has `## Pane A` and `## Pane B` sections with independent histories.

- [ ] **Step 5: Commit**

```bash
git add js/ui.js index.html
git commit -m "$(cat <<'EOF'
Markdown export of current active pane(s)

Adds buildMarkdown + triggerMarkdownDownload helpers and wires the
"Export current as Markdown" button in the session panel. Produces a
file with YAML-ish frontmatter (name, exported timestamp, vault config)
and one section per pane — blockquoted system prompt followed by
**You** / **Assistant** turns. Filename is <slugified-name>-<YYYY-MM-DD>.md.

Uses URL.createObjectURL + a transient <a> for the download; no server
round-trip, no data-URL length issues on large conversations.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Full acceptance verification

**Why:** Final end-to-end sweep against the spec's acceptance criteria.

**Files:** None modified.

- [ ] **Step 1: Services up**

```bash
curl -sf http://localhost:7777/ -o /dev/null && curl -sf http://localhost:8080/v1/models -o /dev/null && curl -sf http://localhost:8100/health && echo
```

- [ ] **Step 2: Unit tests**

```bash
cd ~/prompt-sandbox && node --test js/*.test.js 2>&1 | tail -10
# Expected: 26 pass / 0 fail.
```

- [ ] **Step 3: Phase 1 regression**

Hard-refresh. Verify:
- Default prompt preview visible; expand/collapse works.
- Send "hi" (vault off) → streams a reply.
- Toggle vault on → send → sources chips appear.
- Reindex → status updates.
- Health dot green.
- Apply & Reset updates preview + clears conversation.
- New session clears conversation, keeps prompt.
- Enter sends; Shift+Enter newlines.
- Compare on → Pane B appears with accent "B" badge.
- Parallel streams in compare mode.
- Exit Compare with Pane B populated → confirm fires with Phase 1 copy.

- [ ] **Step 4: Phase 2 acceptance**

- Sessions ▾ button visible; opens panel under it; closes on outside-click / Esc.
- Save single-pane with one-line name, Enter commits; row appears with "●" and "today"/"0d".
- Save two-pane with Compare on; row appears with "●●".
- Save prompt-only (no user messages yet) — row appears with "○".
- Click single-pane row in compare mode with Pane B populated → outer confirm fires; on OK, exits compare + restores.
- Click two-pane row in single-pane mode → enters compare + restores both panes.
- Click ✕ on a row → confirm fires; on OK, row vanishes.
- Open DevTools → Application → Local Storage → `promptSandbox.sessions` contains the expected JSON.
- Reload page; saved entries still in the list.
- Corrupt the storage (DevTools: `localStorage.setItem('promptSandbox.sessions','{not-json')`), reload → panel shows "No saved sessions yet.", console has a `Failed to parse sessions from storage:` warning; sandbox still usable.
- Export current (single-pane) → `.md` downloads; open → frontmatter + system prompt + turns as expected.
- Export current (compare mode) → `.md` has two `## Pane A` / `## Pane B` sections.
- Kill MLX mid-send (`lsof -ti :8080 | xargs kill`) → error bubble in the pane; next send proceeds normally (I-1 fix: state not polluted).
- Use MLX config that yields empty `[DONE]` — bubble shows "(empty response)" instead of stuck "Thinking…" (I-2 fix). Hard to reproduce on demand; accept if it doesn't naturally occur during other testing.

- [ ] **Step 5: Commit log audit**

```bash
git log --oneline a70faff..HEAD
```

Expected: ~10 commits, one per plan task plus any inline review fixes, each with the Co-Authored-By trailer.

- [ ] **Step 6: Final code review (controller-driven)**

The controller dispatches a `superpowers:code-reviewer` subagent across `BASE=a70faff` (Phase 2 spec commit) and `HEAD=<final>`. The controller handles any fix loops before declaring Phase 2 done.

- [ ] **Step 7: No commit needed**

Task 10 is verification; no code change. End of Phase 2.

---

## Self-review notes (applied inline)

- **Spec coverage**: every section of the spec maps to a task. §1 (model) → Task 4; §2 (panel UI) → Task 5; §3 save/load/delete → Tasks 6/7/8; §4 export → Task 9; §5.I-1 → Task 0; §5.I-2 → Task 1; §5.config → Task 2; §5.ui split → Task 3; §6 sessions.js → Task 4; §7 testing → Tasks 0+4; acceptance → Task 10.
- **Placeholders**: none — every step includes the code or exact command.
- **Type / name consistency**:
  - `createSessionsStore(storage)` signature is consistent across Task 4 (def) and Tasks 6–8 (consumers).
  - Entry fields (`id`, `name`, `createdAt`, `updatedAt`, `panes`, `vaultConfig`) are consistent between the schema in the spec and the test + implementation in Task 4, and between save (Task 6), load (Task 7), delete (Task 8).
  - `renderFromMessages` added to the pane handle in Task 3 is used by loadEntry in Task 7.
  - `autoName` / `currentSnapshot` / `slugify` / `buildMarkdown` / `triggerMarkdownDownload` are all defined or imported before use.
- **Scope**: Phase 2 only. Phase 3 (token meter) is untouched.
- **Ambiguities resolved**: storage cap = rolling 100 (FIFO by createdAt); load replaces current state without copy; load confirms in outer dialog before entering exitCompare (bypasses inner confirm by pre-clearing `stateB.messages`); export uses Blob + createObjectURL (no data-URL length limits); autoName uses first-40-chars-at-word-boundary of first user message, with timestamp fallback.
