# UI Iteration — Home "How it works" + dedicated Sessions view — Design

**Date:** 2026-06-14
**Status:** Approved (mockups), pending plan
**Component:** Prompt Studio (`~/DevSwarmProjects/Clista`)
**Builds on:** `docs/superpowers/specs/2026-06-14-ui-shell-redesign-design.md` (the app shell).

## Context

Feedback on the shell redesign: the Deliberate and Sessions screens feel too busy. The fix the user
chose: make **Home explain how the pieces fit together (revealed on demand)** so it teaches without a
wall of text, and give **Sessions its own page** so it stops living in the busy Deliberate rail.

## Goal

1. **Home — "How the pieces work together," reveal-on-demand.** Keep the ①②③ deliberate→shape→notarize
   loop as the spine. Add a calm, bordered section of expandable disclosures (`<details>`/`<summary>`)
   — one per component — collapsed by default, plus a one-line data-flow.
2. **Sessions — a dedicated view.** A new `sessions` view in the shell: a clean list of saved sessions
   in the main area (like Decisions/Registry), with **+ New session**. Clicking a session reopens it in
   Deliberate. The Sessions list moves out of the Deliberate rail.

## Decisions locked (mockups approved)

- Home detail rows: **Prompt sandbox**, **Registry**, **ClisTa Protocol**, **ThreadHub** — each a
  `<details>` with a one/two-sentence blurb tying it to the loop. The first (Prompt sandbox) may be
  open by default; the rest collapsed. Below them, a monospace data-flow line:
  `prompt → deliberate → ClisTa shapes → ThreadHub notarizes → Decisions`.
- The "How the pieces work together" block appears in the Home **empty/explainer** state (the first-run
  teaching surface); the hub state keeps its compact form (loop strip + recent decisions).
- Sessions view reuses the existing `renderSessionList(slot, entries, {onClick, onDelete})` helper and
  `sessionsStore.load()`. `onClick` → `loadEntry(entry)` + `showView('deliberate')`; `onDelete` →
  `sessionsStore.delete` + re-render. A **+ New session** button triggers the existing `#new-session`.

## Components / changes

- **`sandbox/js/view.js`** — add `'sessions'` to `VIEWS` (now five: home, deliberate, decisions,
  registry, sessions). Update `view.test.js`.
- **`sandbox/index.html`** —
  - Home `#home-empty`: add the "How the pieces work together" `<details>` block + data-flow line.
  - Add a `<section id="view-sessions">` in `main-wrap` (header "Sessions" + "+ New session" +
    `#sessions-view-list` container), styled like the home view (`max-width`, centered, scroll).
  - Change the sidebar `#nav-sessions` button to carry `data-view="sessions"` (so the generic nav
    handler routes it); keep its id.
- **`sandbox/js/app.js`** —
  - `showView`: handle `sessions` (toggle `#view-sessions` visible; it is non-deliberate, so rail +
    topbar stay hidden, like decisions/registry); call `renderSessions()` when `view === 'sessions'`.
  - Add `renderSessions()` — `await sessionsStore.load()`; `renderSessionList($sessionsViewList, …)`
    with `onClick`/`onDelete` as above.
  - Remove the old `$navSessions` click→`showView('deliberate')` wiring (the `data-view` handler now
    covers it). Wire the Sessions-view "+ New session" button to `document.getElementById('new-session')?.click()`.

## Data flow

`showView('sessions')` → show `#view-sessions`, hide other views + rail + topbar → `renderSessions()`
→ `sessionsStore.load()` → `renderSessionList(...)`. Row click → `loadEntry` + `showView('deliberate')`.

## Error handling

- `sessionsStore.load()` failure → render an empty "No saved sessions yet" state (catch → `[]`).
- Home `<details>` are static content — no failure path.
- Default view, hash routing, and the id-preservation contract are unchanged from the shell redesign
  (the new ids — `view-sessions`, `sessions-view-list` — are additive).

## Testing

- **`node --test` for `view.js`** — `VIEWS` now includes `sessions`; `resolveView('sessions')` →
  `'sessions'`; unknown still → `home`.
- **Manual browser acceptance** — Home shows the loop + collapsible "how the pieces fit" rows
  (expand/collapse works) + data-flow line; the Sessions nav opens the dedicated list (not Deliberate);
  clicking a saved session opens it in Deliberate; "+ New session" works; the Sessions list no longer
  appears only in the rail; all other views unaffected; no console errors; screenshots of Home +
  Sessions.

## Non-goals

- No collapsing/restructuring of the Deliberate rail itself (Sessions moving out is the only rail
  change); the deeper Deliberate declutter (collapsible rail, single-pane default) is deferred.
- No new backend; no change to sessions persistence.
