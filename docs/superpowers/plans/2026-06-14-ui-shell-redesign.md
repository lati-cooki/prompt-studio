# Prompt Studio — UI Shell Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the sandbox into a single-page app shell — a persistent left sidebar (Home / Deliberate / Decisions + Registry / Sessions), a new Home explainer-that-becomes-hub, a decluttered topbar, and per-view controls — reusing the existing iframe view-switch pattern.

**Architecture:** Generalize the existing `switchTab(eval|registry)` view-toggle into a `showView(id)` router driven by a sidebar; add a Decisions iframe alongside the existing Registry iframe; add a native Home view; relocate the sandbox's controls into a Deliberate view and retire the old rail/topbar duplication. Layout/navigation only — the sandbox's chat/model/seal logic is preserved by keeping every element id it depends on.

**Tech Stack:** Vanilla JS ES modules, `node --test`, existing design tokens (paper/ink palette, Inter Tight / Newsreader / JetBrains Mono). No backend changes.

**Spec:** `docs/superpowers/specs/2026-06-14-ui-shell-redesign-design.md`

---

## ⚠️ ID-PRESERVATION CONTRACT (read before any HTML task)

The sandbox JS queries these element ids. **Every one must still exist after each HTML change** —
the redesign MOVES markup between containers, it never deletes these ids. After any change to
`sandbox/index.html`, run this and confirm it prints `ALL PRESENT`:

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
missing=""; for id in composer composer-label export-btn input model-checklist new-session \
  pane-container prompt-badges prompt-picker rail-mode-tag registry-frame registry-load-btn \
  registry-panel-mount registry-prompt-select registry-status reindex save-session-btn \
  seg-compare seg-single send send-hint sessions-list sessions-save-slot stop-both stop-btn \
  tab-eval tab-registry top-k topbar-dots topbar-session topbar-subtitle use-vault \
  vault-card-sub vault-checkbox-visual vault-health vault-label-wrap vault-status; do
  grep -q "id=\"$id\"" sandbox/index.html || missing="$missing $id"; done
[ -z "$missing" ] && echo "ALL PRESENT" || echo "MISSING:$missing"
```

Also after each HTML/JS change, confirm the app still boots (no module error) and the suites pass:
```bash
node --test sandbox/js/*.test.js 2>&1 | grep -iE "pass |fail "
python3 -m pytest tests/ -q | tail -1
```

## Current structure (verified)

- `sandbox/index.html`: `<aside class="rail" id="sessions-rail">` (left rail) + `<div class="main-wrap">` (topbar + `#pane-container` + hidden `#registry-frame` iframe + `#composer`) + `#registry-panel-mount` + seal modal.
- `sandbox/js/app.js` `switchTab(tab)` toggles display of `#pane-container`, `#composer`, `#registry-panel-mount`, `#registry-frame` and the `seg-active` class on `#tab-eval`/`#tab-registry`. Reuse/generalize this.

## File Structure

- **Create** `sandbox/js/view.js` — pure `resolveView(raw)` + `homeState(sessionCount, decisionCount)`; `node --test`.
- **Modify** `sandbox/js/app.js` — generalize `switchTab` → `showView(id)` via `view.js`; wire sidebar nav; lazy iframe `src`; render Home.
- **Modify** `sandbox/index.html` — sidebar, Home view, Deliberate view wrapper, Decisions iframe, decluttered topbar; relocate controls (id-preserving).

---

## Task 1: `view.js` — pure router + home-state helpers

**Files:** Create `sandbox/js/view.js`; Create `sandbox/js/view.test.js`.

- [ ] **Step 1: Write the failing test**

Create `sandbox/js/view.test.js`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import { VIEWS, resolveView, homeState } from './view.js';

test('VIEWS lists the four views', () => {
  assert.deepStrictEqual(VIEWS, ['home', 'deliberate', 'decisions', 'registry']);
});

test('resolveView: known ids pass through', () => {
  for (const v of VIEWS) assert.strictEqual(resolveView(v), v);
});

test('resolveView: leading # and case tolerated', () => {
  assert.strictEqual(resolveView('#Decisions'), 'decisions');
  assert.strictEqual(resolveView('  REGISTRY '), 'registry');
});

test('resolveView: unknown/empty falls back to home', () => {
  assert.strictEqual(resolveView('nope'), 'home');
  assert.strictEqual(resolveView(''), 'home');
  assert.strictEqual(resolveView(null), 'home');
  assert.strictEqual(resolveView(undefined), 'home');
});

test('homeState: empty when no sessions and no decisions', () => {
  assert.strictEqual(homeState(0, 0), 'empty');
});

test('homeState: hub when any sessions or decisions exist', () => {
  assert.strictEqual(homeState(1, 0), 'hub');
  assert.strictEqual(homeState(0, 3), 'hub');
  assert.strictEqual(homeState(2, 5), 'hub');
});

test('homeState: tolerates non-number input as empty', () => {
  assert.strictEqual(homeState(undefined, null), 'empty');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && node --test sandbox/js/view.test.js`
Expected: cannot find module `./view.js`.

- [ ] **Step 3: Write minimal implementation**

Create `sandbox/js/view.js`:

```javascript
export const VIEWS = ['home', 'deliberate', 'decisions', 'registry'];

export function resolveView(raw) {
  const id = String(raw == null ? '' : raw).trim().replace(/^#/, '').toLowerCase();
  return VIEWS.includes(id) ? id : 'home';
}

export function homeState(sessionCount, decisionCount) {
  const s = Number(sessionCount) || 0;
  const d = Number(decisionCount) || 0;
  return s > 0 || d > 0 ? 'hub' : 'empty';
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && node --test sandbox/js/view.test.js`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add sandbox/js/view.js sandbox/js/view.test.js
git commit -m "feat(ui): pure view router + home-state helpers"
```

---

## Task 2: Decisions iframe + generalize the router in `app.js`

**Files:** Modify `sandbox/index.html` (add Decisions iframe); Modify `sandbox/js/app.js`.

- [ ] **Step 1: Add the Decisions iframe next to the Registry iframe**

In `sandbox/index.html`, find the existing registry iframe:

```html
  <iframe class="registry-frame" id="registry-frame" src="/registry/"></iframe>
```

Add a Decisions iframe immediately after it (no `src` yet — set lazily by the router):

```html
  <iframe class="registry-frame" id="registry-frame" src="/registry/"></iframe>
  <iframe class="registry-frame" id="decisions-frame" data-src="/threads/"></iframe>
```

(`.registry-frame` already has `display:none` + `flex:1`; reuse it for both.)

- [ ] **Step 2: Generalize `switchTab` into `showView` in `app.js`**

In `sandbox/js/app.js`, add to the imports at the top:

```javascript
import { resolveView } from './view.js';
```

Add a reference near the other `getElementById` refs (by `$registryFrame`):

```javascript
const $decisionsFrame = document.getElementById('decisions-frame');
```

Replace the existing `switchTab` function:

```javascript
function switchTab(tab) {
  const isRegistry = tab === "registry";
  $paneContainer.style.display      = isRegistry ? "none" : "";
  $composer.style.display           = isRegistry ? "none" : "";
  $registryPanelMount.style.display = isRegistry ? "none" : "";
  $registryFrame.style.display      = isRegistry ? "block" : "none";
  $tabEval.classList.toggle("seg-active",     !isRegistry);
  $tabRegistry.classList.toggle("seg-active",  isRegistry);
}
```

with a generalized router (note: `deliberate` is the former "eval" view):

```javascript
function showView(raw) {
  const view = resolveView(raw);
  const isDeliberate = view === 'deliberate';
  const isRegistry = view === 'registry';
  const isDecisions = view === 'decisions';
  // Deliberate (sandbox) surfaces
  $paneContainer.style.display      = isDeliberate ? "" : "none";
  $composer.style.display           = isDeliberate ? "" : "none";
  $registryPanelMount.style.display = isDeliberate ? "" : "none";
  // Embedded views (lazy src on first show)
  $registryFrame.style.display = isRegistry ? "block" : "none";
  $decisionsFrame.style.display = isDecisions ? "block" : "none";
  if (isDecisions && !$decisionsFrame.src && $decisionsFrame.dataset.src) {
    $decisionsFrame.src = $decisionsFrame.dataset.src;
  }
  // Home view section (added in Task 3); guard for absence
  const homeEl = document.getElementById('view-home');
  if (homeEl) homeEl.style.display = view === 'home' ? "" : "none";
  // Legacy eval/registry tab highlight (kept working)
  $tabEval.classList.toggle("seg-active", isDeliberate);
  $tabRegistry.classList.toggle("seg-active", isRegistry);
  // Sidebar active state (added in Task 3); guard for absence
  document.querySelectorAll('[data-view]').forEach((el) =>
    el.classList.toggle('nav-active', el.dataset.view === view));
  if (location.hash.replace(/^#/, '') !== view) location.hash = view;
}
```

Update the existing tab listeners and the `loadPrompt` handler to call `showView` with the new ids:

```javascript
$tabEval.addEventListener("click",     () => showView("deliberate"));
$tabRegistry.addEventListener("click", () => showView("registry"));
```

In the `window.addEventListener("message", ...)` `loadPrompt` handler, change `switchTab("eval")` to `showView("deliberate")`.

Add hash-driven init at the end of the module (so a reload restores the view; default home):

```javascript
window.addEventListener('hashchange', () => showView(location.hash));
showView(location.hash || 'deliberate');
```

(Use `'deliberate'` as the initial fallback for now — Task 3 changes the default to `home` once the Home view exists.)

- [ ] **Step 3: Verify**

Run the ID-PRESERVATION CONTRACT check (expect `ALL PRESENT`).
Run: `node --check sandbox/js/app.js` and `node --test sandbox/js/*.test.js 2>&1 | grep -iE "pass |fail "` (fail 0).
Manual: start `python3 server.py`, open `http://localhost:8000/`, click the eval/registry tabs — the registry iframe still toggles; the Deliberate (eval) view still chats. Append `#registry` to the URL and reload — the registry view shows.

- [ ] **Step 4: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add sandbox/index.html sandbox/js/app.js
git commit -m "feat(ui): generalize view router (showView) + Decisions iframe"
```

---

## Task 3: Sidebar + Home view

**Files:** Modify `sandbox/index.html` (sidebar markup, Home section, styles); Modify `sandbox/js/app.js` (wire nav, default home, home render).

- [ ] **Step 1: Add sidebar + Home styles**

In `sandbox/index.html`, inside the existing `<style>` block, append:

```css
.sidebar { width: 200px; flex-shrink: 0; background: var(--paper-3); border-right: 1px solid var(--line);
  display: flex; flex-direction: column; padding: 16px 0; gap: 2px; }
.sidebar-brand { font-family: var(--sans); font-weight: 600; font-size: 14px; padding: 0 16px 14px; }
.sidebar-group-label { font-size: 10px; letter-spacing: .06em; text-transform: uppercase; color: var(--ink-4); padding: 12px 16px 4px; }
.nav-item { display: flex; align-items: center; gap: 8px; padding: 7px 16px; font-size: 13px; color: var(--ink-2);
  cursor: pointer; border: none; background: none; width: 100%; text-align: left; text-decoration: none; }
.nav-item:hover { background: var(--paper-2); color: var(--ink); }
.nav-item.nav-active { background: var(--paper-2); color: var(--ink); box-shadow: inset 2px 0 0 var(--ink); }
.sidebar-foot { margin-top: auto; padding: 12px 16px 0; font-size: 11px; color: var(--ink-3); border-top: 1px solid var(--line-2); }
.home-view { max-width: 820px; margin: 0 auto; padding: 56px 24px; }
.home-steps { display: flex; gap: 14px; margin: 24px 0; }
.home-step { flex: 1; border: 1px solid var(--line); border-radius: 6px; padding: 14px; font-size: 13px; }
.home-step .ex { display: block; margin-top: 8px; font-style: italic; color: var(--ink-3); border-left: 2px solid var(--line); padding-left: 8px; font-size: 12px; }
.home-cta { display: inline-block; background: var(--ink); color: #fff; border: none; padding: 9px 18px; border-radius: 5px; font: inherit; cursor: pointer; }
```

- [ ] **Step 2: Add the sidebar `<aside>` as the first child of `<body>`**

In `sandbox/index.html`, immediately after `<body>`, add the sidebar (before the existing `<aside class="rail">`):

```html
<aside class="sidebar" id="app-sidebar">
  <div class="sidebar-brand">▣ Prompt Studio</div>
  <div class="sidebar-group-label">Workflow</div>
  <button class="nav-item" data-view="home" type="button">⌂ Home</button>
  <button class="nav-item" data-view="deliberate" type="button">Deliberate</button>
  <button class="nav-item" data-view="decisions" type="button">Decisions</button>
  <div class="sidebar-group-label">Library</div>
  <button class="nav-item" data-view="registry" type="button">Registry</button>
  <button class="nav-item" id="nav-sessions" type="button">Sessions</button>
  <div class="sidebar-foot" id="sidebar-foot">— loading…</div>
</aside>
```

- [ ] **Step 3: Add the Home view section**

In `sandbox/index.html`, inside `<div class="main-wrap">`, immediately after the `<header class="topbar">…</header>` block and before `<main id="pane-container">`, add:

```html
  <section class="home-view" id="view-home" style="display:none">
    <div id="home-empty">
      <h1 style="font-weight:600;margin:0 0 4px">Prompt Studio</h1>
      <p style="color:var(--ink-3);margin:0">Turn a conversation into a decision you can trust — fully local.</p>
      <div class="home-steps">
        <div class="home-step"><strong>① Deliberate</strong><br>Chat a decision through with your chosen model.
          <span class="ex">e.g. “Should we ship the support beta?” — you weigh that 82% of tickets are FAQ-shaped against a privacy review flagging PII risk.</span></div>
        <div class="home-step"><strong>② Shape</strong><br>✨ Suggest the structure, review, seal it.
          <span class="ex">Your model drafts: decision = “ship to redacted tickets only”, evidence = the 82% finding, surviving objection = “privacy risk remains.” You edit, then Seal.</span></div>
        <div class="home-step"><strong>③ Notarize</strong><br>A signed, verifiable record lands in Decisions.
          <span class="ex">→ ship-the-support-beta · 9 records · ✓ chain valid — citeable by hash, forever.</span></div>
      </div>
      <button class="home-cta" id="home-start-btn" type="button">Start a session →</button>
      <p style="color:var(--ink-4);margin-top:12px;font-size:12px">Local &amp; frontier models supported.</p>
    </div>
    <div id="home-hub" style="display:none">
      <h1 style="font-weight:600;margin:0 0 12px">Home</h1>
      <div class="home-steps" style="font-size:12px"><div class="home-step">① Deliberate</div><div class="home-step">② Shape</div><div class="home-step">③ Notarize</div></div>
      <button class="home-cta" id="home-new-btn" type="button">+ New session</button>
      <div id="home-recent" style="margin-top:18px"></div>
    </div>
  </section>
```

- [ ] **Step 4: Wire the sidebar + home in `app.js`**

In `sandbox/js/app.js`, after the `showView` definition, add nav wiring:

```javascript
document.querySelectorAll('.nav-item[data-view]').forEach((el) =>
  el.addEventListener('click', () => showView(el.dataset.view)));
const $homeStart = document.getElementById('home-start-btn');
if ($homeStart) $homeStart.addEventListener('click', () => showView('deliberate'));
const $homeNew = document.getElementById('home-new-btn');
if ($homeNew) $homeNew.addEventListener('click', () => { document.getElementById('new-session')?.click(); showView('deliberate'); });
const $navSessions = document.getElementById('nav-sessions');
if ($navSessions) $navSessions.addEventListener('click', () => showView('deliberate'));
```

Change the init fallback (from Task 2) so the default view is Home:

```javascript
window.addEventListener('hashchange', () => showView(location.hash));
showView(location.hash || 'home');
```

- [ ] **Step 5: Verify**

Run the ID-PRESERVATION CONTRACT (expect `ALL PRESENT`), `node --check sandbox/js/app.js`, `node --test sandbox/js/*.test.js`, `python3 -m pytest tests/ -q`.
Manual: open `http://localhost:8000/` — Home shows by default with the explainer; the sidebar switches Home/Deliberate/Decisions/Registry with no reload and highlights the active item; "Start a session →" goes to Deliberate; the sandbox chats in Deliberate; Decisions shows the Threads iframe.

- [ ] **Step 6: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add sandbox/index.html sandbox/js/app.js
git commit -m "feat(ui): app-shell sidebar + Home view, default to Home"
```

---

## Task 4: Declutter the topbar (remove duplicates)

**Files:** Modify `sandbox/index.html`.

The topbar-actions currently holds: `#mode-toggle` (Single/Compare), the registry-load block, `a[href="/registry"]` (Registry), `a[href="/threads"]` (Threads), `#seal-open-btn`, and a duplicate `#export-btn`. The sidebar now owns Registry/Decisions nav; the rail owns the primary `#export-btn`. Remove only the duplicates from the topbar — KEEP `#mode-toggle`, the registry-load block (`#registry-prompt-select`/`#registry-load-btn`/`#registry-status`), and `#seal-open-btn` (these are Deliberate controls that live in the topbar of the Deliberate view).

- [ ] **Step 1: Remove the duplicate topbar links/button**

In `sandbox/index.html` topbar-actions, delete exactly these three lines:

```html
      <a class="ghost-btn" href="/registry">Registry</a>
      <a class="ghost-btn" href="/threads">Threads</a>
      <button class="ghost-btn" id="export-btn">Export .md</button>
```

(There are two `#export-btn` in the file — the rail one at `id="export-btn"` inside `.rail-actions` and this topbar duplicate. Remove ONLY the topbar one. Verify afterward that exactly one `id="export-btn"` remains.)

- [ ] **Step 2: Verify**

Run the ID-PRESERVATION CONTRACT (expect `ALL PRESENT` — `export-btn` still present once, in the rail).
Confirm a single `export-btn`: `grep -c 'id="export-btn"' sandbox/index.html` → `1`.
`node --test sandbox/js/*.test.js`, `python3 -m pytest tests/ -q`.
Manual: open `http://localhost:8000/#deliberate` — the topbar no longer shows the Registry/Threads/Export duplicates; Single/Compare, the registry-load select+Load, and Seal still work; Export still works from the rail.

- [ ] **Step 3: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add sandbox/index.html
git commit -m "feat(ui): declutter topbar — drop Registry/Threads/Export duplicates"
```

---

## Task 5: Sidebar footer status (vault + model)

**Files:** Modify `sandbox/js/app.js`.

The sidebar has a `#sidebar-foot`. Mirror the live vault + active-model status into it (read-only; the authoritative vault card stays in the rail with all its ids intact).

- [ ] **Step 1: Populate the sidebar footer**

In `sandbox/js/app.js`, find where the vault status text is updated (search for `vault-card-sub` / `vault-status`). After the existing vault-status update, also reflect it in the footer. Add a small helper and call it wherever vault status or the active model changes:

```javascript
function updateSidebarFoot() {
  const foot = document.getElementById('sidebar-foot');
  if (!foot) return;
  const vault = (document.getElementById('vault-card-sub')?.textContent || '').trim();
  const model = getActiveModelKey ? getActiveModelKey() : '';
  foot.textContent = `vault: ${vault || '—'}${model ? ' · ' + model : ''}`;
}
```

Call `updateSidebarFoot()` at the end of module init and immediately after any code that sets `#vault-card-sub`'s text (search the file for `vault-card-sub` assignments and add the call after each). If `getActiveModelKey` is not imported in app.js, it is (used elsewhere) — confirm with grep.

- [ ] **Step 2: Verify**

Run the ID-PRESERVATION CONTRACT, `node --check sandbox/js/app.js`, `node --test sandbox/js/*.test.js`, `python3 -m pytest tests/ -q`.
Manual: the sidebar footer shows e.g. `vault: ready · gemma-4-26B` and updates with vault health.

- [ ] **Step 3: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add sandbox/js/app.js
git commit -m "feat(ui): mirror vault + model status into sidebar footer"
```

---

## Task 6: Home hub content + end-to-end acceptance

**Files:** Modify `sandbox/js/app.js`.

- [ ] **Step 1: Render empty-vs-hub + recent decisions**

In `sandbox/js/app.js`, add (and import `homeState` from `./view.js` — extend the Task-2 import: `import { resolveView, homeState } from './view.js';`):

```javascript
async function renderHome() {
  let sessionCount = 0, decisions = [];
  try { sessionCount = (document.querySelectorAll('#sessions-list .session-row, #sessions-list > *')).length; } catch (e) {}
  try {
    const r = await fetch('/api/threads');
    if (r.ok) decisions = await r.json();
  } catch (e) { decisions = []; }
  const state = homeState(sessionCount, Array.isArray(decisions) ? decisions.length : 0);
  document.getElementById('home-empty').style.display = state === 'empty' ? '' : 'none';
  document.getElementById('home-hub').style.display = state === 'hub' ? '' : 'none';
  const recent = document.getElementById('home-recent');
  if (recent && state === 'hub') {
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    const items = (Array.isArray(decisions) ? decisions : []).slice(0, 5)
      .map((t) => `<div style="padding:4px 0;font-size:12px">✓ ${esc(t.slug)} <span style="color:var(--ink-4)">· ${esc(t.title || '')}</span></div>`).join('');
    recent.innerHTML = `<div class="sidebar-group-label" style="padding-left:0">Recent decisions <a href="javascript:void(0)" id="home-see-decisions" style="text-transform:none">→ all</a></div>${items || '<div style="color:var(--ink-4);font-size:12px">none yet</div>'}`;
    document.getElementById('home-see-decisions')?.addEventListener('click', () => showView('decisions'));
  }
}
```

Call `renderHome()` whenever Home becomes visible — at the end of `showView`, add:

```javascript
  if (view === 'home') renderHome();
```

- [ ] **Step 2: Verify (automated)**

Run the ID-PRESERVATION CONTRACT (`ALL PRESENT`), `node --check sandbox/js/app.js`, `node --test sandbox/js/*.test.js 2>&1 | grep -iE "pass |fail "` (fail 0), `python3 -m pytest tests/ -q`.

- [ ] **Step 3: End-to-end manual acceptance**

Start `python3 server.py` (and ThreadHub :8110 for the Decisions view). Open `http://localhost:8000/`:
1. **Home** is the default and shows the explainer (or hub if you have sealed decisions); the worked example reads model-agnostically.
2. The **sidebar** switches Home / Deliberate / Decisions / Registry with no reload; the active item highlights.
3. **Deliberate** retains ALL sandbox behavior: pick prompt + model, Single/Compare, chat, ✨ Suggest drafts fields, Seal → the thread appears in **Decisions**, vault toggle + Reindex work, Save session + Export .md work.
4. **Decisions** shows the Threads iframe (with its ✓ badges); **Registry** shows the registry iframe.
5. The **topbar** is reduced — no duplicate Registry/Threads/Export.
6. The **sidebar footer** shows live vault + model status.
7. Reload on `#decisions` restores the Decisions view; an unknown hash falls back to Home.

- [ ] **Step 4: Screenshot check**

```bash
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless --disable-gpu --hide-scrollbars --window-size=1300,820 --virtual-time-budget=3500 --screenshot=/tmp/ui-home.png "http://localhost:8000/"
"$CHROME" --headless --disable-gpu --hide-scrollbars --window-size=1300,820 --virtual-time-budget=3500 --screenshot=/tmp/ui-deliberate.png "http://localhost:8000/#deliberate"
```
Open both PNGs and confirm: Home renders the explainer with the sidebar; Deliberate renders the chat with the decluttered topbar. A blank frame = a failure to load (check the console / module errors).

- [ ] **Step 5: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add sandbox/js/app.js
git commit -m "feat(ui): Home hub (recent decisions) + render on show"
```

---

## Self-Review

**Spec coverage:**
- Single-page app shell + persistent sidebar → Tasks 2–3. ✓
- Home explainer-that-becomes-hub (worked example, model-agnostic) → Task 3 (markup) + Task 6 (empty/hub logic). ✓
- Sidebar IA (Home/Deliberate/Decisions + Registry/Sessions, footer status) → Task 3 + Task 5. ✓
- Decisions/Registry as iframes (lazy src) → Task 2. ✓
- Decluttered topbar; Registry/Export de-duplicated → Task 4. ✓
- Per-view controls preserved (id contract) → every HTML task runs the ID-PRESERVATION CONTRACT. ✓
- Router with Home fallback → Task 1 (`resolveView`) + Task 2/3 wiring. ✓
- Testing: `node --test` for `view.js`; manual + screenshot acceptance → Task 6. ✓
- Non-goals respected: iframe embedding (not native re-mount), no backend changes, no sandbox-logic rewrite, reuse existing tokens. ✓

**Placeholder scan:** No TBD/TODO; HTML moves are specified by exact anchors + the id contract rather than brittle line numbers; `<slug>`-style values appear only in runtime/manual steps.

**Type/name consistency:** `resolveView`/`homeState`/`VIEWS` from `view.js` used consistently; `showView(id)` replaces `switchTab` and is called with the canonical ids (`home`/`deliberate`/`decisions`/`registry`); `#decisions-frame`/`#registry-frame`/`#view-home`/`.nav-item[data-view]`/`#sidebar-foot`/`#home-empty`/`#home-hub`/`#home-recent` are referenced consistently across tasks.
