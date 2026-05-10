# Fix Review Issues — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address all issues found in the code review of `lati-cooki/prompt-studio` master branch.

**Architecture:** All fixes apply directly to the existing files — `server.py` (Python HTTP server), `schema.sql`, and the `sandbox/js/` frontend modules. No new files are needed. Changes are grouped by file/layer to minimize context switching. Tests use Python's `unittest` for the server and Node.js `node:test` for the JS modules.

**Tech Stack:** Python 3 stdlib (`http.server`, `sqlite3`, `unittest`), Node.js `node:test` + `node:assert/strict`, vanilla JS (ESM).

---

## File Map

| File | Changes |
|---|---|
| `server.py` | Body size limit, input validation, DB connection safety, 404 on missing IDs |
| `schema.sql` | Index on `sessions.created_at`, `NOT NULL` on `prompts.created_at`/`updated_at` |
| `sandbox/js/sessions.js` | Remove dead `CAP`, remove `storage` param, null-guard `exportToRegistryDraft` |
| `sandbox/js/api.js` | Make `API_BASE` configurable |
| `sandbox/js/app.js` | Show error feedback on session save failure |
| `sandbox/js/sessions.test.js` | Add tests for `exportToRegistryDraft` |
| `.gitignore` | Already correct — `prompt_studio.db` is listed |
| `prompt_studio.db` | Remove from git tracking (`git rm --cached`) |

---

## Task 1: Setup — Branch from Master

**Files:**
- No file changes — git operations only

- [ ] **Step 1: Create a fix branch from origin/master**

```bash
git fetch origin
git checkout -b fix/review-issues origin/master
```

Expected: `Switched to a new branch 'fix/review-issues'`

- [ ] **Step 2: Remove prompt_studio.db from git tracking**

`.gitignore` on master already lists `prompt_studio.db`, but the file is still tracked. Remove it from the index without deleting it locally:

```bash
git rm --cached prompt_studio.db
```

Expected: `rm 'prompt_studio.db'`

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: stop tracking prompt_studio.db (already in .gitignore)"
```

---

## Task 2: server.py — Input Validation and Body Size Limit

**Files:**
- Modify: `server.py`

The current `read_json_body` reads whatever `Content-Length` says without an upper bound. `handle_post_sessions` crashes with `KeyError` on missing required fields.

- [ ] **Step 1: Add body size constant and update `read_json_body`**

Replace the existing `read_json_body` method with a version that enforces a size cap and returns `None` on malformed JSON:

```python
MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MB — add this at module level near PORT

# Replace the existing read_json_body method:
def read_json_body(self):
    try:
        content_length = int(self.headers.get('Content-Length', 0))
    except ValueError:
        return None
    if content_length > MAX_BODY_BYTES:
        self.send_error(413, "Request body too large")
        return None
    body = self.rfile.read(content_length)
    try:
        return json.loads(body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        self.send_error(400, "Invalid JSON")
        return None
```

- [ ] **Step 2: Guard all callers of `read_json_body` against `None`**

Add an early return in every handler that calls `read_json_body`:

`handle_post_sessions`:
```python
def handle_post_sessions(self):
    data = self.read_json_body()
    if data is None:
        return
    required = ("id", "name", "createdAt", "updatedAt", "panes", "vaultConfig")
    if not all(k in data for k in required):
        self.send_error(400, "Missing required fields")
        return
    conn = self.get_db()
    ...
```

`handle_post_prompts`:
```python
def handle_post_prompts(self):
    data = self.read_json_body()
    if data is None:
        return
    ...  # rest unchanged
```

`handle_put_session`:
```python
def handle_put_session(self, session_id):
    data = self.read_json_body()
    if data is None:
        return
    ...  # rest unchanged
```

`handle_put_prompt`:
```python
def handle_put_prompt(self, prompt_id):
    data = self.read_json_body()
    if data is None:
        return
    ...  # rest unchanged
```

- [ ] **Step 3: Commit**

```bash
git add server.py
git commit -m "fix: validate request body size and required fields in server.py"
```

---

## Task 3: server.py — DB Connection Safety

**Files:**
- Modify: `server.py`

If an exception fires between `get_db()` and `conn.close()`, the connection leaks. Wrap every handler with `try/finally`.

- [ ] **Step 1: Apply try/finally to every handler that opens a DB connection**

The pattern to apply everywhere:

```python
conn = self.get_db()
try:
    cursor = conn.cursor()
    # ... query logic ...
    conn.commit()  # only in write handlers
finally:
    conn.close()
```

Apply this to all eight handlers:
- `handle_get_sessions`
- `handle_post_sessions`
- `handle_put_session`
- `handle_delete_session`
- `handle_get_prompts`
- `handle_post_prompts`
- `handle_put_prompt`
- `handle_delete_prompt`

For read handlers (GET), omit `conn.commit()`. For write handlers (POST/PUT/DELETE), keep `conn.commit()` inside the try block.

Example for `handle_get_sessions`:
```python
def handle_get_sessions(self):
    conn = self.get_db()
    try:
        cursor = conn.cursor()
        query = """
            SELECT json_group_array(
                json_object(
                    'id', id,
                    'name', name,
                    'createdAt', created_at,
                    'updatedAt', updated_at,
                    'panes', json(panes),
                    'vaultConfig', json(vault_config)
                )
            ) FROM (SELECT * FROM sessions ORDER BY created_at DESC)
        """
        cursor.execute(query)
        result = cursor.fetchone()[0]
    finally:
        conn.close()
    self.send_raw_json(result if result else "[]")
```

Example for `handle_delete_session`:
```python
def handle_delete_session(self, session_id):
    conn = self.get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()
    self.send_json({"status": "success"})
```

- [ ] **Step 2: Commit**

```bash
git add server.py
git commit -m "fix: ensure DB connections are always closed via try/finally"
```

---

## Task 4: server.py — 404 for Missing Resources

**Files:**
- Modify: `server.py`

PUT/DELETE on a non-existent session or prompt currently returns `{"status": "success"}` with no rows affected.

- [ ] **Step 1: Check rowcount and return 404 in DELETE handlers**

In `handle_delete_session` and `handle_delete_prompt`, after the execute/commit, check `cursor.rowcount`:

```python
def handle_delete_session(self, session_id):
    conn = self.get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
        if cursor.rowcount == 0:
            self.send_error(404, "Session not found")
            return
    finally:
        conn.close()
    self.send_json({"status": "success"})

def handle_delete_prompt(self, prompt_id):
    conn = self.get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
        conn.commit()
        if cursor.rowcount == 0:
            self.send_error(404, "Prompt not found")
            return
    finally:
        conn.close()
    self.send_json({"status": "success"})
```

- [ ] **Step 2: Check rowcount and return 404 in PUT handlers**

In `handle_put_session` and `handle_put_prompt`, after the execute/commit when `fields` is non-empty:

```python
# inside handle_put_session, after cursor.execute and conn.commit():
if cursor.rowcount == 0:
    self.send_error(404, "Session not found")
    return

# inside handle_put_prompt, after cursor.execute and conn.commit():
if cursor.rowcount == 0:
    self.send_error(404, "Prompt not found")
    return
```

- [ ] **Step 3: Write basic server tests**

Create `tests/test_server.py`:

```python
import unittest
import json
import io
import sqlite3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import server

class FakeRequest:
    def __init__(self, method, path, body=b"", headers=None):
        self.method = method
        self.path = path
        self._body = body
        self._headers = headers or {}

class MockHandler(server.PromptStudioHandler):
    def __init__(self):
        self._responses = []
        self._headers_sent = []
        self._body_written = b""
        self.path = "/"

    def get_db(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "schema.sql")) as f:
            conn.executescript(f.read())
        return conn

    def send_response(self, code, message=None):
        self._last_status = code

    def send_header(self, key, val):
        pass

    def end_headers(self):
        pass

    def send_error(self, code, message=None):
        self._last_status = code

    @property
    def wfile(self):
        return self

    def write(self, data):
        self._body_written += data

    @property
    def headers(self):
        return self._mock_headers

    @property
    def rfile(self):
        return self._mock_rfile


class TestBodySizeLimit(unittest.TestCase):
    def _make_handler(self, body: bytes):
        h = MockHandler()
        h._mock_headers = {"Content-Length": str(len(body))}
        h._mock_rfile = io.BytesIO(body)
        return h

    def test_rejects_oversized_body(self):
        h = self._make_handler(b"x" * (server.MAX_BODY_BYTES + 1))
        h._mock_headers = {"Content-Length": str(server.MAX_BODY_BYTES + 1)}
        result = h.read_json_body()
        self.assertIsNone(result)
        self.assertEqual(h._last_status, 413)

    def test_rejects_malformed_json(self):
        body = b"{not json"
        h = self._make_handler(body)
        result = h.read_json_body()
        self.assertIsNone(result)
        self.assertEqual(h._last_status, 400)

    def test_parses_valid_json(self):
        body = json.dumps({"key": "val"}).encode()
        h = self._make_handler(body)
        result = h.read_json_body()
        self.assertEqual(result, {"key": "val"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run the tests**

```bash
python -m pytest tests/test_server.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "fix: return 404 for PUT/DELETE on non-existent resources; add server tests"
```

---

## Task 5: schema.sql — Index and NOT NULL Consistency

**Files:**
- Modify: `schema.sql`

- [ ] **Step 1: Add index on `sessions.created_at` and fix prompt NOT NULL**

Replace the `prompts` table definition and add the index. The full updated `schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    panes TEXT NOT NULL,
    vault_config TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions (created_at DESC);

CREATE TABLE IF NOT EXISTS prompts (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    status TEXT,
    tier TEXT,
    owner TEXT,
    body TEXT,
    use_case TEXT,
    cost_per_run_usd REAL,
    tokens_prompt_body INTEGER,
    default_model TEXT,
    eval_status TEXT,
    file TEXT,
    notes TEXT,
    composes TEXT,
    tested_on TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evals (
    id TEXT PRIMARY KEY,
    directive TEXT,
    date TEXT,
    prompt_under_test TEXT,
    headline_finding TEXT,
    file TEXT,
    data_file TEXT,
    models_tested TEXT
);
```

Note: The `CREATE INDEX IF NOT EXISTS` only applies to new databases. Existing `prompt_studio.db` is now untracked, so this is fine.

- [ ] **Step 2: Commit**

```bash
git add schema.sql
git commit -m "fix: add index on sessions.created_at; add NOT NULL to prompts timestamps"
```

---

## Task 6: sandbox/js/sessions.js — Dead Code, Storage Param, Null Guard

**Files:**
- Modify: `sandbox/js/sessions.js`
- Modify: `sandbox/js/sessions.test.js`

- [ ] **Step 1: Remove `CAP` constant and `storage` parameter**

In `sessions.js`, remove the `const CAP = 100;` line and the `storage` parameter from `createSessionsStore`:

```js
// Before:
export function createSessionsStore(storage) {
  // `storage` parameter is ignored now since we use the API,
  // but kept for signature compatibility with test fakes if needed.

// After:
export function createSessionsStore() {
```

Also remove the `CAP = 100` line entirely.

- [ ] **Step 2: Add null guard to `exportToRegistryDraft`**

```js
// Before:
export function exportToRegistryDraft(session) {
  const primaryPane = session.panes[0];

// After:
export function exportToRegistryDraft(session) {
  if (!session?.panes?.length) {
    throw new Error("exportToRegistryDraft: session has no panes");
  }
  const primaryPane = session.panes[0];
```

- [ ] **Step 3: Write tests for `exportToRegistryDraft`**

Add to `sandbox/js/sessions.test.js` (after the existing `resolveModelKey` tests):

```js
import { exportToRegistryDraft } from "./sessions.js";

const sampleSession = {
  name: "My Test Prompt",
  panes: [
    {
      systemPrompt: "You are a helpful assistant.",
      messages: [{ role: "system", content: "You are a helpful assistant." }],
      modelKey: "gemma-4-26b",
    },
  ],
};

test("exportToRegistryDraft: throws on session with no panes", () => {
  assert.throws(
    () => exportToRegistryDraft({ name: "empty", panes: [] }),
    /no panes/,
  );
});

test("exportToRegistryDraft: throws on null session", () => {
  assert.throws(
    () => exportToRegistryDraft(null),
    /no panes/,
  );
});

test("exportToRegistryDraft: returns draft with id derived from name", () => {
  const draft = exportToRegistryDraft(sampleSession);
  assert.equal(draft.id, "my_test_prompt");
  assert.equal(draft.status, "draft");
  assert.equal(draft.body, "You are a helpful assistant.");
  assert.equal(draft.default_model, "gemma-4-26b");
});

test("exportToRegistryDraft: name with special chars slugifies cleanly", () => {
  const draft = exportToRegistryDraft({ ...sampleSession, name: "  Hello World!!  " });
  assert.equal(draft.id, "hello_world");
});

test("exportToRegistryDraft: empty name falls back to 'draft'", () => {
  const draft = exportToRegistryDraft({ ...sampleSession, name: "" });
  assert.equal(draft.id, "draft");
});
```

- [ ] **Step 4: Run the tests**

```bash
cd sandbox && node --test js/sessions.test.js
```

Expected: All non-skipped tests pass (including the new `exportToRegistryDraft` tests).

- [ ] **Step 5: Update the call site in `app.js` to remove the `localStorage` argument**

In `app.js`, find:
```js
const sessionsStore = createSessionsStore(localStorage);
```
Change to:
```js
const sessionsStore = createSessionsStore();
```

- [ ] **Step 6: Commit**

```bash
git add sandbox/js/sessions.js sandbox/js/sessions.test.js sandbox/js/app.js
git commit -m "fix: remove dead CAP constant and storage param; null-guard exportToRegistryDraft; add tests"
```

---

## Task 7: sandbox/js/api.js — Configurable API Base URL

**Files:**
- Modify: `sandbox/js/api.js`

- [ ] **Step 1: Read from a global config before falling back to localhost**

Replace the hardcoded constant with a function that checks `window.PROMPT_STUDIO_API_BASE` if available:

```js
function getApiBase() {
  if (typeof window !== "undefined" && window.PROMPT_STUDIO_API_BASE) {
    return window.PROMPT_STUDIO_API_BASE;
  }
  return "http://localhost:8000/api";
}
```

Then replace every use of `API_BASE` in the file with `getApiBase()`. For example:

```js
// Before:
const API_BASE = "http://localhost:8000/api";

export async function fetchSessions() {
  const res = await fetch(`${API_BASE}/sessions`);

// After:
function getApiBase() {
  if (typeof window !== "undefined" && window.PROMPT_STUDIO_API_BASE) {
    return window.PROMPT_STUDIO_API_BASE;
  }
  return "http://localhost:8000/api";
}

export async function fetchSessions() {
  const res = await fetch(`${getApiBase()}/sessions`);
```

Apply the same substitution to `saveSession`, `renameSession`, and `deleteSession`.

- [ ] **Step 2: Commit**

```bash
git add sandbox/js/api.js
git commit -m "fix: make API base URL configurable via window.PROMPT_STUDIO_API_BASE"
```

---

## Task 8: sandbox/js/app.js — Save Failure Feedback

**Files:**
- Modify: `sandbox/js/app.js`

Currently when a session save fails, the error is swallowed silently.

- [ ] **Step 1: Surface save errors in the UI**

In `app.js`, find the `renderSaveSlot` block and its `onSave` handler. Wrap the `sessionsStore.save` call to show an error in the vault status element (reusing the existing status pattern):

```js
renderSaveSlot(document.getElementById("sessions-save-slot"), {
  defaultName: autoName,
  onSave: async (name) => {
    try {
      const { panes, vaultConfig } = currentSnapshot();
      const entry = await sessionsStore.save({ name, panes, vaultConfig });
      activeSessionId = entry.id;
      refreshSessionList();
    } catch (err) {
      $vaultStatus.textContent = `Save failed: ${err.message}`;
      setTimeout(() => { $vaultStatus.textContent = ""; }, 6000);
    }
  },
});
```

- [ ] **Step 2: Commit**

```bash
git add sandbox/js/app.js
git commit -m "fix: show error message in UI when session save fails"
```

---

## Task 9: Push and Open PR

- [ ] **Step 1: Verify all tests pass**

```bash
cd sandbox && node --test js/sessions.test.js js/state.test.js js/stream.test.js js/tokens.test.js
python -m pytest tests/ -v
```

Expected: All non-skipped tests pass.

- [ ] **Step 2: Push the branch**

```bash
git push -u origin fix/review-issues
```

- [ ] **Step 3: Open PR**

```bash
gh pr create \
  --title "fix: address all code review issues" \
  --body "$(cat <<'EOF'
## Summary

- Removes `prompt_studio.db` from git tracking (already in `.gitignore`)
- Adds 10 MB body size limit and malformed JSON handling to `server.py`
- Validates required fields in `handle_post_sessions`
- Wraps all DB connections in `try/finally` to prevent leaks
- Returns 404 for PUT/DELETE on non-existent resources
- Adds index on `sessions.created_at` and fixes `NOT NULL` consistency in `schema.sql`
- Removes dead `CAP = 100` and unused `storage` parameter from `sessions.js`
- Adds null guard to `exportToRegistryDraft` with tests
- Makes API base URL configurable via `window.PROMPT_STUDIO_API_BASE`
- Shows error feedback in UI when session save fails

## Test plan

- [ ] `node --test sandbox/js/sessions.test.js` — new exportToRegistryDraft tests pass
- [ ] `python -m pytest tests/test_server.py -v` — body size/validation tests pass
- [ ] Manual: start server, send oversized body → 413
- [ ] Manual: DELETE non-existent session → 404
- [ ] Manual: PUT non-existent session → 404
- [ ] Manual: fail a session save (stop server) → error message appears in vault status area

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
