# Transfer prompt — polish the Prompt Studio UI

Copy everything below into a fresh Claude Code session opened in `~/DevSwarmProjects/Clista`.

---

You are doing a **visual design pass** on "Prompt Studio," a local-first web app. The information
architecture is already built and working — your job is to make it look and feel good. It currently
works but feels cluttered/unpolished. Use the **frontend-design** skill. This is HTML/CSS/vanilla-JS
polish, **not** a rewrite of app logic.

## What the app is
Prompt Studio turns a conversation into a verifiable decision, fully local. Its spine is a three-step
workflow: **① Deliberate** (chat a decision through with a local/frontier model) → **② Shape**
(✨ Suggest drafts the decision structure, you edit, then Seal) → **③ Notarize** (a signed, hash-chained
record lands in the Decisions view). Frame the visual design around that calm, disciplined loop.

## Tech constraints (do not violate)
- **No build step, no bundler, no framework.** Plain `sandbox/index.html` (markup + a single `<style>`)
  + ES-module JS in `sandbox/js/*.js`. Edits are picked up on reload.
- It is a **single-page app shell**: a left **sidebar** (`#app-sidebar`) swaps a main view in place via
  `showView(id)` in `app.js` (driven by `location.hash`). Views: `home`, `deliberate`, `decisions`,
  `registry`, `sessions`. `decisions` and `registry` are **iframes** of `/threads/` and `/registry/`.
- **Reuse the existing design tokens** (already in `:root` of index.html) — do not introduce a new
  palette:
  - paper: `--paper #f6f3ec` `--paper-2 #ede9e0` `--paper-3 #e4dfd5`
  - ink: `--ink #0c0f14` `--ink-2 #2c3038` `--ink-3 #5c636b` `--ink-4 #9aa0a8`
  - lines: `--line` `--line-2` `--line-3` (translucent ink)
  - accents: `--amber #a87a00` `--green #2e7048` `--red #a83830` `--teal #2a6464` `--plum #614882`
  - fonts: `--sans 'Inter Tight'`, `--mono 'JetBrains Mono'`, `--serif 'Newsreader'` (all already
    loaded via a Google Fonts link). It's a warm "paper & ink" editorial aesthetic — keep that.

## 🔒 ID-PRESERVATION CONTRACT (critical — the app breaks if you drop these)
`app.js` queries these element ids. You may restyle/move/regroup them, but **every id must keep
existing**. After any edit to `index.html`, run this and confirm `ALL PRESENT`:
```bash
cd ~/DevSwarmProjects/Clista
missing=""; for id in composer composer-label export-btn input model-checklist new-session \
  pane-container prompt-badges prompt-picker rail-mode-tag registry-frame registry-load-btn \
  registry-panel-mount registry-prompt-select registry-status reindex save-session-btn \
  seg-compare seg-single send send-hint sessions-list sessions-save-slot stop-both stop-btn \
  top-k topbar-dots topbar-session topbar-subtitle use-vault vault-card-sub vault-checkbox-visual \
  vault-health vault-label-wrap vault-status decisions-frame view-home view-sessions app-sidebar \
  sidebar-foot home-empty home-hub home-recent sessions-view-list; do
  grep -q "id=\"$id\"" sandbox/index.html || missing="$missing $id"; done
[ -z "$missing" ] && echo "ALL PRESENT" || echo "MISSING:$missing"
```
(`tab-eval`/`tab-registry` are intentionally absent — they're null-guarded in JS. Don't add them.)
Also keep `data-view="..."` on the sidebar nav buttons, the `.nav-active` class hook, and the
`#view-*` section ids — `showView` toggles these.

## Files
- `sandbox/index.html` (~1080 lines) — all markup + the `<style>` block. **This is your main canvas.**
- `sandbox/js/app.js` (~740 lines) — wiring + `showView`/`renderHome`/`renderSessions`. Touch only if
  a visual change needs a class toggle; don't refactor logic.
- `sandbox/js/view.js` — pure view router (`VIEWS`, `resolveView`, `homeState`); has `node --test`.
- Other `js/*.js` — pane/model/session/vault/registry/seal logic. Don't change behavior.
- Specs + approved mockups: `docs/superpowers/specs/2026-06-14-ui-shell-redesign-design.md` and
  `docs/superpowers/specs/2026-06-14-ui-home-detail-sessions-view-design.md`. Read these for intent.

## The five views (current state → what to improve)
- **Home** (`#view-home`): a hub with the ①②③ loop, **+ New session**, recent decisions
  (`#home-recent`), and an always-on collapsible "How the pieces work together" explainer
  (`#home-empty` shows for first-timers, `#home-hub` for returning users, the explainer is a sibling
  shown in both). Make it feel like a confident landing page.
- **Deliberate** (the sandbox): this is the BUSIEST and the main complaint. It stacks the nav sidebar +
  a controls **rail** (`#sessions-rail`: Active Prompt picker `#prompt-picker`, Models
  `#model-checklist`, Save/Export, Vault card `#vault-card`) + a **topbar** (`#mode-toggle`
  Single/Compare, registry-load `#registry-prompt-select`+`#registry-load-btn`, Seal `#seal-open-btn`)
  + the chat panes (`#pane-container`) + the input (`#composer`: `#input`, `#send`, `#use-vault`,
  `#top-k`, `#reindex`). **Make this calm.** Ideas (your call): collapse the controls rail behind a
  "Setup" toggle so the default is mostly chat; default to a single pane (Compare opt-in); tuck the
  vault + top-K controls inline near the input; reduce the topbar to essentials.
- **Decisions** / **Registry**: iframes (`#decisions-frame`, `#registry-frame`). You can't restyle
  inside the iframe from here, but make their framing/container in the shell clean. (The Threads
  widget at `threads/interface/threads_widget.html` and the registry widget have their own styles you
  may also polish if you want full coherence.)
- **Sessions** (`#view-sessions`): a clean saved-sessions list (`#sessions-view-list`) + "+ New
  session". Recently added; make the rows feel good.

## What "jacked up" likely means (fix these)
- Too much visual density on Deliberate (two left columns + topbar + dual panes at once).
- Inconsistent spacing/typography/rhythm across the new sidebar/home vs the older rail/topbar/panes.
- The new shell chrome and the older sandbox chrome don't feel like one designed system yet.
- General polish: alignment, hierarchy, hover/active states, empty states, the sidebar's weight.

## How to run + verify (do this constantly — verify in the BROWSER, screenshots)
```bash
# start the static server
cd ~/DevSwarmProjects/Clista && (lsof -ti :8000 | xargs kill 2>/dev/null; python3 server.py >/tmp/ps.log 2>&1 &)
# (optional, for the Decisions view to show real records) start ThreadHub:
cd ~/threadhub && (curl -sf -m2 http://localhost:8110/ >/dev/null || node bin/cli.js serve --port 8110 >/tmp/th.log 2>&1 &)
# screenshot each view headless and LOOK at the PNGs after every change:
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
for v in "" "#deliberate" "#decisions" "#registry" "#sessions"; do n=$(echo $v|tr -d '#'); n=${n:-home}; \
  "$CHROME" --headless --disable-gpu --hide-scrollbars --window-size=1400,900 --virtual-time-budget=3500 \
  --screenshot=/tmp/ui-$n.png "http://localhost:8000/$v" 2>/dev/null; done
```
**Always confirm the app still boots**: after edits, headless-load `http://localhost:8000/`, check the
model checklist populates and there are **no console SyntaxError/TypeError** (the app.js is a single
ES module — one stray error blanks the whole UI). And keep tests green:
```bash
node --test sandbox/js/*.test.js 2>&1 | grep -iE "pass |fail "   # expect fail 0
python3 -m pytest tests/ -q | tail -1                            # expect all pass
```

## Working agreement
- Don't merge or push. Work on the current branch. Commit in small, reviewable steps.
- After each visual change: run the ID-PRESERVATION CONTRACT, re-screenshot, and look at the result.
- Lead with the Deliberate-view declutter (the biggest pain), then Home polish, then cross-view
  consistency. Show me before/after screenshots as you go.

Goal: one cohesive, calm, editorial UI that makes the deliberate → shape → notarize workflow obvious
and uncluttered — without breaking the working app.
