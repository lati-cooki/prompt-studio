# Prompt Sandbox — Phase 2: Persistence Cluster (Sessions + Export)

**Date:** 2026-04-18
**Status:** Approved design, awaiting implementation plan.
**Parent project:** `prompt-sandbox`
**Prior spec:** `docs/superpowers/specs/2026-04-18-prompt-sandbox-ab-compare.md` (Phase 1).

## Context

Phase 1 shipped A/B compare + UI refresh. State still lives in memory only — a reload wipes the prompt edits and the conversation. Users have no way to hold onto a prompt variant they liked or return to a notable conversation. Phase 2 adds **explicit save** of current state (prompt + optional messages) to `localStorage`, a **unified "Sessions" list** to reload or delete those saves, and a **Markdown export** of the current active pane(s).

Phase 2 also folds in two bugs flagged by the Phase 1 final review that will immediately corrupt exported conversations if left alone, plus two structural cleanups that make room for Phase 3's context meter.

## Goals

- **Explicit save**: user-initiated save of the current state; no auto-save.
- **Unified list**: a saved entry can be just a prompt (functionally a "preset") or a prompt + messages (functionally a "session snapshot") — one list, one schema, one load UI.
- **A/B-aware**: saving in compare mode captures both panes; loading a two-pane entry restores compare mode.
- **Markdown export**: human-readable dump of the current active pane(s), no round-trip requirement.
- Continue the "one HTML file, no build, no npm, no framework" constraint from Phase 1.

## Non-goals

- No cloud sync, no multi-device.
- No search across saved entries. Scrolling list only.
- No tags or folders.
- No JSON export. Markdown only.
- No auto-save of any kind.
- No undo for delete.

## Design

### 1. Data model + storage

Single localStorage key: `promptSandbox.sessions`. Value is a JSON-serialized array, newest-first:

```js
{
  id:         "sess-<unix-ms>-<rand6>",   // stable key, never reused
  name:       "<user-edited, or auto>",   // auto-name: first 40 chars of the first user message (trimmed at a word boundary if possible), else "Untitled"
  createdAt:  "<ISO timestamp>",
  updatedAt:  "<ISO timestamp>",
  panes: [
    { systemPrompt: "<string>", messages: [<role objects, starting with system>] },
    // second element only when saved from compare mode
  ],
  vaultConfig: { enabled: <bool>, topK: <int 1..20> }
}
```

- **Pane schema parallels Phase 1's state**: `panes[i].messages` mirrors `createPaneState(...).messages` (includes the system message at index 0).
- **"Preset-like" entry**: `panes[i].messages.length === 1` (just the system message).
- **"Session-snapshot" entry**: `panes[i].messages.length > 1`.
- **vaultConfig** captures the controls at save time. Vault retrieval *results* are NEVER persisted — they're ephemeral by Phase 1 design.
- **Storage cap**: soft cap of 100 entries. On the 101st save, silently trim the oldest entry (FIFO by `createdAt`). No starring / no prompt — these are all user-saved by definition, and a rolling-100 window is predictable. Hard cap comes from the localStorage 5MB origin limit, well above 100 entries of reasonable size.

### 2. UI surface

Controls strip gains **one new dropdown**:

```
Compare | New session | Sessions ▾ | ● | Use vault | top-K | Reindex | status
```

Clicking `Sessions ▾` opens a floating panel anchored under the button. The panel contains:

```
┌─────────────────────────────────────┐
│ [ Save current… ]                   │  ← primary action; prompts for a name
├─────────────────────────────────────┤
│ ● Rational Advisor tests    • 4d    │  ← entry rows (icon = has convo or not)
│   A/B: Strategist vs Pirate ●● 2d   │  ← A/B entries show two dots
│ ○ Daily journal template    • 6d    │  ← ○ = prompt only
│ … (scrollable list)                 │
├─────────────────────────────────────┤
│ [ Export current as Markdown ]      │  ← separate from list; always enabled
└─────────────────────────────────────┘
```

- Entry rows: one line with name, pane-count dots (● = has convo, ○ = prompt only; two dots for A/B), relative age. Click to load. Hover reveals a trailing ✕ to delete (with native `confirm()`).
- Save button at top: on click, the button morphs into an inline row with a text input (prefilled with the auto-name), a Save button, and a Cancel button. Enter confirms, Esc cancels. After Save or Cancel, the row reverts to the single button.
- Export button at bottom is always enabled regardless of save state — export captures what's on screen, doesn't require saving.
- Panel closes on outside click, Esc, or after a successful Save/Load/Delete action.

### 3. Save / Load / Delete semantics

**Save**:
1. Gather current state: systemPrompt + messages for every active pane, current vault toggle + topK.
2. Pop the dangling user message from each pane if present (belt-and-suspenders; I-1's main fix is in send.js, but save should also guard).
3. Compute auto-name: first 40 chars of the first user message (trimmed at a word boundary if possible); fallback `"Untitled <short-date-time>"` if no user messages yet.
4. Open inline name-entry prefilled; on confirm, prepend a new entry to the array; write back to localStorage.
5. If array exceeds 100 entries, trim the oldest (no confirm; these are user-saved, not auto-save garbage).

**Load**:
- **Single-pane entry → single-pane mode**: if currently in compare mode with Pane B non-empty, use the existing exit-compare confirm copy adapted: "Loading this session will exit compare mode and discard Pane B's conversation. Continue?" On yes, exit compare (discards B); replace Pane A state with entry.panes[0]; apply vaultConfig; refresh pane A's preview; clear/re-render log from messages.
- **Two-pane entry → compare mode**: if currently in compare mode, existing Pane B will be replaced; if not in compare mode, enter compare first. Replace both panes' states from `entry.panes[0]` and `entry.panes[1]`. Apply vaultConfig. Refresh both previews and logs.
- Existing unsaved state is **discarded** on load. Loads do not double as copies — there's always only one live pane per slot.

**Delete**: native `confirm("Delete '<name>'? This cannot be undone.")`. On yes, splice entry from array and write back.

**Note on load**: replacing a pane's state on load requires a new `pane.renderFromMessages(messages)` helper — the pane component today exposes `addBubble` / `addLogNote` / `clearLog`, but not a bulk re-render. Add this during the Pane-split refactor in Task 0.

### 4. Export

- **Trigger**: `[ Export current as Markdown ]` button inside the Sessions panel.
- **Captures**: current active pane(s) state exactly as-is, not the selected saved entry.
- **Output**: a Markdown file delivered via an anchor with `download="<slug>-<YYYY-MM-DD>.md"` + `href="data:text/markdown;charset=utf-8,<encoded>"` (no server round-trip).
- **Filename slug**: if a save operation has named this state, use the slugified name. Otherwise the auto-name slug (first user message) or `"prompt-sandbox"`.
- **Format**:

  ```markdown
  ---
  name: Rational Advisor tests
  exported: 2026-04-18T21:44:00Z
  vault: { enabled: true, topK: 3 }
  ---

  ## Pane A

  > [system prompt, block-quoted, preserving line breaks]

  **You:** what have I written about agentic harnesses?

  **Assistant:** …

  **You:** next follow-up

  **Assistant:** …

  ## Pane B
  ```

  (Two panes only in compare mode; single-pane exports omit the `## Pane A` heading — a single export just has frontmatter + the one system prompt blockquote + turns.)

### 5. Task 0 — pre-work (fold in before the feature work)

These items intersect Phase 2's scope directly and must land first:

- **Fix I-1** (stream failure leaves dangling user message): in `js/send.js`'s catch, pop the just-added user message from `state.messages` (call a new `state.popLastUser()` method). Add a regression test in `js/state.test.js`.
- **Fix I-2** (empty-stream `[DONE]` with zero deltas leaves "Thinking…"): after the stream-read loop and final flush, if `reasoningEl` is still null, clear the `pending` class and set `bubble.textContent = "(empty response)"`.
- **Split `js/ui.js` → `js/pane.js`**: move `createPane` + `oneLinePreview` into `js/pane.js`. `js/ui.js` keeps `renderSources` and becomes the home for new "panel" helpers (session list rendering, name-entry input helper, etc.).
- **Create `js/config.js`**: export `API_URL`, `MODEL`, `VAULT_URL`, `DEFAULT_SYSTEM_PROMPT`, and a new `STORAGE_KEY = "promptSandbox.sessions"`. Update `send.js`, `vault.js`, and the `index.html` entry to import from `config.js`.

### 6. New module: `js/sessions.js`

Own the persistence layer. No DOM. Pure localStorage I/O + array operations. Tests via `node:test` with a thin `localStorage` shim.

Exports:

```js
loadSessions()                              // → array of entries, newest-first
saveSession({ name, panes, vaultConfig })   // → the new entry (assigns id + timestamps + prepends)
renameSession(id, newName)                  // → updated entry
deleteSession(id)                           // → boolean
```

`ui.js` (or a new `js/session-panel.js` if cleaner) owns the panel DOM and event wiring. The panel module is consumed only from the `index.html` entry block.

### 7. Testing plan

- **`js/sessions.test.js`** (new): test loadSessions with empty storage, saveSession prepend + id/timestamp generation, renameSession, deleteSession round-trip; use a simple fake-storage object (implements getItem/setItem/removeItem) to isolate from the real `localStorage`.
- **`js/state.test.js`** (extend): add a test for the new `popLastUser()` method — covers I-1.
- **`js/stream.test.js`** and **`js/pane.js`**: untouched by Phase 2.
- **Manual browser verification**: save single-pane, save A/B, load single-pane, load A/B, load single into A/B with confirm, delete, export in both modes, storage quota edge (optional: seed 100 entries and confirm trim behavior).

## Acceptance criteria

- `Sessions ▾` dropdown visible in the controls strip; opens/closes on click; closes on outside-click / Esc.
- Save captures current state; loads restore it 1:1 (prompt + messages + vault toggle + topK); entries survive a page reload.
- A/B save captures both panes; loading a 2-pane entry enters compare mode.
- Loading a 1-pane entry in compare mode confirms before discarding Pane B.
- Delete removes from list and localStorage after confirm.
- Export produces a Markdown file via browser download with correctly slugified filename and proper frontmatter.
- I-1: MLX kill mid-send no longer leaves a dangling user message in state; a subsequent retry works.
- I-2: empty-stream `[DONE]` renders "(empty response)" instead of stuck "Thinking…".
- `js/ui.js` split landed; tests still pass; entry point unchanged visually.
- `js/config.js` holds the shared constants; other modules import from it.
- All Phase 1 acceptance behaviors still pass.

## Risks

- **localStorage JSON corruption**: a half-written or corrupted entry would fail `JSON.parse` and break the app on load. Mitigation: `loadSessions()` wraps parse in try/catch and returns `[]` on failure, logging a console warning. User loses old saves but can keep using the app.
- **Storage quota exceeded**: one session snapshot with a long conversation could approach 100KB+; 100 entries could theoretically exceed 5MB on huge convos. Mitigation: the 100-entry cap is a soft bound; if `setItem` throws `QuotaExceededError`, drop the oldest entry and retry once; surface a toast if still failing.
- **Breaking the A/B contract**: loading a 2-pane entry while compare is off must enter compare mode. Missing this would silently drop Pane B. Tested via the manual checklist.
- **Export of very long conversations** produces huge data-URL anchors; modern browsers handle multi-MB data URLs for `download` but may warn. Acceptable trade-off for not introducing a server round-trip.

## Follow-ups deferred to Phase 3

- Token / context-window meter (planned as Phase 3 standalone).
- Search over saved sessions.
- Tags or folders.
- JSON export.
- Auto-save (if the user changes their mind).
