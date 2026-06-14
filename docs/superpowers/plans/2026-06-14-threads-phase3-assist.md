# Threads Add-on — Phase 3 (Assisted Extraction — "✨ Suggest") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "✨ Suggest from conversation" button to the seal modal that drafts the seal's content fields (question, decision, evidence, objections) from the active pane's conversation, fills the editable form, and flags them as drafted.

**Architecture:** Fully client-side. A new ES module `sandbox/js/seal-extract.js` holds the pure extraction prompt + parser (unit-tested with `node --test`), a pure pane-context helper, and the impure `runExtraction` model call (reusing the existing `stream.js` SSE parser for frontier providers, a direct non-streaming call for the local `lmstudio` provider). `app.js` exposes `window.sealActivePane()`; the seal modal's inline script wires the button via `window.SealExtract`.

**Tech Stack:** Vanilla JS ES modules, `node --test` + `node:assert`, existing `sandbox/js/stream.js` parser. No backend changes.

**Spec:** `docs/superpowers/specs/2026-06-14-threads-phase3-assist-design.md`

---

## Verified facts (from the codebase)

- JS tests: `import { test } from 'node:test'; import assert from 'node:assert';` importing from the module under test; run with `node --test sandbox/js/*.test.js`.
- Pane state in `app.js`: `activePaneMap` = `{ modelKey: { state, pane, meter } }`; conversation is `state.messages` (`[{role, content}]`); model config is `ALL_MODELS[modelKey]` (`{id, endpoint, provider, …}`). Local models have `provider: "lmstudio"` and `endpoint: "<LM_STUDIO_URL>/v1/chat/completions"`.
- `sandbox/js/stream.js` exports `parseSSEBuffer(buffer) → {events, remainder}` and `extractSSEDelta(event) → {reasoning, content}`.
- The Phase 2 seal modal + inline IIFE live in `sandbox/index.html` (modal header is `<h3 …>Seal as decision</h3>`; the IIFE defines `$`, `esc`, `addEvidence`, `addObjection`, `openModal`, `submit`).

## File Structure

- **Create** `sandbox/js/seal-extract.js` — `EXTRACTION_PROMPT`, `buildExtractionMessages`, `parseExtraction`, `paneContext` (pure); `runExtraction` (impure, imports `stream.js`); attaches `window.SealExtract`.
- **Create** `sandbox/js/seal-extract.test.js` — `node --test` for the pure functions.
- **Modify** `sandbox/js/app.js` — `import { paneContext }`, set `window.sealActivePane`.
- **Modify** `sandbox/index.html` — Suggest button in the modal header + handler in the IIFE.

---

## Task 1: `seal-extract.js` — prompt + message builder

**Files:** Create `sandbox/js/seal-extract.js`; Create `sandbox/js/seal-extract.test.js`.

- [ ] **Step 1: Write the failing test**

Create `sandbox/js/seal-extract.test.js`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import { EXTRACTION_PROMPT, buildExtractionMessages } from './seal-extract.js';

test('EXTRACTION_PROMPT mentions the four output keys', () => {
  for (const k of ['question', 'decision', 'evidence', 'objections']) {
    assert.ok(EXTRACTION_PROMPT.includes(k), `prompt missing ${k}`);
  }
});

test('buildExtractionMessages: system prompt + rendered transcript', () => {
  const msgs = buildExtractionMessages([
    { role: 'user', content: 'Should we ship?' },
    { role: 'assistant', content: 'Ship to redacted only.' },
  ]);
  assert.strictEqual(msgs.length, 2);
  assert.strictEqual(msgs[0].role, 'system');
  assert.strictEqual(msgs[0].content, EXTRACTION_PROMPT);
  assert.strictEqual(msgs[1].role, 'user');
  assert.ok(msgs[1].content.includes('Should we ship?'));
  assert.ok(msgs[1].content.includes('Ship to redacted only.'));
});

test('buildExtractionMessages: tolerates non-array / non-string content', () => {
  const msgs = buildExtractionMessages(null);
  assert.strictEqual(msgs.length, 2);
  assert.strictEqual(msgs[1].role, 'user');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && node --test sandbox/js/seal-extract.test.js`
Expected: FAIL — cannot find module `./seal-extract.js`.

- [ ] **Step 3: Write minimal implementation**

Create `sandbox/js/seal-extract.js`:

```javascript
export const EXTRACTION_PROMPT = `You read a decision-making conversation and extract its accountable structure.
Output ONLY a JSON object (no prose, no markdown fences) with these keys:
- "question": the decision question (string)
- "decision": the decision reached — the yes/no plus its statement (string)
- "evidence": array of {"source": string, "finding": string}
- "objections": array of {"text": string} — concerns raised that were NOT resolved
If something is absent from the conversation, use an empty string or empty array. Do not invent facts.`;

export function buildExtractionMessages(transcript) {
  const rendered = (Array.isArray(transcript) ? transcript : [])
    .map((m) => `${m && m.role ? m.role : 'user'}: ${m && typeof m.content === 'string' ? m.content : ''}`)
    .join('\n\n');
  return [
    { role: 'system', content: EXTRACTION_PROMPT },
    { role: 'user', content: `Conversation:\n\n${rendered}\n\nReturn the JSON object.` },
  ];
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && node --test sandbox/js/seal-extract.test.js`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add sandbox/js/seal-extract.js sandbox/js/seal-extract.test.js
git commit -m "feat(assist): extraction prompt and message builder"
```

---

## Task 2: `seal-extract.js` — `parseExtraction`

**Files:** Modify `sandbox/js/seal-extract.js`; Modify `sandbox/js/seal-extract.test.js`.

- [ ] **Step 1: Write the failing test**

Add to `sandbox/js/seal-extract.test.js` (extend the import line to include `parseExtraction`):

```javascript
import { EXTRACTION_PROMPT, buildExtractionMessages, parseExtraction } from './seal-extract.js';

test('parseExtraction: clean JSON', () => {
  const out = parseExtraction('{"question":"Q","decision":"D","evidence":[{"source":"s","finding":"f"}],"objections":[{"text":"o"}]}');
  assert.deepStrictEqual(out, {
    question: 'Q', decision: 'D',
    evidence: [{ source: 's', finding: 'f' }],
    objections: [{ text: 'o' }],
  });
});

test('parseExtraction: JSON inside a markdown fence', () => {
  const out = parseExtraction('```json\n{"question":"Q","decision":"D","evidence":[],"objections":[]}\n```');
  assert.strictEqual(out.question, 'Q');
  assert.deepStrictEqual(out.evidence, []);
});

test('parseExtraction: JSON after a reasoning preamble', () => {
  const out = parseExtraction('Let me think... the question is clear.\n\n{"question":"Q","decision":"D","evidence":[],"objections":[]}');
  assert.strictEqual(out.decision, 'D');
});

test('parseExtraction: missing keys default to empty', () => {
  const out = parseExtraction('{"question":"Q"}');
  assert.strictEqual(out.decision, '');
  assert.deepStrictEqual(out.evidence, []);
  assert.deepStrictEqual(out.objections, []);
});

test('parseExtraction: drops malformed evidence/objection items', () => {
  const out = parseExtraction('{"evidence":["bad",{"source":"s","finding":"f"},{"source":"","finding":""}],"objections":["plain", {"text":"t"}, {"text":""}]}');
  assert.deepStrictEqual(out.evidence, [{ source: 's', finding: 'f' }]);
  assert.deepStrictEqual(out.objections, [{ text: 'plain' }, { text: 't' }]);
});

test('parseExtraction: garbage throws', () => {
  assert.throws(() => parseExtraction('no json here'));
  assert.throws(() => parseExtraction(''));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && node --test sandbox/js/seal-extract.test.js`
Expected: FAIL — `parseExtraction` is not exported.

- [ ] **Step 3: Write minimal implementation**

Add to `sandbox/js/seal-extract.js`:

```javascript
function _str(v) {
  return typeof v === 'string' ? v.trim() : '';
}

function _coerce(obj) {
  const evidence = Array.isArray(obj.evidence)
    ? obj.evidence
        .filter((e) => e && typeof e === 'object')
        .map((e) => ({ source: _str(e.source), finding: _str(e.finding) }))
        .filter((e) => e.source || e.finding)
    : [];
  const objections = Array.isArray(obj.objections)
    ? obj.objections
        .map((o) => (o && typeof o === 'object' ? _str(o.text) : _str(o)))
        .filter(Boolean)
        .map((text) => ({ text }))
    : [];
  return { question: _str(obj.question), decision: _str(obj.decision), evidence, objections };
}

export function parseExtraction(text) {
  if (typeof text !== 'string') throw new Error('no response text');
  const start = text.indexOf('{');
  if (start === -1) throw new Error('no JSON object in response');
  let depth = 0, inStr = false, esc = false, end = -1;
  for (let i = start; i < text.length; i++) {
    const c = text[i];
    if (inStr) {
      if (esc) esc = false;
      else if (c === '\\') esc = true;
      else if (c === '"') inStr = false;
    } else if (c === '"') {
      inStr = true;
    } else if (c === '{') {
      depth++;
    } else if (c === '}') {
      depth--;
      if (depth === 0) { end = i; break; }
    }
  }
  if (end === -1) throw new Error('unbalanced JSON in response');
  let obj;
  try {
    obj = JSON.parse(text.slice(start, end + 1));
  } catch (e) {
    throw new Error('could not parse JSON: ' + e.message);
  }
  if (!obj || typeof obj !== 'object') throw new Error('parsed value is not an object');
  return _coerce(obj);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && node --test sandbox/js/seal-extract.test.js`
Expected: PASS (9 tests total).

- [ ] **Step 5: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add sandbox/js/seal-extract.js sandbox/js/seal-extract.test.js
git commit -m "feat(assist): robust parseExtraction (fences, reasoning, defaults)"
```

---

## Task 3: `seal-extract.js` — `paneContext`, `runExtraction`, `window.SealExtract`

**Files:** Modify `sandbox/js/seal-extract.js`; Modify `sandbox/js/seal-extract.test.js`.

- [ ] **Step 1: Write the failing test**

Add to `sandbox/js/seal-extract.test.js` (extend import to include `paneContext, runExtraction`):

```javascript
import { EXTRACTION_PROMPT, buildExtractionMessages, parseExtraction, paneContext, runExtraction } from './seal-extract.js';

test('paneContext: empty map → null model, empty messages', () => {
  assert.deepStrictEqual(paneContext({}, {}), { model: null, messages: [] });
});

test('paneContext: first pane model + messages copy', () => {
  const map = { gemma: { state: { messages: [{ role: 'user', content: 'hi' }] } } };
  const models = { gemma: { id: 'gemma', provider: 'lmstudio' } };
  const ctx = paneContext(map, models);
  assert.strictEqual(ctx.model.id, 'gemma');
  assert.deepStrictEqual(ctx.messages, [{ role: 'user', content: 'hi' }]);
  // must be a copy, not the live array
  assert.notStrictEqual(ctx.messages, map.gemma.state.messages);
});

test('runExtraction: lmstudio non-streaming returns content', async () => {
  const fakeFetch = async (url, opts) => {
    const body = JSON.parse(opts.body);
    assert.strictEqual(body.stream, false);
    return { ok: true, json: async () => ({ choices: [{ message: { content: '{"question":"Q"}' } }] }) };
  };
  const out = await runExtraction({ id: 'g', provider: 'lmstudio', endpoint: 'http://x/v1/chat/completions' },
    [{ role: 'user', content: 'hi' }], fakeFetch);
  assert.strictEqual(out, '{"question":"Q"}');
});

test('runExtraction: lmstudio falls back to reasoning when content empty', async () => {
  const fakeFetch = async () => ({ ok: true, json: async () => ({ choices: [{ message: { content: '', reasoning: 'R' } }] }) });
  const out = await runExtraction({ id: 'g', provider: 'lmstudio', endpoint: 'http://x' }, [], fakeFetch);
  assert.strictEqual(out, 'R');
});

test('runExtraction: non-ok response throws', async () => {
  const fakeFetch = async () => ({ ok: false, status: 500 });
  await assert.rejects(() => runExtraction({ provider: 'lmstudio', endpoint: 'http://x' }, [], fakeFetch));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && node --test sandbox/js/seal-extract.test.js`
Expected: FAIL — `paneContext` / `runExtraction` not exported.

- [ ] **Step 3: Write minimal implementation**

Add to the TOP of `sandbox/js/seal-extract.js` (with the other imports — there are none yet, so add this as the first line):

```javascript
import { parseSSEBuffer, extractSSEDelta } from './stream.js';
```

Add these exports to `sandbox/js/seal-extract.js`:

```javascript
export function paneContext(activePaneMap, models) {
  const entries = Object.entries(activePaneMap || {});
  if (!entries.length) return { model: null, messages: [] };
  const [modelKey, entry] = entries[0];
  const messages = entry && entry.state && Array.isArray(entry.state.messages)
    ? [...entry.state.messages]
    : [];
  return { model: (models || {})[modelKey] || null, messages };
}

export async function runExtraction(model, messages, fetchImpl) {
  const doFetch = fetchImpl || fetch;
  if (model && model.provider === 'lmstudio') {
    const res = await doFetch(model.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: model.id, messages, stream: false }),
    });
    if (!res.ok) throw new Error('model error ' + res.status);
    const data = await res.json();
    const msg = (data.choices && data.choices[0] && data.choices[0].message) || {};
    return msg.content && msg.content.trim() ? msg.content : (msg.reasoning || '');
  }
  const res = await doFetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider: model ? model.provider : 'anthropic', model: model ? model.id : '', messages }),
  });
  if (!res.ok || !res.body) throw new Error('model error ' + (res.status || 'no body'));
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '', out = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { events, remainder } = parseSSEBuffer(buffer);
    buffer = remainder;
    for (const ev of events) {
      const { content } = extractSSEDelta(ev);
      if (content) out += content;
    }
  }
  return out;
}

if (typeof window !== 'undefined') {
  window.SealExtract = { EXTRACTION_PROMPT, buildExtractionMessages, parseExtraction, paneContext, runExtraction };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && node --test sandbox/js/seal-extract.test.js`
Expected: PASS (14 tests total).

- [ ] **Step 5: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add sandbox/js/seal-extract.js sandbox/js/seal-extract.test.js
git commit -m "feat(assist): paneContext + runExtraction (lmstudio + frontier SSE) + window bridge"
```

---

## Task 4: `app.js` — `window.sealActivePane`

**Files:** Modify `sandbox/js/app.js`.

- [ ] **Step 1: Add the import**

In `sandbox/js/app.js`, add to the existing import block near the top (alongside the other `./*.js` imports):

```javascript
import { paneContext } from './seal-extract.js';
```

- [ ] **Step 2: Wire the global**

`app.js` references `activePaneMap` (module-scoped) and imports `ALL_MODELS` from `./config.js` (verify it is imported; it is used in app.js). Near the other `window.*` assignments in `app.js` (there is a `window.addEventListener("message", …)` block ~line 249 — add this right after the top-level setup, e.g. after the `activePaneMap` declaration or at the end of module init), add:

```javascript
window.sealActivePane = () => paneContext(activePaneMap, ALL_MODELS);
```

Place it at module top level (not inside a function) so it is set on load. If `ALL_MODELS` is not already imported in `app.js`, add it to the `./config.js` import.

- [ ] **Step 3: Verify the module still loads**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && node --check sandbox/js/app.js && node --test sandbox/js/*.test.js`
Expected: `node --check` passes (syntax OK); all JS tests pass (importing `seal-extract.js` works; `app.js` itself is not unit-tested because it bootstraps the DOM).

- [ ] **Step 4: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add sandbox/js/app.js
git commit -m "feat(assist): expose window.sealActivePane bridge from app"
```

---

## Task 5: Suggest button + handler in the seal modal

**Files:** Modify `sandbox/index.html`.

- [ ] **Step 1: Add the button to the modal header**

In `sandbox/index.html`, find the seal modal header:

```html
    <h3 style="margin:0 0 12px">Seal as decision</h3>
```

Replace it with a header row containing the Suggest button:

```html
    <div style="display:flex;justify-content:space-between;align-items:center;margin:0 0 12px">
      <h3 style="margin:0">Seal as decision</h3>
      <button type="button" class="ghost-btn" id="seal-suggest-btn" style="font-size:11px">✨ Suggest from conversation</button>
    </div>
```

- [ ] **Step 2: Add the handler in the seal IIFE**

In the seal `<script>` IIFE in `sandbox/index.html`, add this function before the final event-listener wiring block (the lines that call `$("seal-open-btn").addEventListener(...)`), and reuse the existing `addEvidence` / `addObjection` / `$` / `esc` helpers:

```javascript
  async function suggest() {
    const SE = window.SealExtract;
    const ctx = window.sealActivePane ? window.sealActivePane() : { model: null, messages: [] };
    if (!SE || !window.sealActivePane) {
      $("seal-msg").style.color = "#a83830";
      $("seal-msg").textContent = "Suggest unavailable.";
      return;
    }
    if (!ctx.messages || !ctx.messages.length) {
      $("seal-msg").style.color = "#a83830";
      $("seal-msg").textContent = "Start a conversation first — nothing to read.";
      return;
    }
    const btn = $("seal-suggest-btn");
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = "⋯ Reading conversation…";
    $("seal-msg").style.color = "#5c636b";
    $("seal-msg").textContent = "";
    try {
      const text = await SE.runExtraction(ctx.model, SE.buildExtractionMessages(ctx.messages));
      const draft = SE.parseExtraction(text);
      $("seal-question").value = draft.question;
      $("seal-decision").value = draft.decision;
      $("seal-evidence").innerHTML = "";
      if (draft.evidence.length) {
        draft.evidence.forEach((e) => {
          addEvidence();
          const row = $("seal-evidence").lastElementChild;
          row.querySelector(".seal-ev-source").value = e.source;
          row.querySelector(".seal-ev-finding").value = e.finding;
        });
      } else {
        addEvidence();
      }
      $("seal-objections").innerHTML = "";
      draft.objections.forEach((o) => {
        addObjection();
        $("seal-objections").lastElementChild.querySelector(".seal-obj-text").value = o.text;
      });
      $("seal-msg").style.color = "#a87a00";
      $("seal-msg").textContent = "✨ Drafted from conversation — review & edit before sealing.";
    } catch (e) {
      $("seal-msg").style.color = "#a83830";
      $("seal-msg").textContent =
        /model error|fetch|Failed/.test(String(e && e.message))
          ? "Model unreachable — is it running?"
          : "Couldn't draft from this conversation. Fill manually or try again.";
    } finally {
      btn.disabled = false;
      btn.textContent = label;
    }
  }
```

Then add its listener in the wiring block alongside the others:

```javascript
  $("seal-suggest-btn").addEventListener("click", suggest);
```

- [ ] **Step 3: Confirm no test regressions and ids present**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && python3 -m pytest tests/ -q` (expect unchanged pass count) and `node --test sandbox/js/*.test.js` (all pass).
Run: `grep -c 'seal-suggest-btn\|SealExtract\|sealActivePane' sandbox/index.html` (expect ≥2).

- [ ] **Step 4: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add sandbox/index.html
git commit -m "feat(assist): Suggest button + draft-from-conversation handler in seal modal"
```

---

## Task 6: End-to-end manual acceptance

**Files:** none (verification only).

- [ ] **Step 1: Start the stack**

```bash
cd ~/threadhub && node bin/cli.js serve --port 8110 &
cd /Users/troylatimer/DevSwarmProjects/Clista && python3 server.py &
```
Ensure a local model is reachable (LM Studio at `LM_STUDIO_URL`, or set `LM_STUDIO_URL` to a running MLX/LM Studio OpenAI-compatible server).

- [ ] **Step 2: Have a short decision conversation**

Open `http://localhost:8000/`, pick a local model, and chat through a small decision (e.g., "Should we ship the support beta? … yes, redacted tickets only, because 82% are FAQ-shaped, though privacy risk remains").

- [ ] **Step 3: Suggest**

Click "Seal as decision" → "✨ Suggest from conversation". Confirm: the button shows "⋯ Reading conversation…", then Question/Decision/Evidence/Objection fields populate, and the amber "✨ Drafted from conversation — review & edit before sealing" note appears.

- [ ] **Step 4: Edit + seal**

Tweak a field, click "Seal →". Confirm the green "✓ Sealed · <slug> · <hash>…" result, then open the Threads tab and confirm the new thread with a ✓ chain-valid badge.

- [ ] **Step 5: Error states**

With the form open and no conversation (fresh session), click Suggest → confirm "Start a conversation first". Stop the local model and click Suggest on a conversation → confirm "Model unreachable".

- [ ] **Step 6: Full JS + Python suites green**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && node --test sandbox/js/*.test.js && python3 -m pytest tests/ -q`
Expected: all pass.

---

## Self-Review

**Spec coverage:**
- "✨ Suggest" button in modal, fills content fields → Task 5. ✓
- Pure extraction module (prompt, builder, parser) with `node --test` → Tasks 1–2. ✓
- Active-pane model + transcript bridge (`paneContext` / `window.sealActivePane`) → Tasks 3–4. ✓
- `runExtraction`: lmstudio non-streaming + frontier SSE-accumulate (reusing `stream.js`) → Task 3. ✓
- Four UI states (idle/working/filled-with-note/error) → Task 5. ✓
- Fills content only (question/decision/evidence/objections); title + decidedBy untouched → Task 5 (handler sets only those fields). ✓
- Error handling: empty transcript, model unreachable, parse failure (no partial fill on throw) → Task 5. ✓
- Testing: pure-function `node --test` (Tasks 1–3) + manual acceptance (Task 6). ✓
- Non-goals respected: no streaming-into-fields, no title/decidedBy extraction, no auto-seal, active-pane only, no backend route. ✓

**Placeholder scan:** No TBD/TODO; every code step is complete. `<slug>`/`<hash>` in Task 6 are runtime values in a manual step.

**Type/name consistency:** `buildExtractionMessages`, `parseExtraction`, `paneContext`, `runExtraction`, `EXTRACTION_PROMPT` exported from `seal-extract.js` and consumed identically in `app.js` (`paneContext`) and the modal IIFE (`window.SealExtract.*`, `window.sealActivePane`). `parseExtraction` returns `{question, decision, evidence:[{source,finding}], objections:[{text}]}` — matched by the handler's field-fill and by the Phase 2 seal payload shape.
