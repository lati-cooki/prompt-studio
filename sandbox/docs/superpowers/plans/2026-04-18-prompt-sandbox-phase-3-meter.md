# Prompt Sandbox Phase 3 — Token/Context Meter + Structural Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-pane token/context meter (hybrid exact-from-`usage` + approximate-for-draft), fold in five Phase 2 structural carry-forwards, and evolve `config.js` into a MODELS map so the next step — model swapping — is a configuration change rather than a refactor.

**Architecture:** Five pre-work tasks land before any new meter code: MODELS map, `state.loadSnapshot` + `state.subscribe`, script-to-`js/app.js` pull, `ui.js` split, and block-style YAML frontmatter. Then three feature tasks: pure `tokens.js` (TDD), `stream.js` extension to surface `usage`, and DOM-facing `meter.js` with wiring. Final acceptance + cross-commit code review closes Phase 3.

**Tech Stack:** Vanilla JS (ES modules), CSS custom properties, Node 22 `node:test`. No package.json, no npm, no build.

**Spec:** `docs/superpowers/specs/2026-04-18-prompt-sandbox-phase-3-meter.md`.

---

## File layout after this plan

```
prompt-sandbox/
├── index.html                 ← markup + styles + <script type="module" src="./js/app.js">
├── js/
│   ├── config.js              ← MODELS map + ACTIVE_MODEL + legacy shims
│   ├── app.js                 ← NEW: entry wiring (moved from index.html)
│   ├── stream.js              ← +usage surfaced on terminal chunk
│   ├── stream.test.js         ← +usage tests
│   ├── state.js               ← +loadSnapshot, +subscribe
│   ├── state.test.js          ← +loadSnapshot, +subscribe tests
│   ├── vault.js               ← unchanged
│   ├── pane.js                ← unchanged
│   ├── ui.js                  ← trimmed to renderSources only (~15 LOC)
│   ├── session-panel.js       ← NEW: panel + save/list rendering
│   ├── export.js              ← NEW: buildMarkdown + download + slugify
│   ├── sessions.js            ← unchanged
│   ├── sessions.test.js       ← unchanged
│   ├── send.js                ← ACTIVE_MODEL import; setExactPromptTokens callback
│   ├── tokens.js              ← NEW: approxTokens, sumMessages, breakdown
│   ├── tokens.test.js         ← NEW
│   └── meter.js               ← NEW: createMeter factory (DOM-facing)
```

## Task-map back to spec

| Spec section | Implementing task |
|---|---|
| §1 MODELS map | 0 |
| §2.Ic state.loadSnapshot + subscribe | 2 |
| §2.Id ui.js split | 3 |
| §2.IIa pull to app.js | 1 |
| §2.Ia block-style YAML | 4 |
| §3 js/tokens.js | 5 |
| §4 js/meter.js | 7 |
| §5 data flow wiring | 7 |
| §6 stream.js usage extraction | 6 |
| §7 UI placement | 7 |
| Acceptance criteria | 8 |

---

## Task 0: MODELS map in `js/config.js`

**Why:** Portability goal — swapping models should be a one-line change. Evolve the current flat `API_URL` / `MODEL` constants into a registry keyed by short model name.

**Files:**
- Modify: `js/config.js`
- Modify: `js/send.js`

- [ ] **Step 1: Rewrite js/config.js**

Replace the existing content with:

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

// Legacy shims — remove at end of Phase 3 after a grep pass confirms no consumers remain.
export const API_URL = ACTIVE_MODEL.endpoint;
export const MODEL   = ACTIVE_MODEL.id;

export const VAULT_URL   = "http://localhost:8100";
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

- [ ] **Step 2: Update js/send.js to use ACTIVE_MODEL**

In `js/send.js`, replace the existing import line:

```javascript
import { API_URL, MODEL } from "./config.js";
```

With:

```javascript
import { ACTIVE_MODEL } from "./config.js";
```

And replace the two usages of `API_URL` and `MODEL` in the `fetch(...)` body. The current block:

```javascript
    const res = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: MODEL,
        messages: turnMessages,
        stream: true,
        max_tokens: 4096,
      }),
    });
```

Change to:

```javascript
    const res = await fetch(ACTIVE_MODEL.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: ACTIVE_MODEL.id,
        messages: turnMessages,
        stream: true,
        max_tokens: 4096,
      }),
    });
```

- [ ] **Step 3: Sanity-check**

```bash
cd ~/prompt-sandbox
node --check js/config.js && node --check js/send.js && echo "syntax ok"
node --test js/*.test.js 2>&1 | tail -5
# Expected: 28/28 pass
curl -s http://localhost:7777/js/config.js | grep -c "MODELS"
# Expected: 2+ (export + Object reference)
curl -s http://localhost:7777/js/config.js | grep -c "ACTIVE_MODEL"
# Expected: 3+ (ACTIVE_MODEL_KEY, ACTIVE_MODEL, reference from MODELS)
```

- [ ] **Step 4: Manual browser smoke**

Hard-refresh `http://localhost:7777/`. Send "hi" → streams a reply. No console errors. If any error mentions `API_URL is not defined` or `MODEL is not defined`, a consumer wasn't updated — grep for the legacy names and fix.

- [ ] **Step 5: Commit**

```bash
git add js/config.js js/send.js
git commit -m "$(cat <<'EOF'
Evolve config.js to MODELS map + ACTIVE_MODEL pointer

Replaces flat API_URL / MODEL constants with a MODELS registry keyed
by short model name. ACTIVE_MODEL_KEY names the current selection;
ACTIVE_MODEL is the object. send.js reads .id and .endpoint. Adds a
contextWindow field (128000 for Gemma) that meter.js will consume.

Legacy API_URL / MODEL are still exported as shims pointing at the
active entry, to keep any missed consumer working; they'll be removed
after Phase 3's final grep pass confirms no one reads them.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 1: Pull `index.html` script → `js/app.js`

**Why:** The entry block has grown past ~240 lines. Moving it to a dedicated `js/app.js` keeps `index.html` as markup-and-styles and gives future phases a real file to extend.

**Files:**
- Create: `js/app.js`
- Modify: `index.html`

- [ ] **Step 1: Create js/app.js with the current script body**

Read the current `<script type="module">...</script>` block in `index.html` (between the `<footer>` and the closing `</body>`). Paste its entire body (everything between the opening and closing `<script>` tags) into a new `js/app.js`, unchanged.

- [ ] **Step 2: Replace the inline script in index.html with a module loader**

In `index.html`, replace the entire `<script type="module">...</script>` block with:

```html
<script type="module" src="./js/app.js"></script>
```

- [ ] **Step 3: Sanity-check**

```bash
cd ~/prompt-sandbox
node --check js/app.js && echo "syntax ok"
node --test js/*.test.js 2>&1 | tail -5
# Expected: 28/28 pass
curl -s http://localhost:7777/ | grep -c 'src="./js/app.js"'
# Expected: 1
curl -s http://localhost:7777/ | grep -c '<script type="module">'
# Expected: 0 (inline module is gone)
curl -s http://localhost:7777/js/app.js | head -10
# Expected: the imports — createPaneState, createPane, sendToPanes, etc.
wc -l index.html js/app.js
# Expected: index.html way down (~270 LOC); app.js ~240+ LOC
```

- [ ] **Step 4: Manual browser smoke**

Hard-refresh. Everything should look identical — prompt preview, Compare button, Sessions, Send, vault toggle, health dot. Any regression means a relative import path broke during the move.

- [ ] **Step 5: Commit**

```bash
git add js/app.js index.html
git commit -m "$(cat <<'EOF'
Move index.html's entry script into js/app.js

No behavior change. The <script type="module"> body moves verbatim into
js/app.js; index.html replaces it with a single-line module loader.
Unblocks Phase 3's meter wiring and keeps index.html readable as
markup + styles.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `state.loadSnapshot` + `state.subscribe` (TDD) and refactor loadEntry

**Why:** The meter needs to observe state mutations. Direct `state.messages = [...]` assignments in `app.js:loadEntry` bypass the state module's encapsulation and prevent subscribers from firing. Add `loadSnapshot` (atomic replace) + `subscribe` (mutation notification) to the state API; refactor `loadEntry` and the `exitCompare`-bypass trick to use them.

**Files:**
- Modify: `js/state.js`
- Modify: `js/state.test.js`
- Modify: `js/app.js` — `loadEntry` uses `state.loadSnapshot`.

- [ ] **Step 1: Write the failing tests**

Append to `js/state.test.js`:

```javascript
test("loadSnapshot replaces systemPrompt and messages atomically", () => {
  const s = createPaneState("old prompt");
  s.addUser("hi");
  s.addAssistant("there");
  s.loadSnapshot({
    systemPrompt: "new prompt",
    messages: [
      { role: "system", content: "new prompt" },
      { role: "user", content: "resumed" },
    ],
  });
  assert.equal(s.systemPrompt, "new prompt");
  assert.deepEqual(s.messages, [
    { role: "system", content: "new prompt" },
    { role: "user", content: "resumed" },
  ]);
});

test("subscribe fires after mutating methods and not on no-op", () => {
  const s = createPaneState("sp");
  let calls = 0;
  const unsub = s.subscribe(() => calls++);

  s.addUser("a");              // 1
  s.addAssistant("b");          // 2
  s.popLastUser();              // 3 (assistant at tail, false return — but we still notify consistently)
  s.reset();                    // 4
  s.applyPrompt("new");          // 5 (applyPrompt internally calls reset — emit once, not twice)
  s.loadSnapshot({ systemPrompt: "x", messages: [{ role: "system", content: "x" }] });  // 6

  assert.ok(calls >= 6, `expected at least 6 notifications, got ${calls}`);

  unsub();
  s.addUser("after-unsub");
  const prev = calls;
  s.addUser("again");
  assert.equal(calls, prev + 1);   // only the first addUser fires a notify (unsub happened; one more mutation)
  // Note: addUser after unsub should not fire — so the assertion above should actually be `calls === prev`.
});
```

The last test as written has a bug — the comment on the last line contradicts the `addUser("after-unsub")` call that preceded it. Fix the test to make the intent clear:

Replace the test body `subscribe fires after mutating methods and not on no-op` with:

```javascript
test("subscribe fires after mutating methods; unsubscribe stops notifications", () => {
  const s = createPaneState("sp");
  let calls = 0;
  const unsub = s.subscribe(() => calls++);

  s.addUser("a");
  s.addAssistant("b");
  s.reset();
  s.applyPrompt("new");
  s.loadSnapshot({ systemPrompt: "x", messages: [{ role: "system", content: "x" }] });

  const beforeUnsub = calls;
  assert.ok(beforeUnsub >= 5, `expected ≥5 notifications before unsub, got ${beforeUnsub}`);

  unsub();
  s.addUser("after-unsub");
  assert.equal(calls, beforeUnsub, "post-unsubscribe mutations must not notify");
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test js/state.test.js`
Expected: the two new tests fail (no `loadSnapshot`, no `subscribe`).

- [ ] **Step 3: Implement loadSnapshot and subscribe in js/state.js**

Current state factory closes over the returned object. Rewrite to also close over a subscribers set. Replace the entire body of `createPaneState` with:

```javascript
export function createPaneState(initialPrompt) {
  const subscribers = new Set();
  const notify = () => { for (const fn of subscribers) fn(); };

  return {
    systemPrompt: initialPrompt,
    messages: [{ role: "system", content: initialPrompt }],

    reset() {
      this.messages = [{ role: "system", content: this.systemPrompt }];
      notify();
    },
    applyPrompt(newPrompt) {
      this.systemPrompt = newPrompt;
      this.messages = [{ role: "system", content: newPrompt }];
      notify();
    },
    addUser(text) {
      this.messages.push({ role: "user", content: text });
      notify();
    },
    addAssistant(text) {
      this.messages.push({ role: "assistant", content: text });
      notify();
    },
    popLastUser() {
      const last = this.messages[this.messages.length - 1];
      if (!last || last.role !== "user") return false;
      this.messages.pop();
      notify();
      return true;
    },
    loadSnapshot({ systemPrompt, messages }) {
      this.systemPrompt = systemPrompt;
      this.messages = [...messages];
      notify();
    },
    buildTurnMessages(vaultMessage) {
      if (!vaultMessage) return [...this.messages];
      return [this.messages[0], vaultMessage, ...this.messages.slice(1)];
    },
    subscribe(fn) {
      subscribers.add(fn);
      return () => subscribers.delete(fn);
    },
  };
}
```

Note: `applyPrompt` is intentionally inlined (doesn't call `this.reset()`) to fire `notify` exactly once per mutation. Change is behaviorally identical to the old version.

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test js/*.test.js`
Expected: 30 pass / 0 fail (28 prior + 2 new).

- [ ] **Step 5: Refactor loadEntry in js/app.js**

In `js/app.js`, find the `loadEntry` function. Replace both the single-pane and two-pane branches' `state.applyPrompt(...)` + direct `state.messages = ...` + textarea reset pattern with `state.loadSnapshot(...)` calls.

Current single-pane branch body (inside `if (paneCount === 1) { ... }`):

```javascript
    if (paneB && stateB && stateB.messages.length > 1) {
      const ok = confirm("Loading this session will exit compare mode and discard Pane B's conversation. Continue?");
      if (!ok) return;
    }
    if (paneB) {
      stateB.messages = [{ role: "system", content: stateB.systemPrompt }];
      exitCompare();
    }
    stateA.applyPrompt(entry.panes[0].systemPrompt);
    stateA.messages = [...entry.panes[0].messages];
    paneA.textarea.value = entry.panes[0].systemPrompt;
    paneA.refreshPreview();
    paneA.renderFromMessages(stateA.messages);
```

Replace with:

```javascript
    if (paneB && stateB && stateB.messages.length > 1) {
      const ok = confirm("Loading this session will exit compare mode and discard Pane B's conversation. Continue?");
      if (!ok) return;
    }
    if (paneB) {
      // Snapshot Pane B to an empty-but-valid state so exitCompare's inner check sees "clean".
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
```

Current two-pane branch body:

```javascript
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
```

Replace with:

```javascript
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
```

- [ ] **Step 6: Sanity-check + manual browser pass**

Run: `node --test js/*.test.js 2>&1 | tail -5`
Expected: 30/30 pass.

Hard-refresh the browser. Run the same load-flow checks as Phase 2 Task 7 (save single-pane, load it after New session; save A/B, load it from single-pane mode; load single-pane while in compare mode → confirm fires and restores). All should still work.

- [ ] **Step 7: Commit**

```bash
git add js/state.js js/state.test.js js/app.js
git commit -m "$(cat <<'EOF'
Add state.loadSnapshot + state.subscribe; refactor loadEntry

Ic from Phase 2 review. loadSnapshot replaces systemPrompt + messages
atomically; subscribe registers a mutation callback that fires after
every state-changing method (returning an unsubscribe fn). applyPrompt
is inlined to fire a single notification per call (was: reset-then-
overwrite which would fire twice).

app.js's loadEntry now uses loadSnapshot in both branches, removing the
"pre-clear stateB.messages" hack that had to lie to exitCompare about
pane B's dirtiness — the snapshot sets it to system-only directly.

Unblocks the meter subscribing to state changes in Task 7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Split `js/ui.js` → `js/session-panel.js` + `js/export.js`

**Why:** `ui.js` is 251 LOC with three concerns (panel chrome, export, sources). Each can live in its own module with no shared state.

**Files:**
- Create: `js/session-panel.js`
- Create: `js/export.js`
- Modify: `js/ui.js`
- Modify: `js/app.js` — update imports.

- [ ] **Step 1: Create js/session-panel.js**

Create `js/session-panel.js` containing `createSessionPanel`, `renderSaveSlot`, `renderSessionList`, and `formatAge`, moved verbatim from `js/ui.js`.

- [ ] **Step 2: Create js/export.js**

Create `js/export.js` containing `buildMarkdown`, `triggerMarkdownDownload`, `renderExportSlot`, and `slugify`, moved verbatim from `js/ui.js`.

- [ ] **Step 3: Trim js/ui.js**

`js/ui.js` should now contain ONLY the `renderSources` export (the original Phase 1 helper). Everything else moved.

- [ ] **Step 4: Update js/app.js imports**

Current `ui.js` import in `js/app.js`:

```javascript
import {
  createSessionPanel, renderSaveSlot, renderSessionList,
  renderExportSlot, buildMarkdown, triggerMarkdownDownload, slugify,
} from "./js/ui.js";
```

Replace with:

```javascript
import { createSessionPanel, renderSaveSlot, renderSessionList } from "./js/session-panel.js";
import { renderExportSlot, buildMarkdown, triggerMarkdownDownload, slugify } from "./js/export.js";
```

Leave other imports alone. `js/send.js`'s `import { renderSources } from "./ui.js";` still works because `renderSources` stays in `ui.js`.

- [ ] **Step 5: Sanity-check**

```bash
cd ~/prompt-sandbox
node --check js/session-panel.js && node --check js/export.js && node --check js/ui.js && echo "syntax ok"
node --test js/*.test.js 2>&1 | tail -5
# Expected: 30/30 pass
curl -s http://localhost:7777/js/session-panel.js | grep -c "export function"
# Expected: 3 (createSessionPanel, renderSaveSlot, renderSessionList)
curl -s http://localhost:7777/js/export.js | grep -c "export function"
# Expected: 4 (buildMarkdown, triggerMarkdownDownload, renderExportSlot, slugify)
curl -s http://localhost:7777/js/ui.js | grep -c "export function"
# Expected: 1 (just renderSources)
wc -l js/session-panel.js js/export.js js/ui.js
```

- [ ] **Step 6: Manual browser smoke**

Hard-refresh. Sessions panel opens, Save / Load / Delete / Export all still work. No console errors.

- [ ] **Step 7: Commit**

```bash
git add js/session-panel.js js/export.js js/ui.js js/app.js
git commit -m "$(cat <<'EOF'
Split js/ui.js into session-panel.js and export.js

Id from Phase 2 review. ui.js had grown to 251 LOC across three
concerns; splits into:
- js/session-panel.js: createSessionPanel + renderSaveSlot + render
  SessionList + formatAge
- js/export.js: buildMarkdown + triggerMarkdownDownload + renderExport
  Slot + slugify
- js/ui.js: just renderSources (~15 LOC)

No behavior change. app.js imports update accordingly; send.js still
imports renderSources from ui.js.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Markdown frontmatter → block-style YAML

**Why:** Ia from the Phase 2 review. Current flow-style `vault: { enabled: false, topK: 5 }` is valid YAML but Obsidian won't recognize it as frontmatter. Block style is universal.

**Files:**
- Modify: `js/export.js` — `buildMarkdown`.

- [ ] **Step 1: Rewrite buildMarkdown's frontmatter**

In `js/export.js`, find the `frontmatter` local in `buildMarkdown`. Current:

```javascript
  const frontmatter = [
    "---",
    `name: ${exportedName}`,
    `exported: ${new Date().toISOString()}`,
    `vault: { enabled: ${vaultConfig.enabled}, topK: ${vaultConfig.topK} }`,
    "---",
    "",
  ].join("\n");
```

Replace with:

```javascript
  const safeName = exportedName.replace(/"/g, '\\"');
  const frontmatter = [
    "---",
    `name: "${safeName}"`,
    `exported: ${new Date().toISOString()}`,
    "vault:",
    `  enabled: ${vaultConfig.enabled}`,
    `  topK: ${vaultConfig.topK}`,
    "---",
    "",
  ].join("\n");
```

- [ ] **Step 2: Sanity-check**

```bash
cd ~/prompt-sandbox
node --check js/export.js && echo "syntax ok"
node --test js/*.test.js 2>&1 | tail -5
# Expected: 30/30 pass
```

- [ ] **Step 3: Manual browser verification**

Hard-refresh. Send a message, Sessions ▾ → Export → open downloaded `.md`:

- Frontmatter looks like:
  ```
  ---
  name: "your auto-name here"
  exported: 2026-04-18T…Z
  vault:
    enabled: false
    topK: 5
  ---
  ```
- Name with a double-quote in it (try `he said "hi"`) appears correctly escaped.
- The file, dropped into an Obsidian vault, shows `name`, `exported`, `vault.enabled`, `vault.topK` in its frontmatter panel (spot-check if you have Obsidian handy; otherwise trust the YAML parse).

- [ ] **Step 4: Commit**

```bash
git add js/export.js
git commit -m "$(cat <<'EOF'
Export Markdown frontmatter in block-style YAML

Ia from Phase 2 review. Flow-style vault: { … } parsed as valid YAML
but was not recognized as frontmatter by Obsidian. Switches to block
style (vault: then indented enabled / topK). Also quotes name and
escapes any embedded double quotes so names with punctuation survive.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Create `js/tokens.js` with TDD

**Why:** Pure token-counting helpers. The meter depends on these; isolating them lets us write real unit tests.

**Files:**
- Create: `js/tokens.js`
- Create: `js/tokens.test.js`

- [ ] **Step 1: Write the failing tests**

Create `js/tokens.test.js`:

```javascript
import { test } from "node:test";
import assert from "node:assert/strict";
import { approxTokens, sumMessages, breakdown } from "./tokens.js";

test("approxTokens: empty string is 0", () => {
  assert.equal(approxTokens(""), 0);
});

test("approxTokens: short string rounds up via /4", () => {
  assert.equal(approxTokens("hi"),   1);   // 2 / 4 = 0.5 → 1
  assert.equal(approxTokens("hello"), 2);  // 5 / 4 = 1.25 → 2
  assert.equal(approxTokens("a".repeat(8)), 2);  // 8 / 4 = 2
});

test("approxTokens: long string", () => {
  assert.equal(approxTokens("a".repeat(401)), 101);  // 401 / 4 = 100.25 → 101
});

test("approxTokens: handles non-string input as 0", () => {
  assert.equal(approxTokens(null),      0);
  assert.equal(approxTokens(undefined), 0);
});

test("sumMessages: empty array is 0", () => {
  assert.equal(sumMessages([]), 0);
});

test("sumMessages: sums content + fixed overhead per message", () => {
  const msgs = [
    { role: "system",    content: "a".repeat(8) },   // 2 tokens + 3 overhead = 5
    { role: "user",      content: "b".repeat(8) },   // 2 + 3 = 5
    { role: "assistant", content: "c".repeat(8) },   // 2 + 3 = 5
  ];
  assert.equal(sumMessages(msgs), 15);
});

test("sumMessages: skips falsy content but still counts overhead", () => {
  const msgs = [
    { role: "assistant", content: "" },
    { role: "user",      content: null },
  ];
  assert.equal(sumMessages(msgs), 6);   // 0 + 3 + 0 + 3
});

test("breakdown: returns system, history, draft, totalExact, totalApprox", () => {
  const messages = [
    { role: "system",    content: "a".repeat(40) },  // system: 10 + 3 = 13
    { role: "user",      content: "b".repeat(40) },  // history: 10 + 3 = 13
    { role: "assistant", content: "c".repeat(40) },  // history: 10 + 3 = 13
  ];
  const out = breakdown({ messages, draftText: "d".repeat(20), exactPromptTokens: 42 });
  assert.equal(out.system,       13);
  assert.equal(out.history,      26);   // two non-system messages
  assert.equal(out.draft,        5);    // 20 / 4
  assert.equal(out.totalExact,   42);
  assert.equal(out.totalApprox,  13 + 26 + 5);   // full approximate path
});

test("breakdown: messages with no system prefix returns system: 0", () => {
  const messages = [
    { role: "user", content: "x".repeat(8) },
  ];
  const out = breakdown({ messages, draftText: "", exactPromptTokens: 0 });
  assert.equal(out.system,       0);
  assert.equal(out.history,      5);    // 2 + 3
  assert.equal(out.draft,        0);
  assert.equal(out.totalApprox,  5);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test js/tokens.test.js`
Expected: all 9 tests fail — module not found.

- [ ] **Step 3: Write js/tokens.js**

```javascript
// Approximate token count from characters. ~4 chars/token for English.
// Good enough for live "how close am I to the limit" feedback; the
// meter's exact anchor from usage.prompt_tokens corrects this on each send.

const PER_MESSAGE_OVERHEAD = 3;  // rough: role tag, separators

export function approxTokens(text) {
  if (typeof text !== "string" || text.length === 0) return 0;
  return Math.ceil(text.length / 4);
}

export function sumMessages(messages) {
  let total = 0;
  for (const msg of messages) {
    total += approxTokens(msg.content);
    total += PER_MESSAGE_OVERHEAD;
  }
  return total;
}

export function breakdown({ messages, draftText, exactPromptTokens }) {
  let system  = 0;
  let history = 0;
  for (const msg of messages) {
    if (msg.role === "system" && system === 0) {
      system = approxTokens(msg.content) + PER_MESSAGE_OVERHEAD;
    } else {
      history += approxTokens(msg.content) + PER_MESSAGE_OVERHEAD;
    }
  }
  const draft       = approxTokens(draftText);
  const totalApprox = system + history + draft;
  return { system, history, draft, totalExact: exactPromptTokens, totalApprox };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test js/tokens.test.js`
Expected: 9/9 pass.

- [ ] **Step 5: Run all tests**

Run: `node --test js/*.test.js`
Expected: 39 pass / 0 fail (30 prior + 9 new).

- [ ] **Step 6: Commit**

```bash
git add js/tokens.js js/tokens.test.js
git commit -m "$(cat <<'EOF'
Add js/tokens.js pure token-counting helpers with tests

approxTokens (chars / 4, rounded up, handles non-string as 0),
sumMessages (per-message overhead of 3), and breakdown ({ system,
history, draft, totalExact, totalApprox }) for the meter tooltip.

No tokenizer dependency; chars/4 is accurate enough for the "how close
am I to the context window" feedback the meter provides, and the meter
snaps to the exact usage.prompt_tokens count on each stream completion.

9 tests against node:test covering empty input, boundary rounding,
non-string input, empty arrays, per-message overhead, and the
breakdown decomposition.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Extend `js/stream.js` to surface `usage`

**Why:** MLX (and every OpenAI-compatible streaming endpoint) emits a terminal SSE chunk with `usage.prompt_tokens`. `extractSSEDelta` currently returns only `{reasoning, content, done}`; extend it so the caller can capture `usage` on that chunk.

**Files:**
- Modify: `js/stream.js`
- Modify: `js/stream.test.js`

- [ ] **Step 1: Write the failing tests**

Append to `js/stream.test.js`:

```javascript
test("extractSSEDelta: usage chunk returns { usage } without reasoning/content", () => {
  const event = `data: {"choices":[{"delta":{}}],"usage":{"prompt_tokens":42,"completion_tokens":7,"total_tokens":49}}`;
  const d = extractSSEDelta(event);
  assert.ok(d, "expected a non-null delta");
  assert.equal(d.usage.prompt_tokens,     42);
  assert.equal(d.usage.completion_tokens,  7);
  assert.equal(d.usage.total_tokens,       49);
});

test("extractSSEDelta: content chunk without usage has usage undefined", () => {
  const event = `data: {"choices":[{"delta":{"content":"hi"}}]}`;
  const d = extractSSEDelta(event);
  assert.equal(d.content, "hi");
  assert.equal(d.usage, undefined);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test js/stream.test.js`
Expected: the two new tests fail (current impl returns no `usage` field).

- [ ] **Step 3: Update extractSSEDelta**

In `js/stream.js`, replace `extractSSEDelta` with:

```javascript
export function extractSSEDelta(event) {
  for (const line of event.split("\n")) {
    if (!line.startsWith("data:")) continue;
    const payload = line.slice(5).trim();
    if (payload === "[DONE]") return { done: true };
    try {
      const json  = JSON.parse(payload);
      const delta = json.choices?.[0]?.delta;
      const usage = json.usage;
      if (!delta && !usage) return null;
      return {
        reasoning: delta?.reasoning,
        content:   delta?.content,
        done:      false,
        usage,
      };
    } catch (err) {
      console.warn("Failed to parse SSE payload:", payload, err);
      return null;
    }
  }
  return null;
}
```

Behavior change summary: chunks that contain both `delta` and `usage` populate both fields; chunks with only `usage` (no delta object) now return a non-null result with `reasoning`/`content` undefined and `usage` populated — previously they returned `null`.

- [ ] **Step 4: Update send.js to surface usage**

In `js/send.js`'s `streamOnePane`, the inner `applyEvents` function currently looks like:

```javascript
    const applyEvents = (events) => {
      for (const event of events) {
        const delta = extractSSEDelta(event);
        if (!delta || delta.done) continue;
        const { reasoning: r, content: c } = delta;
        if (r || c) initSpans();
        if (r) { reasoning += r; reasoningEl.textContent = reasoning; }
        if (c) { content   += c; contentEl.textContent   = content;   }
        if (r || c) pane.log.scrollTop = pane.log.scrollHeight;
      }
    };
```

Change to (add a local `capturedUsage` above `applyEvents` — near where `reasoningEl` is declared — and capture usage):

```javascript
    let capturedUsage = null;

    const applyEvents = (events) => {
      for (const event of events) {
        const delta = extractSSEDelta(event);
        if (!delta || delta.done) continue;
        if (delta.usage) capturedUsage = delta.usage;
        const { reasoning: r, content: c } = delta;
        if (r || c) initSpans();
        if (r) { reasoning += r; reasoningEl.textContent = reasoning; }
        if (c) { content   += c; contentEl.textContent   = content;   }
        if (r || c) pane.log.scrollTop = pane.log.scrollHeight;
      }
    };
```

After the streaming loop + final flush succeed (right after `state.addAssistant(...)`), add:

```javascript
    if (capturedUsage && typeof pane.onUsage === "function") {
      pane.onUsage(capturedUsage);
    }
```

(We'll populate `pane.onUsage` in Task 7; for now the `typeof === "function"` guard makes it a no-op.)

- [ ] **Step 5: Run tests**

Run: `node --test js/*.test.js 2>&1 | tail -5`
Expected: 41 pass / 0 fail (39 prior + 2 new).

- [ ] **Step 6: Manual browser smoke**

Hard-refresh. Send a message. Streaming still renders. No console errors. The meter still doesn't exist yet (Task 7).

- [ ] **Step 7: Commit**

```bash
git add js/stream.js js/stream.test.js js/send.js
git commit -m "$(cat <<'EOF'
Surface usage from streaming SSE chunks

extractSSEDelta now returns { reasoning, content, done, usage } so
callers can capture token usage from the terminal chunk. Chunks
carrying only a usage object (no delta) previously returned null;
they now return a defined result with usage populated.

send.js's streamOnePane captures the most recent usage across all
events in the stream and passes it to pane.onUsage() on success if
the pane exposes that callback. Currently a no-op; Task 7's meter
wires pane.onUsage to meter.setExactPromptTokens.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `js/meter.js` + integration

**Why:** The meter itself. Per-pane factory that renders, listens to state changes + draft input, snaps to exact on each completion.

**Files:**
- Create: `js/meter.js`
- Modify: `js/app.js` — instantiate meters, wire `pane.onUsage`.
- Modify: `index.html` — meter CSS.

- [ ] **Step 1: Write js/meter.js**

```javascript
import { approxTokens, sumMessages, breakdown } from "./tokens.js";

export function createMeter({ pane, state, contextWindow, getDraftText }) {
  // Insert the meter element into the pane's prompt header, below the preview.
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

  let exactPromptTokens = 0;

  function render() {
    const draftText = typeof getDraftText === "function" ? getDraftText() : "";
    const used = exactPromptTokens > 0
      ? exactPromptTokens + approxTokens(draftText)
      : sumMessages(state.messages) + approxTokens(draftText);

    usedEl.textContent = used.toLocaleString();

    const pct = Math.min(100, (used / contextWindow) * 100);
    fillEl.style.width = `${pct.toFixed(1)}%`;

    el.classList.toggle("amber", pct > 75 && pct <= 90);
    el.classList.toggle("red",   pct > 90);

    const b = breakdown({ messages: state.messages, draftText, exactPromptTokens });
    el.title = `system ≈ ${b.system}, history ≈ ${b.history}, draft ≈ ${b.draft}`;
  }

  // Subscribe to state mutations and draft input events.
  const unsubState = state.subscribe(render);
  const draftEl    = typeof getDraftText === "function" ? getDraftText.el : null;
  // getDraftText is a function; if the caller wants live-update-on-keystroke,
  // they also pass an `onDraftInput(fn)` attach helper. See Task 7 integration.

  render();

  return {
    setExactPromptTokens(n) {
      exactPromptTokens = n;
      render();
    },
    render,
    destroy() {
      unsubState();
      el.remove();
    },
  };
}
```

The integration in Task 7 Step 3 handles wiring the draft `input` listener — `createMeter` doesn't attach it directly because the shared input lives outside `pane.section`.

- [ ] **Step 2: Add meter CSS in index.html**

In `index.html`'s `<style>` block, append:

```css
.meter {
  padding: 4px 14px 8px;
  font-size: 11px;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.meter-numbers { margin-bottom: 3px; }
.meter-used { color: var(--fg); }
.meter-bar {
  height: 4px;
  background: #1a1a1a;
  border-radius: 2px;
  overflow: hidden;
}
.meter-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.1s linear, background 0.2s;
  width: 0%;
}
.meter.amber .meter-fill { background: #e0a54a; }
.meter.red   .meter-fill { background: var(--error); }
```

- [ ] **Step 3: Wire meters into js/app.js**

In `js/app.js`:

At the top of the script body, add a new import:

```javascript
import { createMeter } from "./js/meter.js";
import { ACTIVE_MODEL } from "./js/config.js";
```

(If `ACTIVE_MODEL` is already imported for another reason, consolidate.)

After the existing `const paneA = createPane(...)` and `const stateA = createPaneState(...)` lines, instantiate `meterA`:

```javascript
let meterA = null;
let meterB = null;

function attachMeter(pane, state) {
  const meter = createMeter({
    pane,
    state,
    contextWindow: ACTIVE_MODEL.contextWindow,
    getDraftText: () => $input.value,
  });
  // Hook pane.onUsage so send.js's completion handler can feed the exact count.
  pane.onUsage = (usage) => {
    if (typeof usage.prompt_tokens === "number") {
      meter.setExactPromptTokens(usage.prompt_tokens);
    }
  };
  return meter;
}

meterA = attachMeter(paneA, stateA);
```

`$input` is the shared textarea ref already defined in the script. After its existing declaration, add an `input`-event listener that nudges both meters:

```javascript
$input.addEventListener("input", () => {
  meterA?.render();
  meterB?.render();
});
```

Update `enterCompare()` to create `meterB`; find the function definition:

```javascript
function enterCompare() {
  if (paneB) return;
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
}
```

Add one line before the final `}`:

```javascript
  meterB = attachMeter(paneB, stateB);
```

Update `exitCompare()` to destroy `meterB`. Find the function and add one line right after `paneB.section.remove();`:

```javascript
  meterB?.destroy();
  meterB = null;
```

- [ ] **Step 4: Static checks**

```bash
cd ~/prompt-sandbox
node --check js/meter.js && node --check js/app.js && echo "syntax ok"
node --test js/*.test.js 2>&1 | tail -5
# Expected: 41/41 pass
curl -s http://localhost:7777/js/meter.js | grep -c "export function createMeter"
# Expected: 1
curl -s http://localhost:7777/js/app.js | grep -c "attachMeter"
# Expected: 3 (def + paneA call + paneB call via enterCompare)
```

- [ ] **Step 5: Manual browser verification (REQUEST USER — DO NOT DRIVE)**

Report includes this checklist for the user:

1. Hard-refresh `http://localhost:7777/`.
2. Pane A shows a meter under the prompt preview: a numbers row `<N> / 128,000` and a thin blue bar near 0% full.
3. Expand the prompt area (click the preview) — meter moves naturally with the layout (stays in the header area).
4. Type 100 characters into the input — meter's numerator rises by ~25 tokens; bar barely moves.
5. Send "hi". When the response completes, the numerator snaps to the exact value MLX reports (cross-reference: DevTools → Network → the `/v1/chat/completions` response → `usage.prompt_tokens`).
6. Keep sending until the bar turns amber (>75%) then red (>90%). Hover the meter → tooltip shows `system ≈ N, history ≈ N, draft ≈ N`.
7. Click Compare → a second meter appears for Pane B at 0 / 128,000.
8. Typing in the shared input updates both meters live.
9. Click Single → Pane B's meter goes away with the pane; Pane A's meter is unchanged.
10. No console errors.

- [ ] **Step 6: DO NOT commit yet**

Controller will commit after user confirms. Suggested message:

```
Add js/meter.js per-pane token/context meter

createMeter mounts a small numbers + progress-bar element in the pane's
prompt header, subscribes to state.subscribe for mutation-driven
updates, and re-renders on draft-input events. Exact anchor comes from
pane.onUsage (called by send.js on stream completion with the MLX-
reported usage.prompt_tokens); draft delta is approxTokens(draftText).

Bar color thresholds: <=75% accent, >75% amber, >90% red. Tooltip shows
the token breakdown (system / history / draft). Context window comes
from ACTIVE_MODEL.contextWindow, so a future model switch updates the
meter automatically.

Pane A's meter is created at startup; Pane B's meter is created by
enterCompare and destroyed by exitCompare.
```

## Context

- **Working directory**: `/Users/troylatimer/prompt-sandbox`
- **Branch**: `main`
- **Prior Phase 3 commit**: Task 6 (stream usage extension). 41 tests pass.
- **`$input` ref**: already declared in `js/app.js` as the shared input textarea DOM ref.

---

## Task 8: Full acceptance verification + final cross-commit review

- [ ] **Step 1: All tests + services**

```bash
cd ~/prompt-sandbox
node --test js/*.test.js 2>&1 | tail -10
# Expected: 41/41 pass
curl -sf http://localhost:7777/ -o /dev/null && curl -sf http://localhost:8080/v1/models -o /dev/null && curl -sf http://localhost:8100/health && echo
# Expected: all three healthy
wc -l index.html js/*.js
# Expected: index.html ~270 LOC (down from ~530); js/app.js ~250 LOC; js/ui.js ~15 LOC
```

- [ ] **Step 2: Phase 1 + 2 regression checklist**

Hard-refresh. Verify:
- Default prompt preview; expand/collapse works.
- Send (vault on/off) streams a reply; sources chips when vault on.
- Reindex / health dot / Apply & Reset / New session / keyboard shortcuts all work.
- Compare toggle creates and tears down Pane B; parallel streams work.
- Sessions: save (single + A/B), load, delete, confirms all fire; localStorage entry correct.
- Export downloads a `.md` file with block-style YAML frontmatter.

- [ ] **Step 3: Phase 3 acceptance**

- Meter visible under each pane's prompt preview.
- Initial values: `~90 / 128,000` (system prompt + message overhead).
- Typing in the input updates numerator live.
- Sending snaps numerator to the MLX-reported `usage.prompt_tokens`.
- Color thresholds at 75% and 90%.
- Tooltip shows the breakdown.
- Compare creates a second meter; Single removes it.
- Meter + state.subscribe doesn't leak: verify by entering/exiting Compare several times — browser devtools Performance or just "click rapidly, no slowdown" is enough.

- [ ] **Step 4: Cross-commit final review (controller-driven)**

Dispatch a `superpowers:code-reviewer` subagent across `BASE=116f5c2` (Phase 3 spec commit) and `HEAD=<final>`. Controller handles any fix loops before declaring Phase 3 done.

- [ ] **Step 5: Remove the legacy config.js shims (optional cleanup)**

After the review, run:

```bash
grep -rn "from \"./config.js\".*\\bAPI_URL\\b\\|from \"./config.js\".*\\bMODEL\\b" js/
grep -rn "^import { API_URL\\|^import { MODEL" js/
```

If no matches, remove the `export const API_URL = ACTIVE_MODEL.endpoint;` and `export const MODEL = ACTIVE_MODEL.id;` lines from `js/config.js`. Re-run tests (`node --test js/*.test.js`) and the browser smoke check. Commit as a tiny cleanup if you choose to remove them.

- [ ] **Step 6: No additional commit required**

Task 8 is verification; no code change beyond the optional shim removal in Step 5.

---

## Self-review notes (applied inline)

- **Spec coverage**: every numbered section in the spec maps to a task in the map table above.
- **Placeholders**: none — every code step shows the actual code; every command step shows the actual command + expected output.
- **Type / name consistency**:
  - `ACTIVE_MODEL.id`, `ACTIVE_MODEL.endpoint`, `ACTIVE_MODEL.contextWindow` — consistent across Task 0 (def), Task 6 (send.js consumer), Task 7 (meter consumer).
  - `state.loadSnapshot({ systemPrompt, messages })` — same signature in the test (Task 2 Step 1), the impl (Task 2 Step 3), and the loadEntry refactor (Task 2 Step 5).
  - `state.subscribe(fn)` returns unsubscribe fn — consistent between test, impl, and meter consumer.
  - `extractSSEDelta` return shape `{ reasoning, content, done, usage }` — consistent between stream.js (Task 6), send.js consumer (Task 6 Step 4), meter/app integration (Task 7).
  - `pane.onUsage(usage)` — called by send.js (Task 6), assigned by app.js (Task 7). If app.js doesn't set it, send.js's `typeof === "function"` guard keeps it a no-op.
  - `createMeter({ pane, state, contextWindow, getDraftText })` — same in def (Task 7 Step 1) and consumer (Task 7 Step 3).
- **Scope**: Phase 3 bundles 5 pre-work items + the meter feature. 8 tasks total. Comparable to Phase 2 (11) and Phase 1 (14). Manageable.
- **Ambiguities resolved**:
  - Meter uses `exactPromptTokens + approxTokens(draft)` once `exactPromptTokens > 0`; before the first send, falls back to `sumMessages(state.messages) + approxTokens(draft)`. Explicit in meter.js's `render()`.
  - Stream chunks that carry only `usage` (no delta) now return a non-null result — behavior change documented in the commit message.
  - `applyPrompt` inlined to fire `notify` once rather than reset-then-overwrite which would fire twice — explicit in Task 2 Step 3 note.
