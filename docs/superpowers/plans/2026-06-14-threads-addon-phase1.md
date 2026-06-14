# Threads Add-on — Phase 1 (Read-Only Viewer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only "Threads" tab to Prompt Studio that lists threads from a ThreadHub sidecar, opens a thread to show its record chain, and surfaces ThreadHub's chain-verification status.

**Architecture:** ThreadHub runs as a launcher-managed Node sidecar on a private port (8110). `server.py` gains three read-only GET proxy routes that forward to ThreadHub server-to-server via the Python stdlib (`urllib`). A new static widget served at `/threads` renders the results in Studio's own UI. Zero changes to ThreadHub; records are never copied into `prompt_studio.db`.

**Tech Stack:** Python 3 stdlib `http.server` + `urllib` (server), vanilla JS + HTML/CSS (widget), Node ≥ 22 (ThreadHub sidecar, unchanged), `unittest` run via `pytest` (tests).

**Spec:** `docs/superpowers/specs/2026-06-14-threads-addon-design.md`

---

## ThreadHub response shapes (confirmed against the live CLI)

- `GET /threads` → array of `{ id, slug, title, created_by, created_at, genesis_hash }` (no record count, no question).
- `GET /t/<slug>.json` → array of envelopes `{ seq, kind, author, author_key, recorded_at, prev, payload, hub, thread }`. **No per-record `record_hash`/`signature`** in this JSON.
- `GET /t/<slug>/verify` → `{ thread, slug, records, head, valid, trusted, problems }`.
- `GET /` → `{ instance, records, threads:[{id,slug,title}] }` (used as the health endpoint).

Because per-record hash/signature are not in `/t/<slug>.json`, the detail view shows the `prev` chain-linkage per record plus the **chain-level** verified badge from `/verify` (chain verification is what proves every signature). This is an intentional, ThreadHub-unchanged adaptation.

## File Structure

- **Modify** `server.py` — add `urllib` imports, `THREADHUB_PORT` constant, `is_safe_slug()` helper, `proxy_threadhub_get()` + three handler methods, and four routes in `do_GET` (`/api/threads`, `/api/threads/<slug>`, `/api/threads/<slug>/verify`, `/threads`).
- **Create** `threads/interface/threads_widget.html` — the read-only Threads UI (list + detail), vanilla JS calling the proxy routes.
- **Modify** `sandbox/index.html` — add a "Threads" nav link beside the existing Registry link.
- **Create** `sandbox/_run-threadhub.sh` — sidecar launch helper.
- **Modify** `sandbox/launch.command` — free port 8110, spawn the sidecar window, health-wait on `http://localhost:8110/`.
- **Modify** `tests/test_server.py` — add proxy-route + slug-validation tests (mock `urllib`).

---

## Task 1: Slug validation helper

**Files:**
- Modify: `server.py` (module-level function near the top, after constants)
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_server.py`:

```python
class TestSlugValidation(unittest.TestCase):
    def test_accepts_plain_slug(self):
        self.assertTrue(server.is_safe_slug("founding"))
        self.assertTrue(server.is_safe_slug("workflow-audit-q2"))

    def test_rejects_path_separators_and_traversal(self):
        self.assertFalse(server.is_safe_slug("a/b"))
        self.assertFalse(server.is_safe_slug(".."))
        self.assertFalse(server.is_safe_slug("../etc/passwd"))

    def test_rejects_empty(self):
        self.assertFalse(server.is_safe_slug(""))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/DevSwarmProjects/Clista && python3 -m pytest tests/test_server.py::TestSlugValidation -v`
Expected: FAIL with `AttributeError: module 'server' has no attribute 'is_safe_slug'`

- [ ] **Step 3: Write minimal implementation**

In `server.py`, immediately after the constants block (after `MAX_BODY_BYTES = ...`):

```python
THREADHUB_PORT = 8110


def is_safe_slug(slug):
    return bool(slug) and '/' not in slug and '..' not in slug
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/DevSwarmProjects/Clista && python3 -m pytest tests/test_server.py::TestSlugValidation -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat(threads): add slug validation helper and ThreadHub port constant"
```

---

## Task 2: Proxy helper + threads list route

**Files:**
- Modify: `server.py` (imports, `proxy_threadhub_get`, `handle_get_threads`, route in `do_GET`)
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_server.py` (the `unittest.mock` `patch` import already exists at top of the file via `from unittest.mock import ...`; if not, add `from unittest.mock import patch`):

```python
class FakeResp:
    def __init__(self, body, status=200):
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestThreadsProxy(unittest.TestCase):
    @patch("server.urllib.request.urlopen")
    def test_threads_list_proxied(self, mock_open):
        mock_open.return_value = FakeResp(b'[{"slug":"founding","title":"X"}]', 200)
        h = MockHandler()
        h.handle_get_threads()
        self.assertEqual(h._last_status, 200)
        self.assertIn(b'founding', h._body_written)

    @patch("server.urllib.request.urlopen",
           side_effect=server.urllib.error.URLError("connection refused"))
    def test_threadhub_unreachable_returns_502(self, mock_open):
        h = MockHandler()
        h.handle_get_threads()
        self.assertEqual(h._last_status, 502)
        self.assertIn(b'threadhub_unreachable', h._body_written)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/DevSwarmProjects/Clista && python3 -m pytest tests/test_server.py::TestThreadsProxy -v`
Expected: FAIL with `AttributeError: 'MockHandler' object has no attribute 'handle_get_threads'` (and/or `server.urllib` not defined)

- [ ] **Step 3: Write minimal implementation**

In `server.py`, add to the imports at the top:

```python
import urllib.request
import urllib.error
```

Add these methods inside `class PromptStudioHandler` (e.g. after `send_raw_json`):

```python
    def proxy_threadhub_get(self, th_path):
        url = f"http://localhost:{THREADHUB_PORT}{th_path}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                body = resp.read()
                status = resp.status
        except urllib.error.HTTPError as e:
            body = e.read()
            status = e.code
        except urllib.error.URLError:
            self.send_json(
                {"error": "ThreadHub is not reachable", "code": "threadhub_unreachable"},
                status=502,
            )
            return
        self.send_raw_json(body.decode('utf-8'), status=status)

    def handle_get_threads(self):
        self.proxy_threadhub_get("/threads")
```

In `do_GET`, add this branch right after the `elif self.path.startswith('/registry-asset/'):` block:

```python
        elif self.path == '/api/threads':
            self.handle_get_threads()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/DevSwarmProjects/Clista && python3 -m pytest tests/test_server.py::TestThreadsProxy -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat(threads): proxy GET /api/threads to ThreadHub with unreachable handling"
```

---

## Task 3: Thread detail + verify routes

**Files:**
- Modify: `server.py` (`handle_get_thread`, `handle_get_thread_verify`, routes in `do_GET`)
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

Add to `class TestThreadsProxy` in `tests/test_server.py`:

```python
    @patch("server.urllib.request.urlopen")
    def test_thread_detail_proxied(self, mock_open):
        mock_open.return_value = FakeResp(b'[{"seq":0,"kind":"genesis"}]', 200)
        h = MockHandler()
        h.handle_get_thread("founding")
        self.assertEqual(h._last_status, 200)
        self.assertIn(b'genesis', h._body_written)

    @patch("server.urllib.request.urlopen")
    def test_thread_verify_proxied(self, mock_open):
        mock_open.return_value = FakeResp(b'{"valid":true,"records":14}', 200)
        h = MockHandler()
        h.handle_get_thread_verify("founding")
        self.assertEqual(h._last_status, 200)
        self.assertIn(b'"valid":true', h._body_written)

    def test_thread_detail_rejects_bad_slug(self):
        h = MockHandler()
        h.handle_get_thread("../etc/passwd")
        self.assertEqual(h._last_status, 400)

    def test_thread_verify_rejects_bad_slug(self):
        h = MockHandler()
        h.handle_get_thread_verify("a/b")
        self.assertEqual(h._last_status, 400)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/DevSwarmProjects/Clista && python3 -m pytest tests/test_server.py::TestThreadsProxy -v`
Expected: FAIL with `AttributeError: 'MockHandler' object has no attribute 'handle_get_thread'`

- [ ] **Step 3: Write minimal implementation**

In `server.py`, add inside `class PromptStudioHandler` (after `handle_get_threads`):

```python
    def handle_get_thread(self, slug):
        if not is_safe_slug(slug):
            self.send_error(400, "Invalid slug")
            return
        self.proxy_threadhub_get(f"/t/{slug}.json")

    def handle_get_thread_verify(self, slug):
        if not is_safe_slug(slug):
            self.send_error(400, "Invalid slug")
            return
        self.proxy_threadhub_get(f"/t/{slug}/verify")
```

In `do_GET`, add this branch right after the `elif self.path == '/api/threads':` branch from Task 2:

```python
        elif self.path.startswith('/api/threads/'):
            rest = self.path[len('/api/threads/'):]
            if rest.endswith('/verify'):
                self.handle_get_thread_verify(rest[:-len('/verify')])
            else:
                self.handle_get_thread(rest)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/DevSwarmProjects/Clista && python3 -m pytest tests/test_server.py::TestThreadsProxy -v`
Expected: PASS (6 tests in the class)

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat(threads): proxy thread detail and verify routes with slug validation"
```

---

## Task 4: Threads widget + route + nav link

**Files:**
- Create: `threads/interface/threads_widget.html`
- Modify: `server.py` (`/threads` route in `do_GET`)
- Modify: `sandbox/index.html:697` (add nav link)
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_server.py`:

```python
class TestThreadsRoute(unittest.TestCase):
    def test_threads_route_serves_widget(self):
        h = MockHandler()
        h.path = '/threads'
        h.do_GET()
        self.assertEqual(h._last_status, 200)
        self.assertTrue(len(h._body_written) > 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/DevSwarmProjects/Clista && python3 -m pytest tests/test_server.py::TestThreadsRoute -v`
Expected: FAIL — `send_error` sets `_last_status` to 404 (no `/threads` route yet), so the `assertEqual(..., 200)` fails.

- [ ] **Step 3a: Create the widget file**

Create `threads/interface/threads_widget.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Threads</title>
<style>
:root {
  --paper-2: #ede9e0; --ink: #0c0f14; --ink-3: #5c636b; --ink-4: #9aa0a8;
  --line: rgba(12,15,20,0.13); --green: #2e7048; --red: #a83830;
  --sans: 'Inter Tight', -apple-system, sans-serif;
  --mono: ui-monospace, 'JetBrains Mono', monospace;
}
*, *::before, *::after { box-sizing: border-box; }
body { font-family: var(--sans); font-size: 13px; color: var(--ink);
  background: var(--paper-2); margin: 0; padding: 48px 24px 72px; }
.wrap { max-width: 820px; margin: 0 auto; }
h1 { font-weight: 600; font-size: 22px; margin: 0 0 4px; }
.sub { color: var(--ink-3); margin: 0 0 28px; }
a.back { color: var(--ink-3); text-decoration: none; cursor: pointer; }
.row { display: flex; justify-content: space-between; gap: 12px;
  padding: 12px 0; border-bottom: 1px solid var(--line); cursor: pointer; }
.row:hover { opacity: 0.75; }
.row .title { font-weight: 500; }
.row .meta { color: var(--ink-3); font-size: 12px; }
.badge { font-family: var(--mono); font-size: 11px; white-space: nowrap; }
.badge.ok { color: var(--green); }
.badge.bad { color: var(--red); }
.badge.pending { color: var(--ink-4); }
.rec { padding: 8px 0; border-bottom: 1px solid var(--line); font-family: var(--mono); font-size: 12px; }
.rec .k { color: var(--ink-3); }
.err { color: var(--red); padding: 16px 0; }
.hash { color: var(--ink-4); }
</style>
</head>
<body>
<div class="wrap">
  <div id="header">
    <h1>Threads</h1>
    <p class="sub">Signed decision records from ThreadHub. <span class="badge">trusted: false — chain verification proves structure, never content.</span></p>
  </div>
  <div id="view"></div>
</div>
<script>
const view = document.getElementById('view');

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
function short(h) { return h ? esc(String(h).slice(0, 18)) + '…' : ''; }

async function getJSON(path) {
  const res = await fetch(path);
  if (!res.ok) {
    let code = res.status;
    try { code = (await res.json()).code || code; } catch (e) {}
    throw new Error(code);
  }
  return res.json();
}

async function showList() {
  view.innerHTML = '<p class="sub">Loading…</p>';
  let threads;
  try {
    threads = await getJSON('/api/threads');
  } catch (e) {
    view.innerHTML = '<p class="err">ThreadHub sidecar not running — start it via the launcher. (' + esc(e.message) + ')</p>';
    return;
  }
  if (!threads.length) { view.innerHTML = '<p class="sub">No threads yet.</p>'; return; }
  view.innerHTML = threads.map(t => `
    <div class="row" data-slug="${esc(t.slug)}">
      <span>
        <div class="title">${esc(t.title)}</div>
        <div class="meta">${esc(t.created_at)} · ${esc(t.created_by)}</div>
      </span>
      <span class="badge pending" data-verify="${esc(t.slug)}">checking…</span>
    </div>`).join('');
  view.querySelectorAll('.row').forEach(r =>
    r.addEventListener('click', () => showDetail(r.dataset.slug)));
  threads.forEach(t => fillBadge(t.slug));
}

async function fillBadge(slug) {
  const el = view.querySelector(`[data-verify="${CSS.escape(slug)}"]`);
  if (!el) return;
  try {
    const v = await getJSON('/api/threads/' + encodeURIComponent(slug) + '/verify');
    el.className = 'badge ' + (v.valid ? 'ok' : 'bad');
    el.textContent = (v.valid ? '✓ chain valid' : '✗ broken') + ' · ' + v.records + ' records';
  } catch (e) {
    el.className = 'badge bad';
    el.textContent = '✗ ' + esc(e.message);
  }
}

async function showDetail(slug) {
  view.innerHTML = '<p class="sub"><a class="back" id="back">← all threads</a></p><p class="sub">Loading…</p>';
  document.getElementById('back').addEventListener('click', showList);
  let chain, verify;
  try {
    [chain, verify] = await Promise.all([
      getJSON('/api/threads/' + encodeURIComponent(slug)),
      getJSON('/api/threads/' + encodeURIComponent(slug) + '/verify'),
    ]);
  } catch (e) {
    view.innerHTML = '<p class="sub"><a class="back" id="back2">← all threads</a></p><p class="err">Could not load thread (' + esc(e.message) + ')</p>';
    document.getElementById('back2').addEventListener('click', showList);
    return;
  }
  const badge = verify.valid
    ? `<span class="badge ok">✓ chain verified · ${verify.records} records</span>`
    : `<span class="badge bad">✗ chain broken · ${esc((verify.problems || []).join('; '))}</span>`;
  const rows = chain.map(r => `
    <div class="rec">
      <span class="k">seq ${esc(r.seq)} · ${esc(r.kind)} · ${esc(r.author)}</span><br>
      <span class="hash">${esc(r.recorded_at)} · prev ${short(r.prev)}</span>
    </div>`).join('');
  view.innerHTML = `
    <p class="sub"><a class="back" id="back3">← all threads</a></p>
    <h1 style="font-size:18px">${esc(slug)}</h1>
    <p>${badge} · head ${short(verify.head)}</p>
    ${rows}`;
  document.getElementById('back3').addEventListener('click', showList);
}

showList();
</script>
</body>
</html>
```

> Note for the implementer: the record-chain fetch hits `/api/threads/<slug>` (the server maps that to ThreadHub's `/t/<slug>.json`) — do **not** append `.json` on the client side.

- [ ] **Step 3b: Add the route in `server.py`**

In `do_GET`, add right after the `/api/threads/` branch from Task 3:

```python
        elif self.path in ('/threads', '/threads/'):
            self.serve_file('threads/interface/threads_widget.html', 'text/html')
```

- [ ] **Step 3c: Add the nav link**

In `sandbox/index.html`, line 697 currently reads:

```html
      <a class="ghost-btn" href="/registry">Registry</a>
```

Add a Threads link immediately after it:

```html
      <a class="ghost-btn" href="/registry">Registry</a>
      <a class="ghost-btn" href="/threads">Threads</a>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/DevSwarmProjects/Clista && python3 -m pytest tests/test_server.py::TestThreadsRoute -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py threads/interface/threads_widget.html sandbox/index.html
git commit -m "feat(threads): serve Threads widget at /threads and add nav link"
```

---

## Task 5: ThreadHub sidecar launch integration

**Files:**
- Create: `sandbox/_run-threadhub.sh`
- Modify: `sandbox/launch.command`

- [ ] **Step 1: Create the sidecar helper**

Create `sandbox/_run-threadhub.sh`:

```bash
#!/bin/bash
echo "[ThreadHub server — :8110]"
cd ~/threadhub
exec node bin/cli.js serve --port 8110
```

Then make it executable:

```bash
chmod +x ~/DevSwarmProjects/Clista/sandbox/_run-threadhub.sh
```

- [ ] **Step 2: Add port freeing**

In `sandbox/launch.command`, find the block:

```bash
free_port 7777
free_port 8080
free_port 8091
free_port 8100
```

Add one line after it:

```bash
free_port 8110
```

- [ ] **Step 3: Spawn the sidecar window**

In `sandbox/launch.command`, inside the `osascript` `tell application "Terminal"` block, add a `do script` line after the existing `_run-vault.sh` line:

```applescript
    do script "bash '$DIR/_run-threadhub.sh'"
```

- [ ] **Step 4: Add the health-wait loop**

In `sandbox/launch.command`, after the existing "Waiting for vault search…" loop and before the final `open "http://localhost:7777"` line, add:

```bash
echo "Waiting for ThreadHub..."
for i in {1..60}; do
  curl -sf http://localhost:8110/ >/dev/null 2>&1 && break
  sleep 0.5
done
```

- [ ] **Step 5: Manual verification**

Run: `bash ~/DevSwarmProjects/Clista/sandbox/_run-threadhub.sh` in a terminal, then in another:

```bash
curl -sf http://localhost:8110/ | head -c 200
```

Expected: JSON like `{"instance":"threadhub.v0","records":...,"threads":[...]}`. Stop the helper with Ctrl+C.

- [ ] **Step 6: Commit**

```bash
git add sandbox/_run-threadhub.sh sandbox/launch.command
git commit -m "feat(threads): launch ThreadHub sidecar on :8110 from the launcher"
```

---

## Task 6: End-to-end acceptance (real ThreadHub + browser)

**Files:** none (verification only)

- [ ] **Step 1: Seed a ThreadHub instance with the bundled fixture**

```bash
cd ~/threadhub
ID=$(node bin/cli.js identity create --name Troy --kind human | grep -oE 'id_[A-Za-z0-9]+' | head -1)
node bin/cli.js ingest --events threads/founding-architecture.ndjson --author "$ID" --slug founding
node bin/cli.js verify --thread founding
```

Expected: `verify` reports `"valid": true`.

- [ ] **Step 2: Start the sidecar and Studio**

```bash
# Terminal A
cd ~/threadhub && node bin/cli.js serve --port 8110
# Terminal B
cd ~/DevSwarmProjects/Clista && python3 server.py
```

- [ ] **Step 3: Verify the proxy routes**

```bash
curl -s http://localhost:8000/api/threads | head -c 200
curl -s http://localhost:8000/api/threads/founding | head -c 200
curl -s http://localhost:8000/api/threads/founding/verify
```

Expected: list contains `founding`; detail is an array of envelopes; verify shows `"valid":true`.

- [ ] **Step 4: Verify the down-state**

Stop Terminal A (Ctrl+C), then:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/threads
curl -s http://localhost:8000/api/threads | grep -o threadhub_unreachable
```

Expected: `502` and `threadhub_unreachable`.

- [ ] **Step 5: Browser acceptance**

Restart Terminal A. Open `http://localhost:8000/threads`. Confirm: the list shows `founding` with a green `✓ chain valid · N records` badge; clicking it opens the detail with the record chain and a `✓ chain verified` header; the "← all threads" link returns to the list. Stop the sidecar and reload — confirm the "ThreadHub sidecar not running" message appears.

- [ ] **Step 6: Full test suite green**

Run: `cd ~/DevSwarmProjects/Clista && python3 -m pytest tests/ -v`
Expected: all tests pass (existing + the new Threads tests).

---

## Self-Review

**Spec coverage:**
- Sidecar on 8110 + launcher health-check → Task 5. ✓
- Three read-only proxy routes (`/api/threads`, `/api/threads/<slug>`, `/api/threads/<slug>/verify`) → Tasks 2–3. ✓
- Threads widget at `/threads`, list + lean detail, native UI → Task 4. ✓
- Nav link beside Registry → Task 4 Step 3c. ✓
- Error handling: unreachable → 502 (Task 2); malformed slug → 400 (Task 3); broken chain → ✗ badge (Task 4 widget + Task 6 Step 5); not-found passthrough (covered by `proxy_threadhub_get` HTTPError passthrough). ✓
- Testing: pytest proxy/slug tests (Tasks 1–4) + real-ThreadHub smoke & browser acceptance (Task 6). The spec's "real instance seeded with fixture" is realized in Task 6; the unit tests mock `urllib` to match the existing `MockHandler` convention (a deliberate operationalization, noted here). ✓
- Non-goals respected: no writes, no ClisTa projection, no registry/identity. ✓

**Placeholder scan:** No TBD/TODO. The widget's record-chain fetch URL has a clarifying implementer note (Task 4) to use `'/api/threads/' + encodeURIComponent(slug)` — that is explicit, not a placeholder.

**Type/name consistency:** `is_safe_slug`, `proxy_threadhub_get`, `handle_get_threads`, `handle_get_thread`, `handle_get_thread_verify`, and `THREADHUB_PORT` are used identically across tasks and tests. Proxy maps `/api/threads/<slug>` → `/t/<slug>.json` and `/api/threads/<slug>/verify` → `/t/<slug>/verify` consistently.
