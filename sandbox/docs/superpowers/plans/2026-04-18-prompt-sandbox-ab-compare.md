# Prompt Sandbox Phase 1 — A/B Compare + UI Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add side-by-side A/B compare of two system prompts (same user input, same vault retrieval, parallel streaming responses) and refresh the single-pane layout, while keeping the "one HTML file served by `python3 -m http.server`, no npm, no framework" constraint.

**Architecture:** Decompose the current ~460-line `index.html` into browser-native ES modules under `js/`. Pure-logic modules (SSE parsing, pane state) get Node-native tests via `node --test`. DOM-facing modules (pane component, entry wiring) get manual browser verification against the spec's acceptance criteria. Ship the extraction as a behavior-unchanged regression gate, then layer A/B functionality, then UI polish.

**Tech Stack:** Vanilla JavaScript (ES modules via `<script type="module">`), CSS custom properties, Node 22+ `node:test` + `node:assert` for pure-logic tests (no package.json, no dependencies), `python3 -m http.server` for serving.

**Spec:** `docs/superpowers/specs/2026-04-18-prompt-sandbox-ab-compare.md`.

**Repo constraints:** No package.json, no npm, no build step. Tests run via `node --test js/*.test.js` (Node 22's `--test` rejects a bare directory, needs the shell glob). CSS stays inline in `index.html` (it is the one-file contract; only JS splits into modules).

---

## File layout after this plan

```
prompt-sandbox/
├── index.html                 ← markup + CSS + <script type="module"> entry
├── js/
│   ├── stream.js              ← pure: SSE buffer parser + delta extractor
│   ├── stream.test.js         ← node --test
│   ├── state.js               ← pure: createPaneState factory
│   ├── state.test.js          ← node --test
│   ├── vault.js               ← pingVaultHealth, fetchVaultContext, reindex
│   ├── ui.js                  ← createPane, togglePromptCollapse, DOM helpers
│   └── send.js                ← send(panes, userText, vaultConfig) orchestrator
```

## Task-map back to spec

| Spec section | Implementing task(s) |
|---|---|
| §1 Mode model + layout | 7, 8, 10 |
| §2 State + send behavior | 3, 5, 9 |
| §3 Visual refresh (collapsible prompt) | 10 |
| §3 Visual refresh (merged controls, typography) | 11 |
| §3 Visual refresh (pane identity) | 12 |
| File layout | 1–6 |
| Acceptance criteria | 13 |

---

## Task 0: Pre-flight — clean working tree

**Why:** The repo currently has three unrelated uncommitted items from earlier work (new `CLAUDE.md`, vault-health dot in `index.html`, `code_review.md.resolved` → `code_review.md` rename). The refactor in Task 1+ will thrash `index.html`; we want a clean baseline so regressions are attributable.

**Files:**
- Staged commit: `CLAUDE.md`
- Staged commit: `index.html` (vault-health dot additions, lines ~130–139, 177, 218, 441–459)
- Staged commit: `code_review.md` (rename from `code_review.md.resolved`)

- [ ] **Step 1: Verify starting state**

Run: `cd ~/prompt-sandbox && git status`
Expected: three items listed — new file `CLAUDE.md`, modified `index.html`, deleted `code_review.md.resolved` + untracked `code_review.md`.

- [ ] **Step 2: Commit CLAUDE.md**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
Add CLAUDE.md for agent onboarding

Documents the three-service architecture, the "one HTML file, no build"
constraint, the ephemeral vault-context splice pattern, and where to
edit what. Intended for Claude Code invocations on this repo.
EOF
)"
```

- [ ] **Step 3: Commit the vault-health dot**

```bash
git add index.html
git commit -m "$(cat <<'EOF'
Add vault-search health dot to the controls row

Small colored indicator next to the vault toggle: green when
http://localhost:8100/health responds OK, red when unreachable. Polled
on load and every 10s with a 2s AbortController timeout. Addresses the
resolved code review's "pinger for the Vault server" suggestion.
EOF
)"
```

- [ ] **Step 4: Commit the code-review rename**

```bash
git add code_review.md.resolved code_review.md
git status    # should show the rename as renamed R100 or similar
git commit -m "$(cat <<'EOF'
Rename code_review.md.resolved → code_review.md

The dot-resolved suffix was an ad-hoc convention; standard filename is
clearer now that the remaining suggestion (vault-health dot) is shipped.
EOF
)"
```

- [ ] **Step 5: Verify clean tree**

Run: `git status`
Expected: `nothing to commit, working tree clean`.

---

## Task 1: Create `js/` directory and extract stream.js with tests

**Why:** The SSE parser is pure, easy to test in isolation, and used by `send()` for every model response. Extracting and testing it first locks in the streaming contract before we refactor the caller.

**Files:**
- Create: `js/stream.js`
- Create: `js/stream.test.js`

- [ ] **Step 1: Create js/ directory**

```bash
mkdir js
```

- [ ] **Step 2: Write the failing tests**

Create `js/stream.test.js`:

```javascript
import { test } from "node:test";
import assert from "node:assert/strict";
import { parseSSEBuffer, extractSSEDelta } from "./stream.js";

test("parseSSEBuffer: complete events with trailing blank", () => {
  const buf = "data: 1\n\ndata: 2\n\n";
  const { events, remainder } = parseSSEBuffer(buf);
  assert.deepEqual(events, ["data: 1", "data: 2"]);
  assert.equal(remainder, "");
});

test("parseSSEBuffer: partial trailing event is returned as remainder", () => {
  const buf = "data: 1\n\ndata: par";
  const { events, remainder } = parseSSEBuffer(buf);
  assert.deepEqual(events, ["data: 1"]);
  assert.equal(remainder, "data: par");
});

test("parseSSEBuffer: empty buffer", () => {
  const { events, remainder } = parseSSEBuffer("");
  assert.deepEqual(events, []);
  assert.equal(remainder, "");
});

test("extractSSEDelta: content delta", () => {
  const event = `data: {"choices":[{"delta":{"content":"hello"}}]}`;
  assert.deepEqual(extractSSEDelta(event),
    { reasoning: undefined, content: "hello", done: false });
});

test("extractSSEDelta: reasoning delta", () => {
  const event = `data: {"choices":[{"delta":{"reasoning":"because"}}]}`;
  assert.deepEqual(extractSSEDelta(event),
    { reasoning: "because", content: undefined, done: false });
});

test("extractSSEDelta: [DONE] sentinel", () => {
  assert.deepEqual(extractSSEDelta("data: [DONE]"), { done: true });
});

test("extractSSEDelta: non-data line returns null", () => {
  assert.equal(extractSSEDelta("event: ping"), null);
});

test("extractSSEDelta: malformed JSON returns null", () => {
  assert.equal(extractSSEDelta("data: {not-json"), null);
});

test("extractSSEDelta: empty delta object yields undefined fields (not null)", () => {
  const event = `data: {"choices":[{"delta":{}}]}`;
  const d = extractSSEDelta(event);
  assert.deepEqual(d, { reasoning: undefined, content: undefined, done: false });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `node --test js/stream.test.js`
Expected: all tests fail with module-not-found errors for `./stream.js`.

- [ ] **Step 4: Write the minimal implementation**

Create `js/stream.js`:

```javascript
export function parseSSEBuffer(buffer) {
  if (buffer === "") return { events: [], remainder: "" };
  const parts = buffer.split("\n\n");
  const remainder = parts.pop();
  return { events: parts, remainder };
}

export function extractSSEDelta(event) {
  for (const line of event.split("\n")) {
    if (!line.startsWith("data:")) continue;
    const payload = line.slice(5).trim();
    if (payload === "[DONE]") return { done: true };
    try {
      const json = JSON.parse(payload);
      const delta = json.choices?.[0]?.delta;
      if (!delta) return null;
      return {
        reasoning: delta.reasoning,
        content: delta.content,
        done: false,
      };
    } catch {
      return null;
    }
  }
  return null;
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `node --test js/stream.test.js`
Expected: all 9 tests pass.

- [ ] **Step 6: Commit**

```bash
git add js/stream.js js/stream.test.js
git commit -m "$(cat <<'EOF'
Extract SSE parser to js/stream.js with tests

parseSSEBuffer splits a buffered chunk on blank-line event boundaries
and returns any trailing partial event as remainder. extractSSEDelta
pulls the delta object out of one event and tags [DONE] sentinels.

First step of the vanilla-modules refactor. Node's built-in test runner
is used for zero-dep unit tests.
EOF
)"
```

---

## Task 2: Extract vault.js (pingVaultHealth, fetchVaultContext, reindex)

**Why:** Vault calls are network I/O, clearly scoped, and used by both Phase 1 panes identically. No unit tests here — the call shapes are trivial and effectively tested by the browser acceptance pass in Task 13.

**Files:**
- Create: `js/vault.js`

- [ ] **Step 1: Write the module**

Create `js/vault.js`:

```javascript
const VAULT_URL = "http://localhost:8100";

export async function pingVaultHealth() {
  const ctrl    = new AbortController();
  const timeout = setTimeout(() => ctrl.abort(), 2000);
  try {
    const res = await fetch(`${VAULT_URL}/health`, { signal: ctrl.signal });
    return res.ok ? "ok" : "down";
  } catch {
    return "down";
  } finally {
    clearTimeout(timeout);
  }
}

export async function fetchVaultContext(query, k) {
  const ctrl    = new AbortController();
  const timeout = setTimeout(() => ctrl.abort(), 5000);
  try {
    const res = await fetch(`${VAULT_URL}/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, k }),
      signal: ctrl.signal,
    });
    clearTimeout(timeout);
    if (!res.ok) return { error: `HTTP ${res.status}` };
    const data    = await res.json();
    const results = data.results || [];
    if (results.length === 0) return null;
    const body    = results.map(r => r.text).join("\n---\n");
    const message = {
      role: "system",
      content: `Relevant notes from your vault:\n---\n${body}\n---`,
    };
    return { message, results };
  } catch (err) {
    clearTimeout(timeout);
    return { error: err.name === "AbortError" ? "timeout" : err.message };
  }
}

export async function reindexVault() {
  const res = await fetch(`${VAULT_URL}/reindex`, { method: "POST" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
```

- [ ] **Step 2: Sanity-check with curl that endpoints still match**

Run: `curl -sf http://localhost:8100/health`
Expected: `{"notes":<n>,"ok":true}`.

Run: `curl -sf -X POST http://localhost:8100/search -H 'Content-Type: application/json' -d '{"query":"test","k":1}' | head -c 200`
Expected: JSON with a `results` array.

- [ ] **Step 3: Commit**

```bash
git add js/vault.js
git commit -m "$(cat <<'EOF'
Extract vault-search calls to js/vault.js

pingVaultHealth, fetchVaultContext, reindexVault — three functions that
wrap the three vault-search endpoints. No DOM dependencies; callers
handle UI updates from the returned data.
EOF
)"
```

---

## Task 3: Extract state.js (pane state factory) with tests

**Why:** The pane-state shape is the core abstraction A/B mode depends on. Two panes = two instances of the same state object. Getting the factory right — and testing its invariants — keeps the fan-out in Task 9 mechanical.

**Files:**
- Create: `js/state.js`
- Create: `js/state.test.js`

- [ ] **Step 1: Write the failing tests**

Create `js/state.test.js`:

```javascript
import { test } from "node:test";
import assert from "node:assert/strict";
import { createPaneState } from "./state.js";

test("createPaneState: initializes with system message", () => {
  const s = createPaneState("hello");
  assert.equal(s.systemPrompt, "hello");
  assert.deepEqual(s.messages, [{ role: "system", content: "hello" }]);
});

test("addUser appends a user message", () => {
  const s = createPaneState("sp");
  s.addUser("hi");
  assert.deepEqual(s.messages, [
    { role: "system", content: "sp" },
    { role: "user", content: "hi" },
  ]);
});

test("addAssistant appends an assistant message", () => {
  const s = createPaneState("sp");
  s.addAssistant("ok");
  assert.deepEqual(s.messages[1], { role: "assistant", content: "ok" });
});

test("reset clears back to just the system message", () => {
  const s = createPaneState("sp");
  s.addUser("hi");
  s.addAssistant("ok");
  s.reset();
  assert.deepEqual(s.messages, [{ role: "system", content: "sp" }]);
});

test("applyPrompt replaces the prompt and clears history", () => {
  const s = createPaneState("old");
  s.addUser("hi");
  s.applyPrompt("new");
  assert.equal(s.systemPrompt, "new");
  assert.deepEqual(s.messages, [{ role: "system", content: "new" }]);
});

test("buildTurnMessages with null returns a copy of messages, not the live array", () => {
  const s = createPaneState("sp");
  s.addUser("hi");
  const turn = s.buildTurnMessages(null);
  assert.deepEqual(turn, s.messages);
  assert.notStrictEqual(turn, s.messages);
});

test("buildTurnMessages splices the vault message after system", () => {
  const s = createPaneState("sp");
  s.addUser("hi");
  const vault = { role: "system", content: "vault" };
  const turn = s.buildTurnMessages(vault);
  assert.deepEqual(turn, [
    { role: "system", content: "sp" },
    { role: "system", content: "vault" },
    { role: "user", content: "hi" },
  ]);
  // Original messages must NOT be mutated — vault injection is ephemeral.
  assert.deepEqual(s.messages, [
    { role: "system", content: "sp" },
    { role: "user", content: "hi" },
  ]);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test js/state.test.js`
Expected: all 7 tests fail with module-not-found errors.

- [ ] **Step 3: Write the minimal implementation**

Create `js/state.js`:

```javascript
export function createPaneState(initialPrompt) {
  return {
    systemPrompt: initialPrompt,
    messages: [{ role: "system", content: initialPrompt }],
    reset() {
      this.messages = [{ role: "system", content: this.systemPrompt }];
    },
    applyPrompt(newPrompt) {
      this.systemPrompt = newPrompt;
      this.reset();
    },
    addUser(text) {
      this.messages.push({ role: "user", content: text });
    },
    addAssistant(text) {
      this.messages.push({ role: "assistant", content: text });
    },
    buildTurnMessages(vaultMessage) {
      if (!vaultMessage) return [...this.messages];
      return [this.messages[0], vaultMessage, ...this.messages.slice(1)];
    },
  };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test js/state.test.js`
Expected: all 7 tests pass.

- [ ] **Step 5: Run all tests together**

Run: `node --test js/*.test.js`
Expected: 9 + 7 = 16 tests pass.

- [ ] **Step 6: Commit**

```bash
git add js/state.js js/state.test.js
git commit -m "$(cat <<'EOF'
Extract pane state factory to js/state.js with tests

createPaneState returns a per-pane state object with systemPrompt,
messages, and the four mutations (addUser/addAssistant/reset/
applyPrompt) plus buildTurnMessages, which implements the ephemeral
vault-context splice without mutating the underlying messages array.

Tested via node:test, including that buildTurnMessages does not mutate
state — that invariant is what makes A/B sends safe to run in parallel
against one vault retrieval.
EOF
)"
```

---

## Task 4: Extract ui.js (createPane DOM component + collapse helper)

**Why:** Each pane owns a slice of DOM. Encapsulating that in a factory means Task 9 can spin up a second pane by calling `createPane` again with a different container. This task produces the single-pane version; A/B-specific markup lands in Task 7.

**Files:**
- Create: `js/ui.js`

- [ ] **Step 1: Write js/ui.js**

```javascript
export function createPane({ id, container, initialPrompt }) {
  // Structure the pane owns:
  //   <section class="pane" data-pane-id="A">
  //     <header class="pane-prompt">
  //       <textarea class="pane-prompt-textarea">…</textarea>
  //       <button class="pane-apply-reset">Apply & Reset</button>
  //     </header>
  //     <main class="pane-log"></main>
  //   </section>
  const section = document.createElement("section");
  section.className        = "pane";
  section.dataset.paneId   = id;

  const header = document.createElement("header");
  header.className = "pane-prompt";

  const textarea = document.createElement("textarea");
  textarea.className   = "pane-prompt-textarea";
  textarea.spellcheck  = false;
  textarea.value       = initialPrompt;

  const applyReset = document.createElement("button");
  applyReset.className  = "pane-apply-reset";
  applyReset.textContent = "Apply & Reset";

  header.appendChild(textarea);
  header.appendChild(applyReset);

  const log = document.createElement("main");
  log.className = "pane-log";

  section.appendChild(header);
  section.appendChild(log);
  container.appendChild(section);

  return {
    id,
    section,
    textarea,
    applyReset,
    log,

    addBubble(role, text = "") {
      const el = document.createElement("div");
      el.className = "bubble " + role;
      el.textContent = text;
      log.appendChild(el);
      log.scrollTop = log.scrollHeight;
      return el;
    },

    addLogNote(text) {
      const note = document.createElement("div");
      note.className = "log-note";
      note.textContent = text;
      log.appendChild(note);
    },

    clearLog() {
      log.innerHTML = "";
    },
  };
}

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

- [ ] **Step 2: Sanity-check the module loads**

Run: `node --check js/ui.js`
Expected: no output (syntax valid).

- [ ] **Step 3: Commit**

```bash
git add js/ui.js
git commit -m "$(cat <<'EOF'
Add js/ui.js with createPane factory and renderSources helper

createPane builds the per-pane DOM (prompt header + log) under a given
container and returns handles for the textarea, Apply & Reset button,
log element, plus addBubble / addLogNote / clearLog helpers. One
instance = one pane; the pane constructor is identical for A and B.

Not wired into index.html yet — that lands in Task 6.
EOF
)"
```

---

## Task 5: Extract send.js (streaming orchestrator)

**Why:** `send()` is the hot path — it fetches vault context (once, shared), calls the model, parses the stream, and routes deltas into the pane. Extracting now, before A/B, keeps the single-pane version honest and makes Task 9 a fan-out change, not a rewrite.

**Files:**
- Create: `js/send.js`

- [ ] **Step 1: Write js/send.js**

```javascript
import { parseSSEBuffer, extractSSEDelta } from "./stream.js";
import { fetchVaultContext }                from "./vault.js";
import { renderSources }                    from "./ui.js";

const API_URL = "http://localhost:8080/v1/chat/completions";
const MODEL   = "mlx-community/gemma-4-26B-A4B-it-4bit";

export async function sendToPanes({ panes, userText, useVault, topK }) {
  // One shared vault retrieval per send. Panes see the same injected message.
  let vaultMessage  = null;
  let vaultResults  = null;
  if (useVault) {
    const k   = Math.max(1, Math.min(20, parseInt(topK, 10) || 5));
    const got = await fetchVaultContext(userText, k);
    if (got && got.message) {
      vaultMessage = got.message;
      vaultResults = got.results;
    } else if (got && got.error) {
      for (const p of panes) p.pane.addLogNote("Vault search unavailable; sending without context.");
    }
  }

  // Fire one request per pane in parallel.
  await Promise.all(panes.map(({ state, pane }) =>
    streamOnePane({ state, pane, userText, vaultMessage, vaultResults })));
}

async function streamOnePane({ state, pane, userText, vaultMessage, vaultResults }) {
  state.addUser(userText);
  pane.addBubble("user", userText);

  const turnMessages = state.buildTurnMessages(vaultMessage);

  const bubble = pane.addBubble("assistant", "Thinking…");
  bubble.classList.add("pending");

  try {
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
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer      = "";
    let reasoning   = "";
    let content     = "";
    let reasoningEl = null;
    let contentEl   = null;

    const initSpans = () => {
      if (reasoningEl) return;
      bubble.textContent = "";
      bubble.classList.remove("pending");
      reasoningEl = document.createElement("span");
      reasoningEl.className = "reasoning";
      contentEl = document.createElement("span");
      contentEl.className = "content";
      bubble.appendChild(reasoningEl);
      bubble.appendChild(contentEl);
    };

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

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const { events, remainder } = parseSSEBuffer(buffer);
      buffer = remainder;
      applyEvents(events);
    }
    // Flush the decoder's internal state and any residual event.
    buffer += decoder.decode();
    if (buffer.trim()) {
      const { events } = parseSSEBuffer(buffer + "\n\n");
      applyEvents(events);
    }

    state.addAssistant(content || reasoning);
    if (vaultResults) renderSources(bubble, vaultResults);
  } catch (err) {
    bubble.classList.add("error");
    bubble.textContent = `⚠ ${err.message}`;
  }
}
```

- [ ] **Step 2: Sanity-check the module loads**

Run: `node --check js/send.js`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add js/send.js
git commit -m "$(cat <<'EOF'
Add js/send.js — per-pane streaming orchestrator

sendToPanes takes an array of {state, pane} objects, performs a single
shared vault retrieval, then fans out one /v1/chat/completions request
per pane in parallel. streamOnePane handles the SSE loop and writes
deltas into its pane's DOM via the handles from createPane.

Not wired into index.html yet — that lands in Task 6.
EOF
)"
```

---

## Task 6: Rewire `index.html` to use the modules (regression gate — single-pane behavior unchanged)

**Why:** This is the riskiest task because it replaces the entire inline `<script>` with a module-loading entry point. After it, behavior must be identical to before. Nothing about A/B yet.

**Files:**
- Modify: `index.html` — replace the `<script>` block; keep CSS + markup intact for now.

- [ ] **Step 1: Rewrite the script block**

Replace everything from `<script>` (line 192) to `</script>` (line 460) inclusive with:

```html
<script type="module">
import { createPaneState }                      from "./js/state.js";
import { createPane }                           from "./js/ui.js";
import { sendToPanes }                          from "./js/send.js";
import { pingVaultHealth, reindexVault }        from "./js/vault.js";

const DEFAULT_SYSTEM_PROMPT = `Role: You are my Lead Strategic Advisor and Decision Scientist.
Objective: Help me reach better conclusions by identifying my blind spots and logical fallacies.
Protocol:
Steel-manning: Before critiquing, summarize my argument back to me to prove you understand it perfectly.
Pre-Mortem: If I propose a plan, tell me three specific ways it could realistically fail in 12 months.
Inversion: Ask me, "What would I have to do to ensure this project fails?" to help me avoid those pitfalls.
Occam's Razor: Challenge me to find the simplest possible version of my idea.
Second-Order Effects: Always ask "And then what?" to explore the long-term consequences of my choice.
Tone: Brutally honest, intellectually rigorous, and concise. No fluff.`;

// Single pane for now. Task 7 adds Pane B.
const paneContainer = document.getElementById("pane-container");
const stateA = createPaneState(DEFAULT_SYSTEM_PROMPT);
const paneA  = createPane({ id: "A", container: paneContainer, initialPrompt: DEFAULT_SYSTEM_PROMPT });

const activePanes = () => [{ state: stateA, pane: paneA }];

paneA.applyReset.addEventListener("click", () => {
  stateA.applyPrompt(paneA.textarea.value);
  paneA.clearLog();
});

// Shared controls
const $input        = document.getElementById("input");
const $send         = document.getElementById("send");
const $newSession   = document.getElementById("new-session");
const $useVault     = document.getElementById("use-vault");
const $topK         = document.getElementById("top-k");
const $reindex      = document.getElementById("reindex");
const $vaultStatus  = document.getElementById("vault-status");
const $vaultHealth  = document.getElementById("vault-health");

async function handleSend() {
  if ($send.disabled) return;
  const text = $input.value.trim();
  if (!text) return;
  $input.value = "";
  $send.disabled = true;
  try {
    await sendToPanes({
      panes:    activePanes(),
      userText: text,
      useVault: $useVault.checked,
      topK:     $topK.value,
    });
  } finally {
    $send.disabled = false;
  }
}

$send.addEventListener("click", handleSend);
$input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
});

$newSession.addEventListener("click", () => {
  for (const { state, pane } of activePanes()) {
    state.reset();
    pane.clearLog();
  }
});

$reindex.addEventListener("click", async () => {
  $reindex.disabled = true;
  $vaultStatus.textContent = "Reindexing…";
  try {
    const data = await reindexVault();
    $vaultStatus.textContent =
      `Indexed: +${data.added} new, ${data.updated} updated, ${data.deleted} deleted (${data.unchanged} unchanged)`;
  } catch (err) {
    $vaultStatus.textContent = `Reindex failed: ${err.message}`;
  } finally {
    $reindex.disabled = false;
    setTimeout(() => { $vaultStatus.textContent = ""; }, 6000);
  }
});

async function tickVaultHealth() {
  const state = await pingVaultHealth();
  $vaultHealth.className = `health-dot ${state}`;
  $vaultHealth.title = state === "ok" ? "Vault search: online" : "Vault search: unreachable";
}
tickVaultHealth();
setInterval(tickVaultHealth, 10000);
</script>
```

- [ ] **Step 2: Swap the old single-pane DOM scaffolding for a pane container**

Replace lines 171–184 of the current `index.html`:

```html
<header class="system-prompt">
  <textarea id="system-prompt" spellcheck="false"></textarea>
  <button id="apply-reset">Apply &amp; Reset</button>
</header>

<header class="vault-controls">
  <span class="health-dot" id="vault-health" title="Vault search: checking…"></span>
  <label><input type="checkbox" id="use-vault"> Use vault context</label>
  <label>top K: <input type="number" id="top-k" min="1" max="20" value="5"></label>
  <button id="reindex" class="secondary">Reindex</button>
  <span class="status" id="vault-status"></span>
</header>

<main class="log" id="log"></main>
```

With:

```html
<header class="vault-controls">
  <span class="health-dot" id="vault-health" title="Vault search: checking…"></span>
  <label><input type="checkbox" id="use-vault"> Use vault context</label>
  <label>top K: <input type="number" id="top-k" min="1" max="20" value="5"></label>
  <button id="reindex" class="secondary">Reindex</button>
  <span class="status" id="vault-status"></span>
</header>

<main class="pane-container" id="pane-container"></main>
```

Note `<main class="log">` is gone; each pane now creates its own `<main class="pane-log">`.

- [ ] **Step 3: Adjust CSS to match the new structure**

Inside the `<style>` block:

1. **Remove** the rule `main.log { ... }` (current lines 64–71).
2. **Add** a `.pane-container` rule and a `.pane` / `.pane-log` / `.pane-prompt` set. Paste inside `<style>`, just before the `.bubble` rule:

```css
.pane-container {
  flex: 1;
  display: flex;
  min-height: 0;
}
.pane {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
}
.pane + .pane { border-left: 1px solid var(--border); }
.pane-prompt {
  padding: 12px;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
  display: flex;
  gap: 8px;
}
.pane-prompt-textarea {
  flex: 1;
  min-height: 90px;
  background: #111;
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 8px;
  font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
  resize: vertical;
}
.pane-log {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}
```

3. **Remove** the rule `header.system-prompt { ... }` and `header.system-prompt textarea { ... }` (current lines 30–47) — the pane owns these now.

4. **Adjust** `.pane-apply-reset` styling. It inherits from `button`, so add:

```css
.pane-apply-reset { }   /* inherits .button; style separately later if needed */
```

(Trivial rule as a placeholder; Task 11 expands it.)

- [ ] **Step 4: Ensure the stack is running**

Run: `cd ~/prompt-sandbox && curl -sf http://localhost:7777/ -o /dev/null && curl -sf http://localhost:8080/v1/models -o /dev/null && echo "up"`
Expected: `up`. If not, run `./launch.command`.

- [ ] **Step 5: Hard-refresh the browser at http://localhost:7777/ and verify regression parity**

Checklist — must all be TRUE:
- Default prompt is visible in the pane's textarea.
- DevTools console: no errors.
- Send "hi" with vault off → assistant streams, source chips absent.
- Toggle vault on, send "what have I written about…" → sources chips appear under the assistant bubble.
- Reindex button shows the "Indexed: +N new…" status.
- Vault-health dot is green; tooltip "Vault search: online".
- Apply & Reset clears the conversation and applies an edited prompt.
- New session clears the conversation, preserves the prompt.
- Enter sends, Shift+Enter newlines.

Any failure: diff against the original inline script; look for missing imports, typos in DOM ids, or a CSS rule that's dropped.

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "$(cat <<'EOF'
Wire index.html to ES modules; single-pane behavior unchanged

Replaces the ~270-line inline <script> with a <script type="module">
entry that imports from js/state.js, js/ui.js, js/send.js, js/vault.js.
DOM structure changes: the single <main class="log"> log is replaced
by a <main id="pane-container"> that createPane mounts into. System
prompt + apply-reset are now owned by the pane component, not by the
top header.

Manual regression: default prompt render, send (vault off/on), reindex,
health dot, apply-reset, new session, keyboard shortcuts.
EOF
)"
```

---

## Task 7: Add Compare toggle and mount Pane B (hidden — structure only)

**Why:** Get the DOM scaffolding for two panes in place before wiring state. When this task is done, clicking Compare creates Pane B visually but sends still only go to Pane A; Task 8 fixes that.

**Files:**
- Modify: `index.html` — add toggle button, compare container CSS, two-pane layout rule.

- [ ] **Step 1: Add Compare toggle to the controls row**

In `index.html`, inside `<header class="vault-controls">`, insert before `<span class="health-dot" …>`:

```html
<button id="compare-toggle" class="secondary" aria-pressed="false">Compare</button>
```

- [ ] **Step 2: Add the compare-active layout rule**

Inside `<style>`, append:

```css
.pane-container.compare      { /* flex-row is already default */ }
.pane-container.compare .pane { flex: 1 1 0; }
```

(Currently `.pane-container` is `display: flex` with `flex: 1` on `.pane`, so two panes stack side-by-side naturally. The rule exists for later Task 12 accents to hook into.)

- [ ] **Step 3: Wire the toggle in the script block**

Append inside the `<script type="module">`:

```javascript
const $compareToggle = document.getElementById("compare-toggle");
let paneB  = null;
let stateB = null;

function enterCompare() {
  if (paneB) return;
  stateB = createPaneState(DEFAULT_SYSTEM_PROMPT);
  paneB  = createPane({ id: "B", container: paneContainer, initialPrompt: DEFAULT_SYSTEM_PROMPT });
  paneB.applyReset.addEventListener("click", () => {
    stateB.applyPrompt(paneB.textarea.value);
    paneB.clearLog();
  });
  paneContainer.classList.add("compare");
  $compareToggle.setAttribute("aria-pressed", "true");
  $compareToggle.textContent = "Single";
}

function exitCompare() {
  if (!paneB) return;
  if (stateB.messages.length > 1) {
    const ok = confirm("Pane B has a conversation. Discard it?");
    if (!ok) return;
  }
  paneB.section.remove();
  paneB  = null;
  stateB = null;
  paneContainer.classList.remove("compare");
  $compareToggle.setAttribute("aria-pressed", "false");
  $compareToggle.textContent = "Compare";
}

$compareToggle.addEventListener("click", () => {
  if (paneB) exitCompare(); else enterCompare();
});
```

- [ ] **Step 4: Hard-refresh and verify**

- Compare button in the controls row, text "Compare".
- Click → second pane appears side by side; button now says "Single".
- Click again → second pane disappears; button back to "Compare". No confirm (B was empty).
- Send still works to Pane A in both states (B remains empty on send — fixed in Task 8).
- Console has no errors.

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "$(cat <<'EOF'
Add Compare toggle and mount Pane B (DOM only)

Clicking Compare creates a second pane side-by-side with an empty
conversation and the default system prompt. Clicking it again tears
Pane B down, with a confirm if B has any history. Sends still only
go to Pane A — wiring lands in the next task.
EOF
)"
```

---

## Task 8: Wire A/B into `activePanes()` — sends fan out to both

**Why:** Tiny but functional task. Changes `activePanes()` to include Pane B when present; because `sendToPanes` already takes an array and fans out in parallel, nothing else changes.

**Files:**
- Modify: `index.html` — one-line change to `activePanes()`.

- [ ] **Step 1: Update activePanes**

Replace:

```javascript
const activePanes = () => [{ state: stateA, pane: paneA }];
```

with:

```javascript
const activePanes = () => paneB
  ? [{ state: stateA, pane: paneA }, { state: stateB, pane: paneB }]
  : [{ state: stateA, pane: paneA }];
```

- [ ] **Step 2: Hard-refresh and verify parallel behavior**

Precondition: all three services up; vault off for the first check to remove retrieval as a variable.

- Single pane (Compare off): send "one" → Pane A responds as before. ✓
- Compare on, send "two" → both panes stream simultaneously. Two "Thinking…" bubbles appear; both resolve to streamed text. ✓
- Edit Pane B's system prompt to something different (e.g., "You are a pirate. Always answer in pirate voice.") and hit Pane B's Apply & Reset. Then send "describe a sandwich" → Pane A gives a normal answer, Pane B gives a pirate answer. ✓
- Kill MLX mid-stream in another terminal: `lsof -ti :8080 | xargs kill`. Both panes get error bubbles, no other pane is frozen. Restart MLX via `bash ~/prompt-sandbox/_run-mlx.sh &` in a background shell. ✓

- [ ] **Step 3: Verify shared vault retrieval**

Open DevTools → Network tab. Filter by "chat/completions". With vault on, top-K=3, Compare on, send a message.

Inspect both request bodies. The `messages` arrays should both contain an identical `{ role: "system", content: "Relevant notes from your vault:\n---\n…" }` entry at index 1. (Everything at index 0 and 2+ is per-pane.) Copy each body into `jq` or a diff tool to confirm byte-identity of the vault message.

- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "$(cat <<'EOF'
Fan send out to both panes in A/B mode

activePanes now returns [A, B] when Pane B exists. sendToPanes was
already built to take an array and Promise.all the per-pane streams,
so this completes the parallel A/B behavior — one shared vault call,
two independent /v1/chat/completions streams.

Verified: both panes stream simultaneously; MLX kill mid-stream errors
both panes without freezing either; vault retrieval splices an
identical system message into both requests.
EOF
)"
```

---

## Task 9: Make `New session` scope-aware, and polish Exit-Compare copy

**Why:** Small cleanups surfaced by Task 8. New session should clear all active panes (it already does via `activePanes()` — just verify). Exit confirm copy is minor; tightening it once here beats re-touching it later.

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Verify New session already clears both panes**

Hard-refresh, Compare on, send a message to both. Click New session. Both logs clear, both prompts persist.

If it fails (it should not, since the handler already iterates `activePanes()`): investigate.

- [ ] **Step 2: Tighten exit-compare confirm copy**

Replace in `exitCompare`:

```javascript
const ok = confirm("Pane B has a conversation. Discard it?");
```

with:

```javascript
const ok = confirm("Exit compare mode? Pane B's conversation will be discarded.");
```

- [ ] **Step 3: Commit**

```bash
git add index.html
git commit -m "$(cat <<'EOF'
Polish compare-exit confirm copy; verify New session scope

Tightens the exit-compare dialog wording. Confirms via manual test that
New session iterates activePanes() correctly and clears both A and B
when compare is on, keeping system prompts intact.
EOF
)"
```

---

## Task 10: Collapsible system-prompt area

**Why:** The prompt textareas occupy ~120px per pane at rest. In A/B mode that's 240px. Collapsing to a one-line preview gets the conversation back its screen real estate; expansion on click retains editability.

**Files:**
- Modify: `js/ui.js` — change `createPane` markup to include a preview + expanded state.
- Modify: `index.html` — CSS for the collapsed/expanded states.

- [ ] **Step 1: Update createPane to emit the collapsible markup**

In `js/ui.js`, replace the `createPane` DOM-construction section (the block starting at `const section = document.createElement("section");` and ending at `container.appendChild(section);`) with:

```javascript
const section = document.createElement("section");
section.className      = "pane";
section.dataset.paneId = id;

const header = document.createElement("header");
header.className = "pane-prompt collapsed";

const preview = document.createElement("button");
preview.className  = "pane-prompt-preview";
preview.type       = "button";
preview.textContent = oneLinePreview(initialPrompt);

const textareaWrap = document.createElement("div");
textareaWrap.className = "pane-prompt-expanded";

const textarea = document.createElement("textarea");
textarea.className  = "pane-prompt-textarea";
textarea.spellcheck = false;
textarea.value      = initialPrompt;

const applyReset = document.createElement("button");
applyReset.className   = "pane-apply-reset";
applyReset.textContent = "Apply & Reset";

textareaWrap.appendChild(textarea);
textareaWrap.appendChild(applyReset);
header.appendChild(preview);
header.appendChild(textareaWrap);

preview.addEventListener("click", () => {
  header.classList.toggle("collapsed");
  if (!header.classList.contains("collapsed")) textarea.focus();
});

// When Apply & Reset fires, the caller updates state.systemPrompt;
// we mirror that by refreshing the preview text. Callers must trigger
// pane.refreshPreview() after applying.
const refreshPreview = () => {
  preview.textContent = oneLinePreview(textarea.value);
};

const log = document.createElement("main");
log.className = "pane-log";

section.appendChild(header);
section.appendChild(log);
container.appendChild(section);
```

Add at the top of `js/ui.js` (outside `createPane`):

```javascript
function oneLinePreview(text) {
  const firstLine = text.split("\n", 1)[0].trim();
  if (firstLine.length <= 60) return firstLine || "(empty prompt — click to edit)";
  return firstLine.slice(0, 57) + "…";
}
```

And extend the returned object to include `refreshPreview`:

```javascript
return {
  id, section, textarea, applyReset, log,
  refreshPreview,
  addBubble(role, text = "") { /* …unchanged… */ },
  addLogNote(text)            { /* …unchanged… */ },
  clearLog()                  { /* …unchanged… */ },
};
```

- [ ] **Step 2: Call refreshPreview from the Apply & Reset handler in index.html**

In both Apply & Reset handlers (Pane A and Pane B), after `stateX.applyPrompt(…)` and `paneX.clearLog()`:

```javascript
paneA.refreshPreview();
```

and

```javascript
paneB.refreshPreview();
```

- [ ] **Step 3: Add CSS for the collapsed/expanded states**

In `<style>`, replace the old `.pane-prompt { ... }` + `.pane-prompt-textarea { ... }` rules with:

```css
.pane-prompt {
  background: var(--panel);
  border-bottom: 1px solid var(--border);
}
.pane-prompt-preview {
  display: block;
  width: 100%;
  text-align: left;
  background: transparent;
  color: var(--muted);
  border: 0;
  padding: 10px 14px;
  font: 12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace;
  cursor: pointer;
}
.pane-prompt-preview:hover { color: var(--fg); }
.pane-prompt.collapsed .pane-prompt-expanded { display: none; }
.pane-prompt-expanded {
  display: flex;
  gap: 8px;
  padding: 0 12px 12px 12px;
}
.pane-prompt-textarea {
  flex: 1;
  min-height: 90px;
  background: #111;
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 8px;
  font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
  resize: vertical;
}
```

- [ ] **Step 4: Hard-refresh and verify**

- On load: each pane shows a collapsed one-line preview of the default prompt ("Role: You are my Lead Strategic Advisor and Deci…"). Conversation area is taller than before.
- Click the preview → full textarea + Apply & Reset appear inline; textarea is focused.
- Edit the prompt, click Apply & Reset → preview line updates to reflect the new first line; conversation clears.
- Click the preview again → collapses.
- Compare on: both panes show independent previews; expanding one doesn't expand the other.

- [ ] **Step 5: Commit**

```bash
git add js/ui.js index.html
git commit -m "$(cat <<'EOF'
Collapsible system-prompt area per pane

Each pane now shows a one-line preview by default (first 57 chars of
the first line). Clicking the preview expands the textarea + Apply &
Reset inline; clicking again collapses. Apply & Reset refreshes the
preview to reflect the new prompt. Independent per pane in A/B mode.

Recovers ~100px of vertical space per pane without hiding the current
applied prompt from view.
EOF
)"
```

---

## Task 11: Merged controls strip + typography refresh + role tags

**Why:** Bundles the remaining small UI improvements. None are structurally risky; all are local CSS/JS tweaks.

**Files:**
- Modify: `index.html` — CSS tweaks, controls-strip ordering, bubble markup via ui.js.
- Modify: `js/ui.js` — bubble creation adds role tag.

- [ ] **Step 1: Reorder the controls strip**

In `index.html`, re-order the children of `<header class="vault-controls">` so the layout reads: Compare, New session, Vault-health dot, Use vault checkbox, top-K, Reindex, status.

Move the existing `<button id="new-session">` out of `<footer class="input-row">` and into the controls header after `<button id="compare-toggle">`. Update the footer accordingly:

```html
<footer class="input-row">
  <textarea id="input" placeholder="Message (Enter to send, Shift+Enter for newline)"></textarea>
  <button id="send">Send</button>
</footer>
```

- [ ] **Step 2: Update vault-controls CSS for tighter, unified strip**

Replace `header.vault-controls { ... }` with:

```css
header.vault-controls {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 6px 12px;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
  color: var(--fg);
  font-size: 13px;
}
header.vault-controls .spacer { flex: 1; }
```

And inside the controls header in `index.html`, insert a spacer before the final `<span class="status" …>`:

```html
<span class="spacer"></span>
<span class="status" id="vault-status"></span>
```

- [ ] **Step 3: Add role tags above bubbles**

In `js/ui.js`, update `addBubble` to optionally prepend a role tag line. Simplest approach: render the role word above the bubble as a separate muted element. Replace the existing `addBubble`:

```javascript
addBubble(role, text = "") {
  const wrap = document.createElement("div");
  wrap.className = "bubble-wrap " + role;

  const tag = document.createElement("div");
  tag.className = "bubble-role";
  tag.textContent = role === "user" ? "You" : role === "assistant" ? "Assistant" : role;
  wrap.appendChild(tag);

  const el = document.createElement("div");
  el.className = "bubble " + role;
  el.textContent = text;
  wrap.appendChild(el);

  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;
  return el;
},
```

- [ ] **Step 4: Add typography + role-tag CSS**

In `<style>`, append:

```css
.bubble-wrap {
  display: flex;
  flex-direction: column;
  max-width: 80%;
}
.bubble-wrap.user      { align-self: flex-end;   align-items: flex-end;   }
.bubble-wrap.assistant { align-self: flex-start; align-items: flex-start; }
.bubble-role {
  font-size: 11px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 2px 2px;
}
.bubble { max-width: 100%; font-size: 14.5px; line-height: 1.55; }
```

And remove the old `.bubble.user { align-self: flex-end; ... }` / `.bubble.assistant { align-self: flex-start; ... }` — alignment now lives on the wrapper.

- [ ] **Step 5: Hard-refresh and verify**

- Controls strip: Compare | New session | health-dot | Use vault | top-K | Reindex | (status pushed right).
- Footer: just input + Send.
- Send a message: "You" label above user bubble aligned to the right; "Assistant" label above the assistant bubble aligned to the left; existing reasoning/content spans intact; pending "Thinking…" works.
- Vault sources still render under the assistant bubble.
- Pulse animation still plays while pending.

- [ ] **Step 6: Commit**

```bash
git add index.html js/ui.js
git commit -m "$(cat <<'EOF'
Merge controls strip, add role tags above bubbles, typography refresh

Relocates New session into the top controls row next to Compare, pushes
vault-status to the right with a spacer, and compacts the strip
vertically. Bubbles now sit under uppercase muted "You" / "Assistant"
tags for scanability. Slight bump to bubble font size and line height.
EOF
)"
```

---

## Task 12: Pane identity accents in A/B mode

**Why:** Small visual distinction makes it obvious which pane you're reading or editing. Accents on pane headers only — not on bubbles — to keep message content clean.

**Files:**
- Modify: `index.html` — CSS additions.

- [ ] **Step 1: Add accent palette**

In the `:root` block inside `<style>`, add:

```css
--accent-a: #6ea8fe;   /* matches existing --accent */
--accent-b: #a78bfa;
```

- [ ] **Step 2: Add pane-specific header accents, active only in compare mode**

Append to `<style>`:

```css
.pane-container.compare .pane[data-pane-id="A"] .pane-prompt { border-top: 2px solid var(--accent-a); }
.pane-container.compare .pane[data-pane-id="B"] .pane-prompt { border-top: 2px solid var(--accent-b); }
.pane-container.compare .pane::before {
  content: attr(data-pane-id);
  display: block;
  align-self: flex-start;
  padding: 2px 8px;
  margin: 6px 0 0 12px;
  font-size: 11px;
  font-weight: 600;
  border-radius: 10px;
}
.pane-container.compare .pane[data-pane-id="A"]::before { background: var(--accent-a); color: #111; }
.pane-container.compare .pane[data-pane-id="B"]::before { background: var(--accent-b); color: #111; }
```

- [ ] **Step 3: Hard-refresh and verify**

- Single-pane mode (Compare off): no "A" badge, no accent border — pane looks like it does today.
- Compare on: Pane A shows a small blue "A" badge and a thin blue top-border on its prompt header; Pane B shows a purple "B" badge and purple top-border. Bubbles are unchanged in both panes.
- Exit Compare: accents disappear from Pane A instantly.

- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "$(cat <<'EOF'
Add A/B pane accents (header border + corner badge)

In compare mode only: Pane A gets a blue top-accent on its prompt
header plus a small blue "A" badge; Pane B gets a purple "B". Single-
pane mode is unchanged. Accents stay off the bubbles to keep the
message content uniform between panes.
EOF
)"
```

---

## Task 13: Full acceptance verification against the spec

**Why:** Ground the implementation in the spec's acceptance criteria before calling Phase 1 done.

**Files:** None modified. Verification pass.

- [ ] **Step 1: Ensure the stack is up**

Run: `curl -sf http://localhost:7777/ -o /dev/null && curl -sf http://localhost:8080/v1/models -o /dev/null && curl -sf http://localhost:8100/health && echo`
Expected: three services reachable; vault returns `{"notes":N,"ok":true}`. If not, `./launch.command` from the repo root.

- [ ] **Step 2: Run all unit tests**

Run: `cd ~/prompt-sandbox && node --test js/*.test.js`
Expected: 16 tests pass across `stream.test.js` and `state.test.js`.

- [ ] **Step 3: Single-pane regression checklist**

Hard-refresh at `http://localhost:7777/`. Verify each:
- Default prompt preview shown; click to expand; edit; Apply & Reset updates preview and clears conversation.
- Send → user bubble with "You" tag, streamed assistant response with "Assistant" tag.
- Vault toggle on + Send → sources chips under assistant bubble; identical text also appears (indirectly) in the context.
- Reindex → status text reports counts, then clears after 6s.
- Vault-health dot: green initially; `lsof -ti :8100 | xargs kill` turns it red within 10s; `bash ~/prompt-sandbox/_run-vault.sh` (in a new terminal) → green within ~10s of `/health` responding.
- Enter sends, Shift+Enter newlines.

- [ ] **Step 4: A/B acceptance checklist**

Click Compare. Verify:
- Pane B appears with its own preview (default prompt), empty log.
- "A" and "B" badges + accent borders present.
- Expand Pane B's prompt, change to a visibly different persona ("Respond only in haiku."), Apply & Reset.
- Send "describe a sandwich" → both panes stream simultaneously; Pane A gives normal prose, Pane B gives a haiku.
- Network tab confirms two `/v1/chat/completions` requests; vault-off for this check.
- Toggle vault on, top-K=3, send again. Network tab shows both request bodies contain an identical injected system message at index 1.
- `lsof -ti :8080 | xargs kill` mid-stream → both panes show error bubbles; neither is frozen. Restart MLX: `bash ~/prompt-sandbox/_run-mlx.sh &`.
- Click Compare again → confirm dialog fires (Pane B has history); accept → Pane B is gone, Pane A preserved. Accents vanish.
- Click Compare again → new Pane B appears empty with default prompt.

- [ ] **Step 5: Final launch check**

Run: `pkill -f mlx_lm.server; pkill -f "http.server 7777"; pkill -f "python server.py"; sleep 2; ./launch.command`
Expected: all three services come up, browser opens, dot green within seconds, single-pane default works on a cold start.

- [ ] **Step 6: Sanity-check the file sizes**

Run: `wc -l index.html js/*.js`
Expected: `index.html` meaningfully smaller than pre-refactor (~200 lines vs ~460); each JS module focused and under ~150 lines. This is informational, not gating.

- [ ] **Step 7: Tag and push**

```bash
git log --oneline -20          # sanity — all Phase 1 commits present
```

Leave the tag / push decision to the user. No automatic push.

---

## Self-review notes (applied inline)

- **Spec coverage**: every section in the spec maps to a task in the map above.
- **Placeholders**: none — all code steps include the code; all command steps include the command and expected output.
- **Type / name consistency**: `createPaneState`, `createPane`, `sendToPanes`, `activePanes`, `pingVaultHealth`, `fetchVaultContext`, `reindexVault`, `renderSources`, `parseSSEBuffer`, `extractSSEDelta`, `oneLinePreview`, `refreshPreview` — all used consistently across tasks.
- **Scope**: Phase 1 only. Persistence (Phase 2) and token meter (Phase 3) are not touched.
- **Ambiguities resolved**: Pane B defaults to the repo default prompt (not a copy of Pane A); Pane A's history is preserved when entering Compare; exit confirm only fires when Pane B has non-empty history; vault settings are shared; Apply & Reset is per-pane; New session clears both.
