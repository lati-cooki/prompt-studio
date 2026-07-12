# Pane System Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate onto the one live (model-checklist / `activePaneMap`) pane system by deleting the dead legacy "A/B" system and its inert markup/CSS, and fix the frontier-model lookup so Claude/GPT sends work.

**Architecture:** The map (see spec) shows only the model-checklist system is live; the A/B system (`stateA/B`, `paneA/B`, `#mode-toggle`, the topbar `.registry-load` + `handleRegistryLoad`) is unreachable dead code. This plan fixes one real bug first (frontier lookup), then deletes the dead JS, then the dead markup/CSS — in that order so no live `getElementById` ref is left dangling.

**Tech Stack:** Vanilla JS ES modules, `node --test`, headless-Chrome boot verification, interactive acceptance.

**Spec:** `docs/superpowers/specs/2026-06-14-pane-consolidation-design.md`

---

## Boot-check (run after every task)
The sandbox app is a single ES module — one stray error blanks the UI. After each task confirm it boots
clean and the suites pass:
```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
node --check sandbox/js/app.js && echo PARSES
node --test sandbox/js/*.test.js 2>&1 | grep -iE "pass |fail "      # expect fail 0
python3 -m pytest tests/ -q | tail -1                                # expect all pass
(lsof -ti :8000 | xargs kill 2>/dev/null; sleep 1; nohup python3 server.py >/tmp/ps.log 2>&1 &); sleep 2
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless --disable-gpu --enable-logging=stderr --v=1 --virtual-time-budget=3000 --dump-dom "http://localhost:8000/#deliberate" 2>/tmp/cc.log \
  | python3 -c "import sys,re;h=sys.stdin.read();m=re.search(r'id=\"model-checklist\"[^>]*>(.*?)</div>',h,re.S);print('models populated:',bool((m.group(1) if m else '').strip()))"
grep -i "CONSOLE" /tmp/cc.log | grep -ivE "VizNull|BackForward" | grep -iE "Uncaught|TypeError|ReferenceError|SyntaxError" | head -3 || echo "no console JS errors"
```
Expected each time: `PARSES`, fail 0, Python pass, `models populated: True`, no console JS errors.

---

## Task 1: Fix the frontier-model lookup (the real bug)

**Files:** Modify `sandbox/js/app.js`.

`activePanes()` and the meter look models up in `liveModels`, which only holds LM-Studio-discovered
models — so frontier models (Claude/GPT) resolve to `undefined` and `send.js` crashes on `model.endpoint`.
`ALL_MODELS` holds frontier + local (it's kept in sync with `liveModels` at discovery).

- [ ] **Step 1: Fix `activePanes()`**

In `sandbox/js/app.js`, find:
```javascript
    model: liveModels[modelKey],
```
Change to:
```javascript
    model: ALL_MODELS[modelKey],
```

- [ ] **Step 2: Fix the meter context window**

In `sandbox/js/app.js` `createOrUpdatePane`, find:
```javascript
    contextWindow: liveModels[modelKey]?.contextWindow ?? 32768,
```
Change to:
```javascript
    contextWindow: ALL_MODELS[modelKey]?.contextWindow ?? 32768,
```

- [ ] **Step 3: Verify**

Run the Boot-check (expect all green). Confirm both edits: `grep -n "liveModels\[modelKey\]" sandbox/js/app.js` should now return **only** the assignment inside `loadLMStudioModels` (`liveModels[m.id] = …` is a different pattern; the `liveModels[modelKey]` reads should be gone) — run `grep -nE "liveModels\[modelKey\]|model: ALL_MODELS|contextWindow: ALL_MODELS" sandbox/js/app.js`.

- [ ] **Step 4: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add sandbox/js/app.js
git commit -m "fix(panes): resolve models via ALL_MODELS so frontier sends work"
```

---

## Task 2: Delete the dead legacy JS

**Files:** Modify `sandbox/js/app.js`.

Delete the unreachable A/B system. (Order matters across tasks: this removes the `$registryLoadBtn`
click listener BEFORE Task 3 removes its markup, so no `getElementById` returns null into a live call.)

- [ ] **Step 1: Remove the legacy declarations + the init paneA**

In `sandbox/js/app.js`, delete these lines (they are contiguous near the top):
```javascript
const paneContainer = document.getElementById("pane-container");
const stateA = createPaneState(DEFAULT_SYSTEM_PROMPT);
let   stateB = null;
let   paneB  = null;
```
(KEEP `$paneContainer = document.getElementById("pane-container")` lower down — that's the live binding.)
Also delete:
```javascript
let modelKeyA = getActiveModelKey();
let modelKeyB = null;
```
And delete the whole init paneA block:
```javascript
const paneA = createPane({
  id:              "A",
  container:       paneContainer,
  initialPrompt:   DEFAULT_SYSTEM_PROMPT,
  modelKeys:       Object.keys(ALL_MODELS),
  initialModelKey: modelKeyA,
});
```
(`getActiveModelKey` may now be an unused import — leave the import; it's harmless and config.js still exports it. If `createPaneState`/`createPane` become unused they are still used by the live `createOrUpdatePane`, so keep those imports.)

- [ ] **Step 2: Remove the dead DOM refs**

Delete these ref lines:
```javascript
const $segSingle     = document.getElementById("seg-single");
const $segCompare    = document.getElementById("seg-compare");
const $stopBoth      = document.getElementById("stop-both");
const $registrySelect = document.getElementById("registry-prompt-select");
const $registryLoadBtn = document.getElementById("registry-load-btn");
const $registryStatus  = document.getElementById("registry-status");
```

- [ ] **Step 3: Remove the dead functions + listener + boot call**

Delete the functions `showRegistryStatus`, `paneHasConversation`, `applyRegistryPromptToPane`,
`populateRegistrySelect`, and `handleRegistryLoad` in their entirety, and the two trailing lines:
```javascript
$registryLoadBtn.addEventListener("click", handleRegistryLoad);
populateRegistrySelect();
```
(Use `grep -n "function showRegistryStatus\|function paneHasConversation\|function applyRegistryPromptToPane\|async function populateRegistrySelect\|async function handleRegistryLoad" sandbox/js/app.js` to find their start lines; delete each from its `function`/`async function` line through its closing `}`.)

- [ ] **Step 4: Confirm nothing live referenced them**

Run: `grep -nE "stateA|stateB|paneA|paneB|modelKeyA|modelKeyB|\\\$segSingle|\\\$segCompare|\\\$stopBoth|\\\$registrySelect|\\\$registryLoadBtn|\\\$registryStatus|applyRegistryPromptToPane|handleRegistryLoad|populateRegistrySelect|showRegistryStatus|paneHasConversation" sandbox/js/app.js`
Expected: **no matches** (all gone). If any remain, they were a live use — STOP and report it.

- [ ] **Step 5: Verify**

Run the Boot-check (expect all green: PARSES, fail 0, models populated, no console errors).

- [ ] **Step 6: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add sandbox/js/app.js
git commit -m "refactor(panes): delete dead legacy A/B pane system from app.js"
```

---

## Task 3: Delete the dead markup + the declutter CSS hacks

**Files:** Modify `sandbox/index.html`.

- [ ] **Step 1: Remove the `#mode-toggle` + `.registry-load` + `#stop-both` markup**

In `sandbox/index.html` topbar-actions, delete the `#mode-toggle` block:
```html
      <div class="seg-toggle" id="mode-toggle">
        <button class="seg-btn seg-active" id="seg-single">
          <span class="seg-dot"></span>Single
        </button>
        <button class="seg-btn" id="seg-compare">
          <span class="seg-dot-a"></span><span class="seg-dot-b"></span>Compare A / B
        </button>
      </div>
```
the `.registry-load` block:
```html
      <div class="registry-load" title="Load system prompt from registry">
        <select id="registry-prompt-select" class="registry-select" aria-label="Registry prompt">
          <option value="">Load from registry…</option>
        </select>
        <button type="button" class="ghost-btn" id="registry-load-btn">Load</button>
      </div>
      <span class="registry-status" id="registry-status" hidden></span>
```
and the legacy stop-both button:
```html
      <button class="stop-btn" id="stop-both" hidden>⏹ Stop both</button>
```
(KEEP `<button class="stop-btn" id="stop-btn" hidden>⏹ Stop</button>` — that's the live single stop.)

- [ ] **Step 2: Remove the now-redundant declutter CSS hacks**

These hid the elements just deleted; remove them. Delete:
```css
.pane[data-pane-id="A"] { display: none !important; }
```
and:
```css
#mode-toggle, .registry-load { display: none !important; }
```
(They live in the `/* ── Deliberate declutter ── */` and single-pane comment blocks added earlier. Also remove the now-stale explanatory comments referring to "retire the legacy paneA" / "legacy Single/Compare toggle" so the CSS comments don't describe deleted things — but keep the comments about the rail drawer and registry-panel-mount, which are still in force.)

- [ ] **Step 3: Verify the dead ids are gone and the live ones remain**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
echo "dead ids (expect 0 each):"; for id in seg-single seg-compare mode-toggle registry-prompt-select registry-load-btn registry-status stop-both; do echo "  $id: $(grep -c "id=\"$id\"" sandbox/index.html)"; done
echo "live ids (expect 1 each):"; for id in stop-btn pane-container composer input send prompt-picker model-checklist setup-toggle seal-open-btn; do echo "  $id: $(grep -c "id=\"$id\"" sandbox/index.html)"; done
```
Expected: all dead ids `0`, all live ids `1`.

- [ ] **Step 4: Verify**

Run the Boot-check. Additionally screenshot Deliberate and confirm it still shows a single pane with the
topbar reduced to `⚙ Setup` + `Seal`:
```bash
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless --disable-gpu --hide-scrollbars --window-size=1400,900 --virtual-time-budget=3500 --screenshot=/tmp/pane-consol.png "http://localhost:8000/#deliberate" 2>/dev/null && echo "shot /tmp/pane-consol.png"
"$CHROME" --headless --disable-gpu --virtual-time-budget=3000 --dump-dom "http://localhost:8000/#deliberate" 2>/dev/null | python3 -c "import sys,re;h=sys.stdin.read();print('pane sections:', re.findall(r'data-pane-id=\"([^\"]*)\"', h))"
```
Expected: one `data-pane-id` (a model key like `claude-haiku-4-5`), NOT `A`.

- [ ] **Step 5: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add sandbox/index.html
git commit -m "refactor(panes): delete dead Single/Compare + topbar registry-load markup + CSS hacks"
```

---

## Task 4: Remove the inert `.compare` CSS rules (cleanup)

**Files:** Modify `sandbox/index.html`.

The `.compare .pane[data-pane-id="A"|"B"]` and `.compare .pane …` CSS rules are permanently inert
(`.compare` is never added to `#pane-container`, and the only thing that could have — the mode-toggle —
is now deleted). Remove them for cleanliness. They are scattered (grep for the line numbers).

- [ ] **Step 1: Find and remove every `.compare` rule**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
grep -n "\.compare " sandbox/index.html
```
For each reported rule (each is a single CSS selector block `.compare … { … }`), delete the whole block
(selector line through its closing `}`). Work from the BOTTOM line upward so earlier line numbers don't
shift. After removing, confirm none remain:
```bash
grep -c "\.compare " sandbox/index.html   # expect 0
```

- [ ] **Step 2: Verify**

Run the Boot-check (expect all green; this is CSS-only so behavior is unchanged). Confirm the Deliberate
screenshot still renders the single pane normally.

- [ ] **Step 3: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add sandbox/index.html
git commit -m "chore(panes): remove inert .compare CSS rules"
```

---

## Task 5: End-to-end interactive acceptance

**Files:** none (verification only).

Automated checks can't drive a real chat-send; these are for the human operator.

- [ ] **Step 1: Automated final pass**

Run the Boot-check one more time (all green). Confirm a clean tree: `git status -s` (empty).

- [ ] **Step 2: Interactive acceptance (human)**

Start the stack (`python3 server.py`; LM-Studio/MLX for a local model; ThreadHub :8110 for Decisions).
Open `http://localhost:8000/#deliberate` and verify:
1. **Single pane by default**; topbar shows only `⚙ Setup` + `Seal`.
2. **Send to a LOCAL model** (open ⚙ Setup → pick a local model) → type a directive → SEND → a reply streams in.
3. **Send to a FRONTIER model** (⚙ Setup → pick Claude/GPT; requires the relevant API key in `.env`) →
   SEND → a reply streams in (this is the bug that was crashing before — confirm no console error).
4. **Compare** → in ⚙ Setup check a 2nd model → a 2nd pane appears; SEND goes to both.
5. **Load a prompt** → ⚙ Setup → pick one under "Active Prompt" → it applies to the pane(s).
6. **Save a session**, start a New session, then reload the saved one → conversation + model(s) restore.
7. **✨ Suggest → Seal** → the decision seals and appears in the Decisions view.
8. No console errors throughout (DevTools console).

Report any failure; each task committed separately so a single step is easy to revert/fix.

---

## Self-Review

**Spec coverage:**
- Delete dead legacy JS (stateA/B, paneA/B, modelKeyA/B, init paneA, refs, dead fns + listener + boot call) → Task 2. ✓
- Delete dead markup (mode-toggle, registry-load, stop-both) + declutter CSS hacks → Task 3. ✓
- Remove inert `.compare` CSS → Task 4. ✓
- Fix frontier lookup (`activePanes()` + meter → `ALL_MODELS`) → Task 1. ✓
- Resulting behavior (single pane default, compare via multi-select, local+frontier send) → verified in Task 5. ✓
- ID-contract change (dead ids removed in sync with their JS) → Task 2 before Task 3 ordering + Task 3 Step 3 check. ✓
- Testing: `node --test` stays green every task; headless boot check every task; interactive acceptance Task 5. ✓
- Non-goals respected: no model-selector/send.js/seal/persistence changes; no new Single/Compare toggle. ✓

**Placeholder scan:** No TBD/TODO; deletions are specified by exact code blocks + grep anchors; line numbers avoided (they shift) in favor of content anchors.

**Type/name consistency:** `ALL_MODELS` (the kept, in-sync map) is used consistently for the lookup fix; `$paneContainer`/`activePaneMap`/`activePanes`/`createOrUpdatePane`/`syncPanes` (live system) are untouched; the deleted symbols are referenced only in deletion steps and the Task-2 Step-4 "expect no matches" guard.
