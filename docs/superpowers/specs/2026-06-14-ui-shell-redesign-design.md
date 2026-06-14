# Prompt Studio — UI Shell Redesign — Design

**Date:** 2026-06-14
**Status:** Approved (brainstorm), pending implementation plan
**Component:** Prompt Studio (`~/DevSwarmProjects/Clista`)

## Context

The app has grown a crowded topbar (Single/Compare, registry-load select + Load, Registry, Threads,
Seal as decision, Export) on top of a left rail that already holds overlapping controls — Registry
and Export appear in **both** places. There is no landing screen: the app drops you straight into an
empty chat with no explanation of the deliberate → shape → notarize workflow the four phases built.

## Goal

Reorganize the UI into a single-page **app shell**: a persistent left **sidebar** for navigation +
workflow, a thin breadcrumb instead of the crowded topbar, and a new **Home** view that explains how
the app works (and becomes a hub once you have sessions/decisions). Per-view controls move into the
view that uses them, removing duplication.

## Decisions locked in brainstorming

- **Home view = explainer that becomes a hub (A+B).** Empty/first-run shows the full
  deliberate → shape → notarize explainer with a worked example per step and a "Start a session" CTA;
  once there are sessions/decisions, it tightens into a hub (Continue + Recent decisions).
- **Framing = deliberate → shape → notarize** as the spine, in Home copy and sidebar labels.
- **Navigation = single-page app shell.** A persistent sidebar swaps the main view in place (no page
  reload). Views: Home, Deliberate, Decisions, Registry.
- **Per-view controls.** Sandbox controls (prompt picker, models, mode toggle, registry-load, Suggest,
  Seal, Save/Export) live inside the **Deliberate** view. The global topbar collapses to a thin crumb.
- **Decisions & Registry are embedded as iframes** of the existing `/threads` and `/registry` widgets
  (reuse working code verbatim; isolate their full-page styles; standalone routes keep working).
- **Model-agnostic copy.** The explainer says "your model"/"your chosen model" (local or frontier),
  never names a specific model. The footer shows the live active model + vault status.

## Information architecture

**Sidebar (persistent left):**
- Header: ▣ Prompt Studio
- **WORKFLOW:** ⌂ Home · Deliberate · Decisions
- **LIBRARY:** Registry · Sessions
- Global action: **+ New session**
- Footer: vault status + active model (live)

Note: the Home explainer teaches the **three** steps (Deliberate → Shape → Notarize), but the sidebar
has only the two *destination views* (Deliberate, Decisions). **"Shape" is not a nav item** — it is
the ✨ Suggest + Seal action that happens *inside* the Deliberate view, on the current conversation.
"Decisions" is where notarized records land.

**Views (in `<main id="view">`):**
1. **Home** *(new, native)* — explainer (empty) / hub (populated). Empty state: title + tagline
   ("Turn a conversation into a decision you can trust — fully local"), the three steps each with a
   one-line description + an italic worked example (the "support beta" decision carried through),
   "Start a session →" CTA, "Local & frontier models supported" note. Populated state: compact
   3-step strip, **+ New session**, **Continue** (resumable sessions), **Recent decisions** (recent
   sealed records, link to Decisions). The empty vs populated choice is driven by whether any saved
   sessions or sealed threads exist.
2. **Deliberate** *(native; the current sandbox restructured)* — Active Prompt picker + badges, Models
   checklist, Single/Compare toggle, registry-load (select + Load), chat panes, directive input,
   vault toggle, **✨ Suggest**, **Seal as decision**, **Save session**, **Export .md**.
3. **Decisions** *(iframe `/threads`)* — the Phase-1 Threads widget.
4. **Registry** *(iframe `/registry`)* — the existing Registry widget.

## Relocation map (every current control)

| Today | New home |
| --- | --- |
| Topbar: Single/Compare toggle (`#mode-toggle`) | Deliberate view header |
| Topbar: registry-load select + Load (`#registry-prompt-select`, `#registry-load-btn`) | Deliberate view (by Active Prompt) |
| Topbar: Registry link (`a[href="/registry"]`) | Sidebar → Registry nav (dedupe) |
| Topbar: Threads link (`a[href="/threads"]`) | Sidebar → Decisions nav |
| Topbar: Seal as decision (`#seal-open-btn`) | Deliberate view (contextual) |
| Topbar: Export .md (`#export-btn`, duplicate) | Removed (one copy stays in Deliberate) |
| Rail: logo + "Prompt Studio" + eval tag | Sidebar header |
| Rail: Active Prompt picker + badges (`#prompt-picker`, `#prompt-badges`) | Deliberate view |
| Rail: Models checklist (`#model-checklist`) | Deliberate view |
| Rail: + New session (`#new-session`) | Sidebar global action |
| Rail: Sessions list + save slot (`#sessions-list`, `#sessions-save-slot`) | Sidebar (Sessions) + Home "Continue" |
| Rail: Save / Export (`#save-session-btn`, `#export-btn`) | Deliberate view actions |
| Rail: Vault card (`#vault-card`) | Sidebar footer (status) |

## Architecture

- **`sandbox/index.html` becomes the shell:** a persistent `<aside class="sidebar">` + a
  `<main id="view">` holding the view sections. Home and Deliberate are native `<section>`s; Decisions
  and Registry are `<iframe>`s (lazily set their `src` on first show to avoid loading widgets you
  never open).
- **`sandbox/js/view.js` (new) — tiny client-side router.** Pure `resolveView(raw)` maps a requested
  view id / URL hash to one of the known views, defaulting to `home` for unknown input. An impure
  `showView(id)` toggles section visibility, sets the active sidebar item, updates `location.hash`,
  and lazily sets the iframe `src` for Decisions/Registry on first show. Default view on load = the
  view in `location.hash`, else `home`.
- **No backend changes.** `server.py` already serves `/`, `/threads`, `/registry`, and `/js/*`.
- **Existing sandbox JS (`app.js`, etc.) is preserved.** The Deliberate view keeps the same element
  ids the sandbox JS targets; the redesign moves markup between containers, it does not rewrite the
  sandbox logic. The seal modal, Suggest, vault toggle, panes, sessions all keep working.

## Error handling

- Unknown/empty view id or hash → fall back to **Home** (`resolveView` returns `home`).
- An iframe view whose backend is down shows the widget's own existing error state (e.g. the Threads
  widget's "ThreadHub sidecar not running"); the shell does not need to handle it.
- Home empty/populated detection degrades to the empty (explainer) state if session/decision lookups
  fail — the explainer is always a safe default.

## Testing

- **`node --test` for `sandbox/js/view.js`:** `resolveView` returns the right id for each known view,
  returns `home` for unknown/empty/garbage input, and is case-tolerant for the hash form.
- **Manual browser acceptance:** sidebar switches Home/Deliberate/Decisions/Registry with no reload;
  the active nav item highlights; Home shows the explainer when empty and the hub when sessions/
  decisions exist; Deliberate retains all sandbox behavior (prompt/model selection, chat, ✨ Suggest,
  Seal → thread appears in Decisions, vault toggle, Save/Export); Decisions/Registry iframes load and
  function; the topbar is reduced to the breadcrumb; Registry/Export are no longer duplicated.

## Non-goals (deferred)

- No native in-DOM re-mount of the Threads/Registry widgets (iframe is the chosen embedding); that
  cleanup is a separate future step.
- No change to the sandbox's chat/model/seal logic — this is layout/navigation only.
- No backend/server changes.
- No new visual theme/redesign of the existing components beyond relocation and the new Home view;
  reuse the current design tokens (paper/ink palette, Inter Tight / Newsreader / JetBrains Mono).
- No mobile/responsive redesign beyond not breaking the existing layout.

## Open items for the implementation plan

- Confirm the exact set of element ids the sandbox JS (`app.js`, `send.js`, sessions, vault, seal,
  registry-load) queries, so the Deliberate-view restructure preserves all of them (a grep inventory
  before moving markup).
- Decide the Home "populated vs empty" data source: saved sessions (existing sessions store /
  `/api/sessions`) and sealed decisions (`/api/threads`), with the empty explainer as the safe
  fallback if either lookup fails or returns none.
