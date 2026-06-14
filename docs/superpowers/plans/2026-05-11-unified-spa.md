# Unified Prompt Studio SPA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild Prompt Studio as a single-page app where the full eval loop — pick a registry prompt, run it as system prompt against N local and frontier models with a directive, save session, update registry — lives in one UI with no page switching.

**Architecture:** Left rail holds the registry prompt picker, model checklist (local + frontier), and session list. The main area dynamically creates one pane per active model. A right-hand registry panel shows active prompt metadata and exposes "Save as draft" / "Mark eval validated" actions. The composer input is relabeled "Directive" and sends to all active panes. Frontier model requests proxy through a new `POST /api/chat` server endpoint that translates to the Anthropic streaming API. Registry view is embedded as an iframe tab. All 79 existing tests must remain green throughout.

**Tech Stack:** Python stdlib http.server, SQLite, vanilla JS ESM, Anthropic Python SDK (streaming), existing Consensus Protocol CSS

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `schema.sql` | Add composite PK `(id, version)` to prompts |
| Modify | `server.py` | Schema migration + `POST /api/chat` + draft/validate endpoints |
| Create | `tests/test_chat_proxy.py` | Server tests for `/api/chat` + draft/validate |
| Modify | `sandbox/js/config.js` | Add `FRONTIER_MODELS`, export `ALL_MODELS` |
| Modify | `sandbox/js/api.js` | Add `saveDraftPrompt`, `validatePrompt` |
| Modify | `sandbox/js/pane.js` | Remove registry dropdown, add `getSystemPrompt()`, `setSystemPrompt()` |
| Create | `sandbox/js/model-selector.js` | Model checklist component (local + frontier groups) |
| Create | `sandbox/js/model-selector.test.js` | Unit tests for model selector state logic |
| Create | `sandbox/js/registry-panel.js` | Right-panel component (prompt metadata + actions) |
| Modify | `sandbox/js/sessions.js` | New save format with `promptRef` + `models`; legacy load compat |
| Modify | `sandbox/index.html` | Unified SPA layout: prompt picker, model checklist, registry panel, directive composer, registry iframe tab |
| Modify | `sandbox/js/app.js` | Full rewrite — wire all components into unified SPA |
| Modify | `registry/interface/registry_widget.html` | Add "Open in Eval →" postMessage button per row |

---

## Task 1: Schema — prompts composite primary key

**Files:**
- Modify: `schema.sql`
- Modify: `server.py` (add `migrate_db()`, call in `init_db()`)
- Create: `tests/test_chat_proxy.py` (baseline, expanded in Task 2)

The prompts table currently uses `id TEXT PRIMARY KEY` which allows only one row per prompt. We need `PRIMARY KEY (id, version)` for multi-version support. SQLite cannot alter a primary key, so we recreate the table.

- [ ] **Step 1: Update schema.sql**

Replace the prompts table definition:

```sql
-- schema.sql (prompts table only — sessions and evals unchanged)
CREATE TABLE IF NOT EXISTS prompts (
    id TEXT NOT NULL,
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
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (id, version)
);
```

- [ ] **Step 2: Add `migrate_db()` to server.py**

Add this function and call it from `init_db()`:

```python
def migrate_db(conn):
    """Migrate prompts table to composite (id, version) primary key if needed."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='prompts'"
    )
    row = cursor.fetchone()
    if not row:
        return  # table doesn't exist yet; schema.sql will create it
    if 'PRIMARY KEY (id, version)' in row[0]:
        return  # already migrated
    # Recreate table with composite PK
    cursor.executescript("""
        CREATE TABLE prompts_new (
            id TEXT NOT NULL,
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
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            PRIMARY KEY (id, version)
        );
        INSERT INTO prompts_new SELECT * FROM prompts;
        DROP TABLE prompts;
        ALTER TABLE prompts_new RENAME TO prompts;
    """)
    conn.commit()
```

Find `init_db()` in server.py (it was added in a recent commit). Call `migrate_db(conn)` just before `conn.executescript(schema)`:

```python
def init_db():
    conn = get_db()   # get_db() is the class method — at module level use sqlite3.connect directly
    # ... existing init_db code ...
    migrate_db(conn)
    # ... rest of init ...
```

Note: `init_db()` is currently a standalone function. Find it in server.py and add the `migrate_db(conn)` call after opening the connection and before applying the schema.

- [ ] **Step 3: Update `handle_put_prompt` to match by (id, version)**

Find `handle_put_prompt` in server.py. The WHERE clause currently uses only `id`. Change it to use both `id` and `version` (version comes from the request body):

```python
def handle_put_prompt(self, prompt_id):
    data = self.read_json_body()
    if data is None:
        return
    version = data.get('version')
    if not version:
        self.send_error(400, "version required")
        return
    conn = self.get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE prompts SET
               status=?, tier=?, owner=?, body=?, use_case=?,
               cost_per_run_usd=?, tokens_prompt_body=?, default_model=?,
               eval_status=?, file=?, notes=?, composes=?, tested_on=?,
               updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
               WHERE id=? AND version=?""",
            (
                data.get('status'), data.get('tier'), data.get('owner'),
                data.get('body'), data.get('use_case'),
                data.get('cost_per_run_usd'), data.get('tokens_prompt_body'),
                data.get('default_model'), data.get('eval_status'),
                data.get('file'), data.get('notes'),
                data.get('composes'), data.get('tested_on'),
                prompt_id, version,
            )
        )
        conn.commit()
        if cursor.rowcount == 0:
            self.send_error(404, "Prompt not found")
            return
    finally:
        conn.close()
    self.send_json({"status": "success"})
```

- [ ] **Step 4: Run existing tests to confirm nothing broke**

```bash
cd /Users/troylatimer/prompt-studio
python3 -m pytest tests/ -v
```

Expected: 35 passed.

- [ ] **Step 5: Commit**

```bash
git add schema.sql server.py
git commit -m "feat: migrate prompts table to composite (id, version) primary key"
```

---

## Task 2: Server — `POST /api/chat` frontier proxy

**Files:**
- Modify: `server.py`
- Create: `tests/test_chat_proxy.py`

Frontier model requests arrive at `POST /api/chat` with `{model, messages, stream}` (same OpenAI format as local requests). The server extracts any system message, calls the Anthropic streaming API, and re-emits SSE in OpenAI format so the existing `stream.js` parser works unchanged.

- [ ] **Step 1: Write failing tests**

Create `tests/test_chat_proxy.py`:

```python
import json
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _make_handler():
    """Return a PromptStudioHandler instance with a stubbed socket."""
    import server
    handler = object.__new__(server.PromptStudioHandler)
    handler.wfile = MagicMock()
    handler.rfile = MagicMock()
    handler.headers = {}
    return handler


class TestPostChat(unittest.TestCase):
    def test_missing_api_key_returns_503(self):
        handler = _make_handler()
        handler.read_json_body = lambda: {"model": "claude-sonnet-4-6", "messages": [], "stream": True}
        handler.send_error = MagicMock()

        with patch.dict(os.environ, {}, clear=True):
            if "ANTHROPIC_API_KEY" in os.environ:
                del os.environ["ANTHROPIC_API_KEY"]
            handler.handle_post_chat()

        handler.send_error.assert_called_once()
        args = handler.send_error.call_args[0]
        self.assertEqual(args[0], 503)

    def test_invalid_body_returns_early(self):
        handler = _make_handler()
        handler.read_json_body = lambda: None  # simulates parse failure
        handler.send_error = MagicMock()

        handler.handle_post_chat()

        handler.send_error.assert_not_called()  # read_json_body already sent the error

    def test_streams_content_as_openai_sse(self):
        handler = _make_handler()
        handler.read_json_body = lambda: {
            "model": "claude-sonnet-4-6",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hello"},
            ],
            "stream": True,
        }
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=False)
        mock_stream.text_stream = iter(["Hello", " world"])
        mock_final = MagicMock()
        mock_final.usage.input_tokens = 10
        mock_final.usage.output_tokens = 5
        mock_stream.get_final_message = MagicMock(return_value=mock_final)

        mock_client = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=mock_stream)

        written = []
        handler.wfile.write = lambda b: written.append(b)
        handler.wfile.flush = MagicMock()

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("server.anthropic") as mock_anthropic:
                mock_anthropic.Anthropic = MagicMock(return_value=mock_client)
                handler.handle_post_chat()

        # First two writes should be content chunks
        chunk0 = json.loads(written[0].decode().removeprefix("data: ").strip())
        self.assertEqual(chunk0["choices"][0]["delta"]["content"], "Hello")
        chunk1 = json.loads(written[1].decode().removeprefix("data: ").strip())
        self.assertEqual(chunk1["choices"][0]["delta"]["content"], " world")
        # Last write should be [DONE]
        self.assertIn(b"[DONE]", written[-1])
```

- [ ] **Step 2: Run to confirm failures**

```bash
python3 -m pytest tests/test_chat_proxy.py -v
```

Expected: 3 failures (handler has no `handle_post_chat` method yet).

- [ ] **Step 3: Add `import anthropic` and `handle_post_chat` to server.py**

At the top of server.py, after existing imports, add:

```python
try:
    import anthropic
except ImportError:
    anthropic = None
```

Add `handle_post_chat` as a method of `PromptStudioHandler`:

```python
def handle_post_chat(self):
    data = self.read_json_body()
    if data is None:
        return
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        self.send_error(503, "ANTHROPIC_API_KEY not configured")
        return
    if anthropic is None:
        self.send_error(503, "anthropic package not installed")
        return

    model_id = data.get('model', '')
    messages = data.get('messages', [])
    system_msgs = [m for m in messages if m.get('role') == 'system']
    user_msgs   = [m for m in messages if m.get('role') != 'system']
    system = system_msgs[0]['content'] if system_msgs else ''

    client = anthropic.Anthropic(api_key=api_key)
    self.send_response(200)
    self.send_header('Content-Type', 'text/event-stream')
    self.send_header('Cache-Control', 'no-cache')
    self.end_headers()

    try:
        with client.messages.stream(
            model=model_id,
            max_tokens=8096,
            system=system,
            messages=user_msgs,
        ) as stream:
            for text in stream.text_stream:
                chunk = json.dumps({"choices": [{"delta": {"content": text}}]})
                self.wfile.write(f"data: {chunk}\n\n".encode())
                self.wfile.flush()
            msg = stream.get_final_message()
            usage_chunk = json.dumps({
                "choices": [{"delta": {}}],
                "usage": {
                    "prompt_tokens": msg.usage.input_tokens,
                    "completion_tokens": msg.usage.output_tokens,
                }
            })
            self.wfile.write(f"data: {usage_chunk}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
    except Exception as err:
        error_chunk = json.dumps({"error": str(err)})
        self.wfile.write(f"data: {error_chunk}\n\n".encode())
        self.wfile.flush()
```

Wire it into `do_POST` by adding before the final `else: self.send_error(404)`:

```python
elif self.path == '/api/chat':
    self.handle_post_chat()
```

- [ ] **Step 4: Run all tests**

```bash
python3 -m pytest tests/ -v
```

Expected: 38 passed (35 existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_chat_proxy.py
git commit -m "feat: add POST /api/chat frontier model proxy with Anthropic streaming"
```

---

## Task 3: Server — prompt draft and validate endpoints

**Files:**
- Modify: `server.py`
- Modify: `tests/test_chat_proxy.py` (add draft/validate tests)

- [ ] **Step 1: Write failing tests — add to `tests/test_chat_proxy.py`**

Append these test classes:

```python
class TestPromptDraft(unittest.TestCase):
    def _make_db(self):
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE prompts (
                id TEXT NOT NULL, version TEXT NOT NULL,
                status TEXT, tier TEXT, owner TEXT, body TEXT,
                use_case TEXT, cost_per_run_usd REAL,
                tokens_prompt_body INTEGER, default_model TEXT,
                eval_status TEXT, file TEXT, notes TEXT,
                composes TEXT, tested_on TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                PRIMARY KEY (id, version)
            );
            INSERT INTO prompts VALUES (
                'my_prompt','1.0.0','production',NULL,NULL,'body text',
                NULL,NULL,NULL,NULL,'validated',NULL,NULL,NULL,NULL,
                strftime('%Y-%m-%dT%H:%M:%SZ','now'),
                strftime('%Y-%m-%dT%H:%M:%SZ','now')
            );
        """)
        return conn

    def test_draft_increments_minor_version(self):
        import server
        handler = object.__new__(server.PromptStudioHandler)
        handler.send_json = MagicMock()
        handler.send_error = MagicMock()
        handler.read_json_body = lambda: {"body": "new body text"}
        handler.get_db = lambda: self._make_db()

        handler.handle_post_prompt_draft("my_prompt")

        handler.send_json.assert_called_once()
        result = handler.send_json.call_args[0][0]
        self.assertEqual(result["version"], "1.1.0")
        self.assertEqual(result["status"], "draft")

    def test_draft_starts_at_1_0_0_for_new_id(self):
        import server
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE prompts (
                id TEXT NOT NULL, version TEXT NOT NULL,
                status TEXT, tier TEXT, owner TEXT, body TEXT,
                use_case TEXT, cost_per_run_usd REAL,
                tokens_prompt_body INTEGER, default_model TEXT,
                eval_status TEXT, file TEXT, notes TEXT,
                composes TEXT, tested_on TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                PRIMARY KEY (id, version)
            );
        """)
        handler = object.__new__(server.PromptStudioHandler)
        handler.send_json = MagicMock()
        handler.send_error = MagicMock()
        handler.read_json_body = lambda: {"body": "brand new prompt"}
        handler.get_db = lambda: conn

        handler.handle_post_prompt_draft("brand_new")

        result = handler.send_json.call_args[0][0]
        self.assertEqual(result["version"], "1.0.0")


class TestPromptValidate(unittest.TestCase):
    def _make_db_with_draft(self):
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE prompts (
                id TEXT NOT NULL, version TEXT NOT NULL,
                status TEXT, tier TEXT, owner TEXT, body TEXT,
                use_case TEXT, cost_per_run_usd REAL,
                tokens_prompt_body INTEGER, default_model TEXT,
                eval_status TEXT, file TEXT, notes TEXT,
                composes TEXT, tested_on TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                PRIMARY KEY (id, version)
            );
            INSERT INTO prompts VALUES (
                'my_prompt','1.1.0','draft',NULL,NULL,'body',
                NULL,NULL,NULL,NULL,'pending',NULL,NULL,NULL,NULL,
                strftime('%Y-%m-%dT%H:%M:%SZ','now'),
                strftime('%Y-%m-%dT%H:%M:%SZ','now')
            );
        """)
        return conn

    def test_validate_sets_production_and_validated(self):
        import server
        handler = object.__new__(server.PromptStudioHandler)
        handler.send_json = MagicMock()
        handler.send_error = MagicMock()
        conn = self._make_db_with_draft()
        handler.get_db = lambda: conn

        handler.handle_post_prompt_validate("my_prompt", "1.1.0")

        row = conn.execute(
            "SELECT status, eval_status FROM prompts WHERE id='my_prompt' AND version='1.1.0'"
        ).fetchone()
        self.assertEqual(row["status"], "production")
        self.assertEqual(row["eval_status"], "validated")

    def test_validate_404_for_missing(self):
        import server
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE prompts (
                id TEXT NOT NULL, version TEXT NOT NULL,
                status TEXT, tier TEXT, owner TEXT, body TEXT,
                use_case TEXT, cost_per_run_usd REAL,
                tokens_prompt_body INTEGER, default_model TEXT,
                eval_status TEXT, file TEXT, notes TEXT,
                composes TEXT, tested_on TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                PRIMARY KEY (id, version)
            );
        """)
        handler = object.__new__(server.PromptStudioHandler)
        handler.send_json = MagicMock()
        handler.send_error = MagicMock()
        handler.get_db = lambda: conn

        handler.handle_post_prompt_validate("ghost", "1.0.0")

        handler.send_error.assert_called_once()
        self.assertEqual(handler.send_error.call_args[0][0], 404)
```

- [ ] **Step 2: Run to confirm failures**

```bash
python3 -m pytest tests/test_chat_proxy.py::TestPromptDraft tests/test_chat_proxy.py::TestPromptValidate -v
```

Expected: 4 failures.

- [ ] **Step 3: Implement `handle_post_prompt_draft` in server.py**

Add as a method of `PromptStudioHandler`:

```python
def handle_post_prompt_draft(self, prompt_id):
    data = self.read_json_body()
    if data is None:
        return
    body = data.get('body', '')
    conn = self.get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT version FROM prompts WHERE id=? ORDER BY version DESC",
            (prompt_id,)
        )
        rows = cursor.fetchall()
        if rows:
            parts = rows[0][0].split('.')
            new_version = f"{parts[0]}.{int(parts[1]) + 1}.0"
        else:
            new_version = "1.0.0"
        cursor.execute(
            """INSERT INTO prompts (id, version, status, body,
               created_at, updated_at)
               VALUES (?, ?, 'draft', ?,
               strftime('%Y-%m-%dT%H:%M:%SZ','now'),
               strftime('%Y-%m-%dT%H:%M:%SZ','now'))
               ON CONFLICT(id, version) DO UPDATE SET
               body=excluded.body,
               updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')""",
            (prompt_id, new_version, body)
        )
        conn.commit()
    finally:
        conn.close()
    self.send_json({"status": "draft", "id": prompt_id, "version": new_version})
```

Add `handle_post_prompt_validate`:

```python
def handle_post_prompt_validate(self, prompt_id, version):
    conn = self.get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE prompts SET status='production', eval_status='validated',
               updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
               WHERE id=? AND version=?""",
            (prompt_id, version)
        )
        conn.commit()
        if cursor.rowcount == 0:
            self.send_error(404, "Prompt not found")
            return
    finally:
        conn.close()
    self.send_json({"status": "validated", "id": prompt_id, "version": version})
```

Wire both into `do_POST`. Add these routes (path patterns like `/api/prompts/my_id/draft` and `/api/prompts/my_id/1.1.0/validate`):

```python
elif self.path.startswith('/api/prompts/'):
    parts = self.path.removeprefix('/api/prompts/').split('/')
    if len(parts) == 2 and parts[1] == 'draft':
        self.handle_post_prompt_draft(parts[0])
    elif len(parts) == 3 and parts[2] == 'validate':
        self.handle_post_prompt_validate(parts[0], parts[1])
    else:
        self.send_error(404)
```

Place this before the existing `/api/prompts` POST route so it takes priority.

- [ ] **Step 4: Run all tests**

```bash
python3 -m pytest tests/ -v
```

Expected: 42 passed.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_chat_proxy.py
git commit -m "feat: add POST /api/prompts/:id/draft and /:id/:version/validate endpoints"
```

---

## Task 4: Config — frontier models + api.js helpers

**Files:**
- Modify: `sandbox/js/config.js`
- Modify: `sandbox/js/api.js`

- [ ] **Step 1: Update config.js**

Replace the entire file:

```js
export const MODELS = {
  "gemma-4-26b": {
    id:            "mlx-community/gemma-4-26B-A4B-it-4bit",
    endpoint:      "http://localhost:8080/v1/chat/completions",
    contextWindow: 128000,
    group:         "local",
  },
  "qwen3-4b": {
    id:            "mlx-community/Qwen3-4B-Instruct-2507-4bit",
    endpoint:      "http://localhost:8091/v1/chat/completions",
    contextWindow: 262144,
    group:         "local",
  },
  "qwen3-27b": {
    id:            "Jackrong/MLX-Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2-4bit",
    endpoint:      "http://localhost:8092/v1/chat/completions",
    contextWindow: 262144,
    group:         "local",
  },
};

export const FRONTIER_MODELS = {
  "claude-haiku-4-5": {
    id:            "claude-haiku-4-5-20251001",
    endpoint:      "/api/chat",
    contextWindow: 200000,
    group:         "frontier",
  },
  "claude-sonnet-4-6": {
    id:            "claude-sonnet-4-6",
    endpoint:      "/api/chat",
    contextWindow: 200000,
    group:         "frontier",
  },
};

export const ALL_MODELS = { ...MODELS, ...FRONTIER_MODELS };

export const DEFAULT_MODEL_KEY = "qwen3-4b";

export function getActiveModelKey() {
  try {
    const saved = localStorage.getItem("promptSandbox.modelKey");
    if (saved && Object.prototype.hasOwnProperty.call(ALL_MODELS, saved)) {
      return saved;
    }
    return DEFAULT_MODEL_KEY;
  } catch {
    return DEFAULT_MODEL_KEY;
  }
}

export const VAULT_URL   = "http://localhost:8100";
export const STORAGE_KEY = "promptSandbox.sessions";

export const DEFAULT_SYSTEM_PROMPT = `Role: You are my Lead Strategic Advisor and Decision Scientist.
Objective: Help me reach better conclusions by identifying my blind spots and logical fallacies.
Protocol:
Steel-manning: Before critiquing, summarize my argument back to me to prove you understand it perfectly.
Pre-Mortem: If I propose a plan, tell me three specific ways it could realistically fail in 12 months.
Inversion: Ask me, "What would I have to do to ensure this project fails?" to help me avoid those pitfalls.
Occam's Razor: Challenge me to find the simplest possible version of my idea.
Second-Order Effects: Always ask "And then what?" to explore the long-term consequences of my choice.
Tone: Brutally honest, intellectually rigorous, and concise. No fluff.`;
```

- [ ] **Step 2: Add `saveDraftPrompt` and `validatePrompt` to api.js**

Append to `sandbox/js/api.js`:

```js
export async function saveDraftPrompt(id, body) {
  const res = await fetch(`${getApiBase()}/prompts/${id}/draft`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body }),
  });
  if (!res.ok) throw new Error("Failed to save draft");
  return res.json();
}

export async function validatePrompt(id, version) {
  const res = await fetch(`${getApiBase()}/prompts/${id}/${version}/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!res.ok) throw new Error("Failed to validate prompt");
  return res.json();
}
```

- [ ] **Step 3: Run all tests**

```bash
python3 -m pytest tests/ -v && node --test sandbox/js/*.test.js
```

Expected: 42 Python passed, 44 JS passed (11 skipped).

- [ ] **Step 4: Commit**

```bash
git add sandbox/js/config.js sandbox/js/api.js
git commit -m "feat: add frontier models to config; add saveDraftPrompt/validatePrompt to api.js"
```

---

## Task 5: pane.js — simplify for unified SPA

**Files:**
- Modify: `sandbox/js/pane.js`

Remove the registry dropdown (now the left rail prompt picker handles this). Keep the system prompt textarea editable (users iterate on prompt text, then save as draft via registry panel). Add `getSystemPrompt()` and `setSystemPrompt(body)` to the public API. Remove `setRegistryPrompts()` and the associated dropdown DOM.

- [ ] **Step 1: Rewrite `createPane` signature and remove dropdown**

Replace the current `createPane` function with this version. Keep all existing behavior (textarea, apply/reset, model select, meter slot, bubble log) — only remove the registry dropdown block and add two new API methods:

```js
function oneLinePreview(text) {
  const firstLine = text.split("\n", 1)[0].trim();
  if (firstLine.length <= 80) return firstLine || "(empty prompt)";
  return firstLine.slice(0, 77) + "…";
}

export function createPane({ id, container, initialPrompt = "", modelKeys = [], initialModelKey = null }) {
  const section = document.createElement("section");
  section.className      = "pane";
  section.dataset.paneId = id;

  const header = document.createElement("header");
  header.className = "pane-prompt";

  const labelRow = document.createElement("div");
  labelRow.className = "pane-label-row";

  const promptLabel = document.createElement("span");
  promptLabel.className   = "pane-prompt-label";
  promptLabel.textContent = "SYSTEM PROMPT";
  labelRow.appendChild(promptLabel);

  const metaRow = document.createElement("div");
  metaRow.className = "pane-meta-row";

  const badge = document.createElement("span");
  badge.className   = "pane-badge";
  badge.textContent = id;

  const modelSelect = document.createElement("select");
  modelSelect.className = "pane-model-select";
  for (const key of modelKeys) {
    const opt = document.createElement("option");
    opt.value       = key;
    opt.textContent = key;
    if (key === initialModelKey) opt.selected = true;
    modelSelect.appendChild(opt);
  }

  const metaSpacer = document.createElement("span");
  metaSpacer.className = "pane-meta-spacer";

  metaRow.appendChild(badge);
  metaRow.appendChild(modelSelect);
  metaRow.appendChild(metaSpacer);

  const promptBody = document.createElement("div");
  promptBody.className = "pane-prompt-body";

  const promptGt = document.createElement("span");
  promptGt.className   = "pane-prompt-gt";
  promptGt.textContent = "> ";

  const promptPreviewText = document.createElement("span");
  promptPreviewText.textContent = oneLinePreview(initialPrompt);

  promptBody.appendChild(promptGt);
  promptBody.appendChild(promptPreviewText);

  const expandedArea = document.createElement("div");
  expandedArea.className = "pane-prompt-expanded";
  expandedArea.hidden    = true;

  const textarea = document.createElement("textarea");
  textarea.className  = "pane-prompt-textarea";
  textarea.spellcheck = false;
  textarea.value      = initialPrompt;

  const applyReset = document.createElement("button");
  applyReset.className   = "pane-apply-reset";
  applyReset.textContent = "Apply & Reset";

  expandedArea.appendChild(textarea);
  expandedArea.appendChild(applyReset);

  const hint = document.createElement("div");
  hint.className = "pane-prompt-hint";
  hint.textContent = "click to collapse · ⌘↵ to apply & reset";

  header.appendChild(labelRow);
  header.appendChild(metaRow);
  header.appendChild(promptBody);
  header.appendChild(expandedArea);
  header.appendChild(hint);

  function enterEditing() {
    header.classList.remove("collapsed");
    header.classList.add("editing");
    expandedArea.hidden = false;
    hint.textContent = "⌘↵ to apply & reset";
    textarea.focus();
  }

  function exitEditing() {
    header.classList.remove("editing");
    expandedArea.hidden = true;
    hint.textContent = "click to collapse · ⌘↵ to apply & reset";
  }

  function toggleCollapsed() {
    if (header.classList.contains("editing")) {
      exitEditing();
    } else {
      header.classList.toggle("collapsed");
    }
  }

  promptBody.addEventListener("click", enterEditing);
  labelRow.addEventListener("click", toggleCollapsed);

  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      applyReset.click();
    }
    if (e.key === "Escape") {
      e.preventDefault();
      exitEditing();
    }
  });

  applyReset.addEventListener("click", exitEditing);

  const log = document.createElement("main");
  log.className = "pane-log";

  const emptyState = document.createElement("div");
  emptyState.className = "empty-state";
  emptyState.innerHTML = `
    <div class="empty-state-inner">
      <div class="empty-tag">— New conversation —</div>
      <div class="empty-hero">A quiet place to<br>iterate on your prompt.</div>
      <div class="empty-body">
        Write a directive below to start, or edit the system prompt above.
      </div>
      <div class="empty-shortcuts">
        <span class="kbd-chip">⌘↵ send</span>
        <span class="kbd-chip">⌘K sessions</span>
      </div>
    </div>
  `;
  log.appendChild(emptyState);

  section.appendChild(header);
  section.appendChild(log);
  container.appendChild(section);

  const refreshPreview = () => {
    promptPreviewText.textContent = oneLinePreview(textarea.value);
  };

  function addBubble(role, text = "") {
    if (emptyState.parentNode === log) log.removeChild(emptyState);
    const wrap = document.createElement("div");
    wrap.className = "bubble-wrap " + role;
    const tag = document.createElement("div");
    tag.className   = "bubble-role";
    tag.textContent = role === "user" ? "directive" : "assistant";
    wrap.appendChild(tag);
    const el = document.createElement("div");
    el.className  = "bubble " + role;
    el.textContent = text;
    wrap.appendChild(el);
    log.appendChild(wrap);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  return {
    id,
    section,
    textarea,
    applyReset,
    log,
    refreshPreview,
    modelSelect,

    getSystemPrompt() {
      return textarea.value;
    },

    setSystemPrompt(body) {
      textarea.value = body;
      refreshPreview();
    },

    setModelKey(key) {
      modelSelect.value = key;
    },

    onModelChange(fn) {
      modelSelect.addEventListener("change", () => fn(modelSelect.value));
    },

    addBubble,

    addLogNote(text) {
      const note = document.createElement("div");
      note.className   = "log-note";
      note.textContent = text;
      log.appendChild(note);
    },

    clearLog() {
      log.innerHTML = "";
      log.appendChild(emptyState);
    },

    renderFromMessages(messages) {
      log.innerHTML = "";
      const nonSystem = messages.filter(m => m.role !== "system");
      if (nonSystem.length === 0) {
        log.appendChild(emptyState);
        return;
      }
      for (const msg of nonSystem) {
        addBubble(msg.role, msg.content);
      }
    },

    onUsage: null,
  };
}
```

- [ ] **Step 2: Run JS tests**

```bash
node --test sandbox/js/*.test.js
```

Expected: 44 passed, 11 skipped.

- [ ] **Step 3: Commit**

```bash
git add sandbox/js/pane.js
git commit -m "refactor: simplify pane — remove registry dropdown, add getSystemPrompt/setSystemPrompt"
```

---

## Task 6: model-selector.js — component + tests

**Files:**
- Create: `sandbox/js/model-selector.js`
- Create: `sandbox/js/model-selector.test.js`

The model selector renders a grouped checklist (Local / Frontier). Its state logic is extracted into a pure function so it can be unit-tested without DOM.

- [ ] **Step 1: Write failing tests**

Create `sandbox/js/model-selector.test.js`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { createModelSelectorState } from "./model-selector.js";

test("initial selected keys match initialKeys", () => {
  const state = createModelSelectorState({
    allKeys: ["a", "b", "c"],
    initialKeys: ["a", "b"],
    onChange: () => {},
  });
  assert.deepEqual([...state.selectedKeys()].sort(), ["a", "b"]);
});

test("toggle adds a deselected key", () => {
  const changes = [];
  const state = createModelSelectorState({
    allKeys: ["a", "b"],
    initialKeys: ["a"],
    onChange: (keys) => changes.push([...keys]),
  });
  state.toggle("b");
  assert.ok([...state.selectedKeys()].includes("b"));
  assert.equal(changes.length, 1);
  assert.ok(changes[0].includes("b"));
});

test("toggle removes a selected key", () => {
  const state = createModelSelectorState({
    allKeys: ["a", "b"],
    initialKeys: ["a", "b"],
    onChange: () => {},
  });
  state.toggle("a");
  assert.ok(![...state.selectedKeys()].includes("a"));
});

test("cannot deselect last key — minimum 1 enforced", () => {
  const state = createModelSelectorState({
    allKeys: ["a"],
    initialKeys: ["a"],
    onChange: () => {},
  });
  state.toggle("a");  // try to deselect only key
  assert.ok([...state.selectedKeys()].includes("a"));
});

test("unknown key toggle is a no-op", () => {
  const state = createModelSelectorState({
    allKeys: ["a"],
    initialKeys: ["a"],
    onChange: () => {},
  });
  state.toggle("z");
  assert.deepEqual([...state.selectedKeys()], ["a"]);
});
```

- [ ] **Step 2: Run to confirm failures**

```bash
node --test sandbox/js/model-selector.test.js
```

Expected: 5 failures (module not found).

- [ ] **Step 3: Create `sandbox/js/model-selector.js`**

```js
/**
 * Pure state machine for model selection.
 * Exported separately so it can be unit-tested without DOM.
 */
export function createModelSelectorState({ allKeys, initialKeys, onChange }) {
  const valid   = new Set(allKeys);
  const selected = new Set(initialKeys.filter(k => valid.has(k)));

  return {
    selectedKeys() { return new Set(selected); },

    toggle(key) {
      if (!valid.has(key)) return;
      if (selected.has(key)) {
        if (selected.size <= 1) return;  // min 1 enforced
        selected.delete(key);
      } else {
        selected.add(key);
      }
      onChange(new Set(selected));
    },
  };
}

/**
 * DOM component. Renders a grouped model checklist into `container`.
 * Returns { element, state } — call state.selectedKeys() to read selections.
 */
export function createModelSelector({ container, models, initialKeys, onChange }) {
  const allKeys = Object.keys(models);
  const state   = createModelSelectorState({ allKeys, initialKeys, onChange });

  const wrap = document.createElement("div");
  wrap.className = "model-selector";

  const groups = { local: [], frontier: [] };
  for (const [key, m] of Object.entries(models)) {
    (groups[m.group] || groups.local).push(key);
  }

  for (const [groupName, keys] of Object.entries(groups)) {
    if (!keys.length) continue;
    const groupLabel = document.createElement("div");
    groupLabel.className   = "model-group-label";
    groupLabel.textContent = groupName.toUpperCase();
    wrap.appendChild(groupLabel);

    for (const key of keys) {
      const row = document.createElement("label");
      row.className = "model-row";

      const cb = document.createElement("input");
      cb.type    = "checkbox";
      cb.checked = state.selectedKeys().has(key);
      cb.className = "model-cb";

      const name = document.createElement("span");
      name.className   = "model-name";
      name.textContent = key;

      const tag = document.createElement("span");
      tag.className   = `model-tag ${groupName}`;
      tag.textContent = groupName;

      cb.addEventListener("change", () => {
        state.toggle(key);
        cb.checked = state.selectedKeys().has(key);
      });

      row.appendChild(cb);
      row.appendChild(name);
      row.appendChild(tag);
      wrap.appendChild(row);
    }
  }

  container.appendChild(wrap);
  return { element: wrap, state };
}
```

- [ ] **Step 4: Run all JS tests**

```bash
node --test sandbox/js/*.test.js
```

Expected: 49 passed, 11 skipped (5 new model-selector tests pass).

- [ ] **Step 5: Commit**

```bash
git add sandbox/js/model-selector.js sandbox/js/model-selector.test.js
git commit -m "feat: add model-selector component with pure state and DOM wrapper"
```

---

## Task 7: registry-panel.js — right-panel component

**Files:**
- Create: `sandbox/js/registry-panel.js`

No unit test — pure DOM construction with callbacks. Acceptance-tested via manual checklist.

- [ ] **Step 1: Create `sandbox/js/registry-panel.js`**

```js
/**
 * Right-panel showing active prompt metadata + registry actions.
 *
 * Usage:
 *   const panel = createRegistryPanel({ container, onSaveDraft, onValidate, onViewRegistry });
 *   panel.setPrompt(promptObject);   // { id, version, status, eval_status, tokens_prompt_body, cost_per_run_usd }
 *   panel.setPrompt(null);           // clears to empty state
 */
export function createRegistryPanel({ container, onSaveDraft, onValidate, onViewRegistry }) {
  const panel = document.createElement("aside");
  panel.className = "registry-panel";

  const title = document.createElement("div");
  title.className   = "rp-title";
  title.textContent = "Active Prompt";

  const idEl = document.createElement("div");
  idEl.className   = "rp-id";
  idEl.textContent = "—";

  const metaEl = document.createElement("div");
  metaEl.className = "rp-meta";

  const divider1 = document.createElement("hr");
  divider1.className = "rp-divider";

  const statsEl = document.createElement("div");
  statsEl.className = "rp-stats";

  const divider2 = document.createElement("hr");
  divider2.className = "rp-divider";

  const draftBtn = document.createElement("button");
  draftBtn.className   = "rp-action save-version";
  draftBtn.textContent = "Save as next draft";
  draftBtn.addEventListener("click", () => onSaveDraft && onSaveDraft());

  const validateBtn = document.createElement("button");
  validateBtn.className   = "rp-action promote";
  validateBtn.textContent = "Mark eval: validated ✓";
  validateBtn.addEventListener("click", () => onValidate && onValidate());

  const viewBtn = document.createElement("button");
  viewBtn.className   = "rp-action open-reg";
  viewBtn.textContent = "View full registry →";
  viewBtn.addEventListener("click", () => onViewRegistry && onViewRegistry());

  panel.append(title, idEl, metaEl, divider1, statsEl, divider2, draftBtn, validateBtn, viewBtn);
  container.appendChild(panel);

  function stat(label, value) {
    const row = document.createElement("div");
    row.className = "rp-stat";
    row.innerHTML = `${label} <span>${value ?? "—"}</span>`;
    return row;
  }

  return {
    element: panel,

    setPrompt(p) {
      if (!p) {
        idEl.textContent  = "—";
        metaEl.textContent = "";
        statsEl.innerHTML  = "";
        draftBtn.disabled    = true;
        validateBtn.disabled = true;
        return;
      }
      idEl.textContent   = p.id;
      metaEl.textContent = `v${p.version} · ${p.status ?? "draft"}`;
      statsEl.innerHTML  = "";
      statsEl.append(
        stat("eval status", p.eval_status ?? "pending"),
        stat("tokens",      p.tokens_prompt_body ?? "—"),
        stat("cost/run",    p.cost_per_run_usd != null ? `$${p.cost_per_run_usd.toFixed(4)}` : "—"),
      );
      draftBtn.disabled    = false;
      validateBtn.disabled = (p.eval_status === "validated");
    },
  };
}
```

- [ ] **Step 2: Run all tests (no new tests expected)**

```bash
python3 -m pytest tests/ -v && node --test sandbox/js/*.test.js
```

Expected: 42 Python, 49 JS passed.

- [ ] **Step 3: Commit**

```bash
git add sandbox/js/registry-panel.js
git commit -m "feat: add registry-panel component for active prompt metadata and actions"
```

---

## Task 8: sessions.js — new save format + backward compat

**Files:**
- Modify: `sandbox/js/sessions.js`

New sessions include `promptRef` (the registry prompt selected) and `models` (which model keys were active). Legacy sessions (no `promptRef`) still load without crashing.

- [ ] **Step 1: Update sessions.js**

Change the `save` method signature and add `resolveSession` export for loading:

```js
import * as api from "./api.js";

export function createSessionsStore() {
  function nowIso() { return new Date().toISOString(); }
  function newId() {
    const rand = Math.random().toString(36).slice(2, 8).padEnd(6, "0");
    return `sess-${Date.now()}-${rand}`;
  }

  return {
    async load() {
      try {
        return await api.fetchSessions();
      } catch (err) {
        console.warn("Failed to load sessions from API:", err);
        return [];
      }
    },

    async save({ name, panes, vaultConfig, promptRef = null, models = [] }) {
      const now = nowIso();
      const entry = {
        id:        newId(),
        name,
        createdAt: now,
        updatedAt: now,
        panes:     { promptRef, models, panes },
        vaultConfig,
      };
      try {
        await api.saveSession(entry);
        return entry;
      } catch (err) {
        console.warn("Failed to save session to API:", err);
        throw err;
      }
    },

    async rename(id, newName) {
      try { return await api.renameSession(id, newName); }
      catch (err) { console.warn("Failed to rename session via API:", err); return null; }
    },

    async delete(id) {
      try { await api.deleteSession(id); return true; }
      catch (err) { console.warn("Failed to delete session via API:", err); return false; }
    },
  };
}

export function resolveModelKey(saved, modelKeys, fallbackKey) {
  if (saved && modelKeys.includes(saved)) return saved;
  if (saved) console.warn(`Unknown modelKey "${saved}" in saved session; falling back to "${fallbackKey}"`);
  return fallbackKey;
}

/**
 * Normalise a saved session entry into a canonical shape regardless of whether
 * it was saved with the old format (panes is an array) or the new format
 * (panes is {promptRef, models, panes}).
 *
 * Returns: { promptRef, models, panes, vaultConfig }
 */
export function resolveSession(entry) {
  const raw = entry.panes;
  if (Array.isArray(raw)) {
    // Legacy format
    return { promptRef: null, models: [], panes: raw, vaultConfig: entry.vaultConfig };
  }
  return {
    promptRef:   raw.promptRef  ?? null,
    models:      raw.models     ?? [],
    panes:       raw.panes      ?? [],
    vaultConfig: entry.vaultConfig,
  };
}

export function exportToRegistryDraft(session) {
  if (!session?.panes?.length) throw new Error("exportToRegistryDraft: session has no panes");
  const primaryPane = session.panes[0];
  return {
    id:                 session.name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || "draft",
    version:            "0.1.0",
    status:             "draft",
    tier:               "audit",
    owner:              "unknown",
    body:               primaryPane.systemPrompt,
    use_case:           "Draft exported from sandbox",
    default_model:      primaryPane.modelKey ?? null,
    cost_per_run_usd:   null,
    tokens_prompt_body: null,
    tested_on:          primaryPane.modelKey ? [primaryPane.modelKey] : [],
    eval_status:        "unevaluated",
    composes:           [],
    file:               null,
    notes:              "",
  };
}
```

- [ ] **Step 2: Update sessions.test.js tests for new resolveSession export**

Open `sandbox/js/sessions.test.js`. The existing tests for `createSessionsStore` skip (they use localStorage). Add these at the end of the file:

```js
import { resolveSession } from "./sessions.js";

test("resolveSession: new format returns promptRef and models", () => {
  const entry = {
    panes: { promptRef: { id: "my_prompt", version: "1.0.0" }, models: ["qwen3-4b"], panes: [] },
    vaultConfig: { enabled: false, topK: 5 },
  };
  const r = resolveSession(entry);
  assert.deepEqual(r.promptRef, { id: "my_prompt", version: "1.0.0" });
  assert.deepEqual(r.models, ["qwen3-4b"]);
});

test("resolveSession: legacy array format returns null promptRef and empty models", () => {
  const entry = {
    panes: [{ systemPrompt: "hello", messages: [], modelKey: "qwen3-4b" }],
    vaultConfig: { enabled: false, topK: 5 },
  };
  const r = resolveSession(entry);
  assert.equal(r.promptRef, null);
  assert.deepEqual(r.models, []);
  assert.equal(r.panes[0].systemPrompt, "hello");
});
```

(Add `import assert from "node:assert/strict";` at top of the test file if not already present.)

- [ ] **Step 3: Run JS tests**

```bash
node --test sandbox/js/*.test.js
```

Expected: 51 passed, 11 skipped (2 new resolveSession tests).

- [ ] **Step 4: Commit**

```bash
git add sandbox/js/sessions.js sandbox/js/sessions.test.js
git commit -m "feat: sessions new format with promptRef+models; resolveSession for backward compat"
```

---

## Task 9: index.html — unified SPA layout

**Files:**
- Modify: `sandbox/index.html`

This task restructures the HTML to add the new sections. All existing CSS classes and tokens are preserved. New CSS rules are added for: prompt picker section, model checklist, registry panel, registry iframe tab.

- [ ] **Step 1: Add CSS for new sections**

In `sandbox/index.html`, find the `</style>` closing tag and insert before it:

```css
/* ── Prompt picker (rail) ── */
.rail-prompt-section { padding: 10px 12px; border-bottom: 1px solid var(--line-2); }
.rail-section-label { font-family: var(--mono); font-size: 9.5px; color: var(--ink-4); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px; }
.rail-prompt-select { width: 100%; font-family: var(--sans); font-size: 11.5px; background: var(--paper); border: 1px solid var(--line); color: var(--ink); padding: 5px 8px; border-radius: 0; cursor: pointer; }
.rail-prompt-badges { display: flex; gap: 5px; margin-top: 4px; flex-wrap: wrap; }
.rail-prompt-badge { font-family: var(--mono); font-size: 9px; padding: 1px 5px; border-radius: 2px; }
.rail-prompt-badge.version { color: var(--green); background: rgba(46,112,72,.08); border: 1px solid rgba(46,112,72,.2); }
.rail-prompt-badge.eval { color: var(--amber); background: rgba(168,122,0,.08); border: 1px solid rgba(168,122,0,.2); }
.rail-prompt-badge.validated { color: var(--green); background: rgba(46,112,72,.08); border: 1px solid rgba(46,112,72,.2); }

/* ── Model checklist (rail) ── */
.rail-model-section { padding: 10px 12px; border-bottom: 1px solid var(--line-2); }
.model-group-label { font-family: var(--mono); font-size: 9px; color: var(--ink-4); text-transform: uppercase; letter-spacing: 0.06em; margin: 6px 0 3px; }
.model-row { display: flex; align-items: center; gap: 6px; padding: 3px 0; cursor: pointer; font-size: 11.5px; color: var(--ink-2); }
.model-row:hover { color: var(--ink); }
.model-cb { accent-color: var(--teal); flex-shrink: 0; }
.model-name { flex: 1; font-family: var(--mono); font-size: 10.5px; }
.model-tag { font-size: 9px; padding: 1px 4px; border-radius: 2px; font-family: var(--mono); }
.model-tag.local { color: var(--green); background: rgba(46,112,72,.08); }
.model-tag.frontier { color: var(--plum); background: rgba(97,72,130,.08); }

/* ── Rail bottom actions ── */
.rail-actions { padding: 10px 12px; border-top: 1px solid var(--line-2); display: flex; flex-direction: column; gap: 5px; }
.rail-action-btn { width: 100%; font-family: var(--mono); font-size: 10px; background: transparent; border: 1px solid var(--line); color: var(--ink-3); padding: 6px 10px; cursor: pointer; letter-spacing: 0.02em; text-align: left; }
.rail-action-btn:hover { color: var(--ink); border-color: rgba(12,15,20,.25); background: var(--paper); }
.rail-action-btn.primary { color: var(--teal); border-color: rgba(42,100,100,.3); }
.rail-action-btn.primary:hover { background: rgba(42,100,100,.05); }

/* ── Registry panel (right) ── */
.registry-panel { width: 220px; flex-shrink: 0; background: var(--paper-2); border-left: 1px solid var(--line); display: flex; flex-direction: column; padding: 14px 12px; gap: 7px; overflow-y: auto; }
.rp-title { font-family: var(--mono); font-size: 9.5px; color: var(--ink-4); text-transform: uppercase; letter-spacing: 0.06em; }
.rp-id { font-size: 13px; font-weight: 600; color: var(--ink); }
.rp-meta { font-size: 11px; color: var(--ink-3); }
.rp-divider { border: none; border-top: 1px solid var(--line-2); margin: 2px 0; }
.rp-stats { display: flex; flex-direction: column; gap: 3px; }
.rp-stat { display: flex; justify-content: space-between; font-size: 10.5px; color: var(--ink-3); }
.rp-stat span { color: var(--ink-2); font-family: var(--mono); }
.rp-action { width: 100%; font-family: var(--mono); font-size: 10px; background: transparent; border: 1px solid var(--line); color: var(--ink-3); padding: 5px 8px; cursor: pointer; text-align: left; letter-spacing: 0.02em; }
.rp-action:hover { color: var(--ink); }
.rp-action.save-version { color: var(--teal); border-color: rgba(42,100,100,.3); }
.rp-action.save-version:hover { background: rgba(42,100,100,.05); }
.rp-action.promote { color: var(--green); border-color: rgba(46,112,72,.3); }
.rp-action.promote:hover { background: rgba(46,112,72,.05); }
.rp-action.open-reg { font-size: 9.5px; }
.rp-action:disabled { opacity: 0.4; cursor: default; }

/* ── Registry iframe tab ── */
.registry-frame { flex: 1; border: none; background: var(--paper); display: none; }
.registry-frame.active { display: block; }
.pane-container.hidden { display: none !important; }
.registry-panel.hidden { display: none !important; }

/* ── Directive composer label ── */
.composer-directive-hint { font-size: 10px; color: var(--ink-4); font-family: var(--mono); }
```

- [ ] **Step 2: Restructure the HTML body**

Find the `<body>` section in `sandbox/index.html` (after `</style>` and `</head>`). Replace the entire body content with:

```html
<body>

<!-- ── Left Rail ───────────────────────────────── -->
<aside class="rail" id="sessions-rail">

  <div class="rail-header">
    <div class="rail-logo"><em>P</em></div>
    <span class="rail-title">Prompt Studio</span>
    <span class="rail-header-spacer"></span>
    <span class="rail-mode-tag" id="rail-mode-tag">eval</span>
  </div>

  <!-- Prompt picker -->
  <div class="rail-prompt-section">
    <div class="rail-section-label">Active Prompt</div>
    <select class="rail-prompt-select" id="prompt-picker">
      <option value="">— loading… —</option>
    </select>
    <div class="rail-prompt-badges" id="prompt-badges"></div>
  </div>

  <!-- Model checklist -->
  <div class="rail-model-section">
    <div class="rail-section-label">Models</div>
    <div id="model-checklist"></div>
  </div>

  <!-- Sessions list -->
  <div class="rail-new-wrap">
    <button class="rail-new-btn" id="new-session">
      <span class="rail-new-plus">+</span>
      <span>New session</span>
      <span class="rail-new-spacer"></span>
      <span class="rail-new-kbd">⌘N</span>
    </button>
  </div>

  <div class="rail-saved-label">Saved sessions</div>
  <div class="rail-list" id="sessions-list"></div>
  <div class="rail-save-slot" id="sessions-save-slot"></div>

  <!-- Bottom actions -->
  <div class="rail-actions">
    <button class="rail-action-btn primary" id="save-session-btn">Save session</button>
    <button class="rail-action-btn" id="export-btn">Export .md</button>
  </div>

  <!-- Vault health -->
  <div class="rail-vault" id="vault-card">
    <div class="rail-vault-header">
      <span class="health-dot" id="vault-health" title="Vault search: checking…"></span>
      <span>vault search</span>
    </div>
    <div class="rail-vault-sub" id="vault-card-sub">checking…</div>
  </div>

</aside>

<!-- ── Main area ─────────────────────────────────── -->
<div style="flex:1;display:flex;flex-direction:column;min-width:0;overflow:hidden;">

  <!-- Topbar -->
  <div class="topbar">
    <span class="topbar-breadcrumb">Prompt Studio</span>
    <span class="topbar-sep">/</span>
    <span class="topbar-session" id="topbar-session">untitled</span>
    <span class="topbar-subtitle" id="topbar-subtitle">empty</span>
    <span class="topbar-dots" id="topbar-dots" hidden>···</span>
    <span style="flex:1"></span>
    <div class="seg-toggle" id="mode-toggle">
      <button class="seg-btn seg-active" id="tab-eval">Eval</button>
      <button class="seg-btn" id="tab-registry">Registry</button>
    </div>
    <button class="stop-btn" id="stop-btn" hidden>⏹ Stop</button>
  </div>

  <!-- Pane container (eval mode) -->
  <main class="pane-container" id="pane-container" style="flex:1;display:flex;min-height:0;overflow:hidden;"></main>

  <!-- Registry iframe (registry mode, hidden by default) -->
  <iframe class="registry-frame" id="registry-frame" src="/registry/"></iframe>

  <!-- Directive composer -->
  <div class="composer" id="composer">
    <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
      <span class="composer-label" id="composer-label">Directive</span>
      <span class="composer-directive-hint">→ sent to all active models</span>
    </div>
    <div style="display:flex;gap:8px;align-items:flex-end;">
      <textarea id="input" placeholder="Enter directive…" rows="2" style="flex:1;resize:none;"></textarea>
      <div style="display:flex;flex-direction:column;gap:4px;">
        <button id="send">SEND ↵</button>
        <span class="composer-hint" id="send-hint">shift+↵ newline</span>
      </div>
    </div>
    <div style="display:flex;gap:10px;align-items:center;margin-top:6px;">
      <label class="vault-label" id="vault-label-wrap">
        <span class="vault-checkbox-box" id="vault-checkbox-visual"></span>
        <input type="checkbox" id="use-vault" style="display:none;">
        use context
      </label>
      <span>top-K <input type="number" id="top-k" min="1" max="20" value="5" class="top-k-input"></span>
      <button class="ghost-btn" id="reindex">Reindex</button>
      <span class="vault-inline-status" id="vault-status"></span>
    </div>
  </div>

</div>

<!-- ── Registry Panel (right) ──────────────────── -->
<div id="registry-panel-mount"></div>

<script type="module" src="js/app.js"></script>
</body>
```

- [ ] **Step 3: Verify the page loads without JS errors**

Start the server and open `http://localhost:8000/`. The page should render the new layout (broken until app.js is rewritten in Task 10, but no syntax errors).

```bash
python3 server.py &
open http://localhost:8000/
```

- [ ] **Step 4: Commit**

```bash
git add sandbox/index.html
git commit -m "feat: unified SPA layout — prompt picker, model checklist, registry panel mount, directive composer"
```

---

## Task 10: app.js — full SPA rewrite

**Files:**
- Modify: `sandbox/js/app.js`

This is the main wiring task. Replace the entire file with the unified SPA controller.

- [ ] **Step 1: Write new app.js**

```js
import { createPaneState }    from "./state.js";
import { createPane }         from "./pane.js";
import { sendToPanes }        from "./send.js";
import { pingVaultHealth, reindexVault } from "./vault.js";
import { ALL_MODELS, MODELS, FRONTIER_MODELS, getActiveModelKey } from "./config.js";
import { renderSaveSlot, renderSessionList } from "./session-rail.js";
import { buildMarkdown, triggerMarkdownDownload, slugify } from "./export.js";
import { createSessionsStore, resolveModelKey, resolveSession } from "./sessions.js";
import { createMeter }        from "./meter.js";
import { createModelSelector } from "./model-selector.js";
import { createRegistryPanel }  from "./registry-panel.js";
import * as api from "./api.js";

// ── State ──────────────────────────────────────────────
let registryPrompts  = [];   // [{id, version, status, eval_status, body, ...}]
let activePrompt     = null; // current registry prompt object
let activePaneMap    = {};   // modelKey → { state, pane, meter }
let activeSessionId  = null;
let selectedModelKeys = new Set([getActiveModelKey()]);

const sessionsStore = createSessionsStore();

// ── DOM refs ──────────────────────────────────────────
const $paneContainer    = document.getElementById("pane-container");
const $input            = document.getElementById("input");
const $send             = document.getElementById("send");
const $newSession       = document.getElementById("new-session");
const $saveSessionBtn   = document.getElementById("save-session-btn");
const $exportBtn        = document.getElementById("export-btn");
const $stopBtn          = document.getElementById("stop-btn");
const $useVault         = document.getElementById("use-vault");
const $topK             = document.getElementById("top-k");
const $reindex          = document.getElementById("reindex");
const $vaultStatus      = document.getElementById("vault-status");
const $vaultHealth      = document.getElementById("vault-health");
const $vaultCardSub     = document.getElementById("vault-card-sub");
const $vaultCheckVisual = document.getElementById("vault-checkbox-visual");
const $topbarSession    = document.getElementById("topbar-session");
const $topbarSubtitle   = document.getElementById("topbar-subtitle");
const $topbarDots       = document.getElementById("topbar-dots");
const $sessionsList     = document.getElementById("sessions-list");
const $promptPicker     = document.getElementById("prompt-picker");
const $promptBadges     = document.getElementById("prompt-badges");
const $modelChecklist   = document.getElementById("model-checklist");
const $registryPanelMount = document.getElementById("registry-panel-mount");
const $tabEval          = document.getElementById("tab-eval");
const $tabRegistry      = document.getElementById("tab-registry");
const $paneContainerEl  = document.getElementById("pane-container");
const $registryFrame    = document.getElementById("registry-frame");
const $composer         = document.getElementById("composer");

// ── Registry panel ─────────────────────────────────────
const registryPanel = createRegistryPanel({
  container: $registryPanelMount,
  onSaveDraft: handleSaveDraft,
  onValidate:  handleValidate,
  onViewRegistry: () => switchTab("registry"),
});

// ── Model selector ─────────────────────────────────────
const modelSelector = createModelSelector({
  container:   $modelChecklist,
  models:      ALL_MODELS,
  initialKeys: [getActiveModelKey()],
  onChange(keys) {
    selectedModelKeys = keys;
    syncPanes();
  },
});

// ── Pane management ─────────────────────────────────────
function getSystemPrompt() {
  return activePrompt?.body ?? "";
}

function createOrUpdatePane(modelKey) {
  if (activePaneMap[modelKey]) return;
  const state = createPaneState(getSystemPrompt());
  const pane  = createPane({
    id:              modelKey,
    container:       $paneContainer,
    initialPrompt:   getSystemPrompt(),
    modelKeys:       [modelKey],
    initialModelKey: modelKey,
  });
  pane.applyReset.addEventListener("click", () => {
    state.applyPrompt(pane.getSystemPrompt());
    pane.clearLog();
    pane.refreshPreview();
  });
  const meter = createMeter({
    pane,
    state,
    contextWindow: ALL_MODELS[modelKey].contextWindow,
    getDraftText:  () => $input.value,
  });
  pane.onUsage = (usage) => {
    if (typeof usage.prompt_tokens === "number") meter.setExactPromptTokens(usage.prompt_tokens);
  };
  activePaneMap[modelKey] = { state, pane, meter };
}

function removePane(modelKey) {
  const entry = activePaneMap[modelKey];
  if (!entry) return;
  entry.pane.section.remove();
  entry.meter?.destroy();
  delete activePaneMap[modelKey];
}

function syncPanes() {
  const desired = new Set(selectedModelKeys);
  // Remove panes no longer selected
  for (const key of Object.keys(activePaneMap)) {
    if (!desired.has(key)) removePane(key);
  }
  // Add new panes
  for (const key of desired) {
    createOrUpdatePane(key);
  }
}

function activePanes() {
  return Object.entries(activePaneMap).map(([modelKey, { state, pane }]) => ({
    state,
    pane,
    model: ALL_MODELS[modelKey],
  }));
}

// ── Prompt picker ───────────────────────────────────────
function populatePromptPicker(prompts) {
  $promptPicker.innerHTML = "";
  const none = document.createElement("option");
  none.value = "";
  none.textContent = "— no prompt selected —";
  $promptPicker.appendChild(none);

  for (const p of prompts) {
    const opt = document.createElement("option");
    opt.value = `${p.id}|${p.version}`;
    opt.textContent = `${p.id}  v${p.version}`;
    $promptPicker.appendChild(opt);
  }
}

function applyPromptToAllPanes(prompt) {
  activePrompt = prompt;
  const body = prompt?.body ?? "";
  for (const { pane } of Object.values(activePaneMap)) {
    pane.setSystemPrompt(body);
    pane.applyReset.click();
  }
  updatePromptBadges(prompt);
  registryPanel.setPrompt(prompt);
}

function updatePromptBadges(prompt) {
  $promptBadges.innerHTML = "";
  if (!prompt) return;
  const vBadge = document.createElement("span");
  vBadge.className   = "rail-prompt-badge version";
  vBadge.textContent = `v${prompt.version}`;
  const eBadge = document.createElement("span");
  eBadge.className   = `rail-prompt-badge eval ${prompt.eval_status === "validated" ? "validated" : ""}`;
  eBadge.textContent = `eval: ${prompt.eval_status ?? "pending"}`;
  $promptBadges.append(vBadge, eBadge);
}

$promptPicker.addEventListener("change", () => {
  const val = $promptPicker.value;
  if (!val) { applyPromptToAllPanes(null); return; }
  const [id, version] = val.split("|");
  const prompt = registryPrompts.find(p => p.id === id && p.version === version);
  if (prompt) applyPromptToAllPanes(prompt);
});

async function loadRegistryPrompts() {
  try {
    const res = await api.fetchPrompts();
    registryPrompts = res;
    populatePromptPicker(registryPrompts);
  } catch { /* server may not be running — degrade gracefully */ }
}

// ── Tab switching ───────────────────────────────────────
function switchTab(tab) {
  if (tab === "registry") {
    $paneContainerEl.style.display = "none";
    $composer.style.display        = "none";
    $registryPanelMount.style.display = "none";
    $registryFrame.style.display   = "flex";
    $registryFrame.style.flex      = "1";
    $tabEval.classList.remove("seg-active");
    $tabRegistry.classList.add("seg-active");
  } else {
    $paneContainerEl.style.display = "";
    $composer.style.display        = "";
    $registryPanelMount.style.display = "";
    $registryFrame.style.display   = "none";
    $tabEval.classList.add("seg-active");
    $tabRegistry.classList.remove("seg-active");
  }
}

$tabEval.addEventListener("click",     () => switchTab("eval"));
$tabRegistry.addEventListener("click", () => switchTab("registry"));

// Listen for "Open in Eval" messages from registry iframe
window.addEventListener("message", (e) => {
  if (e.data?.type !== "loadPrompt") return;
  const { id, version } = e.data;
  const prompt = registryPrompts.find(p => p.id === id && p.version === version);
  if (prompt) {
    switchTab("eval");
    $promptPicker.value = `${id}|${version}`;
    applyPromptToAllPanes(prompt);
  }
});

// ── Registry actions ────────────────────────────────────
async function handleSaveDraft() {
  if (!activePrompt) { alert("Select a registry prompt first."); return; }
  const body = Object.values(activePaneMap)[0]?.pane.getSystemPrompt() ?? activePrompt.body;
  try {
    const result = await api.saveDraftPrompt(activePrompt.id, body);
    $vaultStatus.textContent = `Draft saved as v${result.version}`;
    setTimeout(() => { $vaultStatus.textContent = ""; }, 4000);
    await loadRegistryPrompts();
  } catch (err) {
    $vaultStatus.textContent = `Draft save failed: ${err.message}`;
    setTimeout(() => { $vaultStatus.textContent = ""; }, 5000);
  }
}

async function handleValidate() {
  if (!activePrompt) return;
  const ok = confirm(`Mark ${activePrompt.id} v${activePrompt.version} as validated?`);
  if (!ok) return;
  try {
    await api.validatePrompt(activePrompt.id, activePrompt.version);
    $vaultStatus.textContent = "Marked as validated ✓";
    setTimeout(() => { $vaultStatus.textContent = ""; }, 3000);
    await loadRegistryPrompts();
    const updated = registryPrompts.find(p => p.id === activePrompt.id && p.version === activePrompt.version);
    if (updated) { activePrompt = updated; registryPanel.setPrompt(updated); }
  } catch (err) {
    $vaultStatus.textContent = `Validate failed: ${err.message}`;
    setTimeout(() => { $vaultStatus.textContent = ""; }, 5000);
  }
}

// ── Send / stream ───────────────────────────────────────
async function handleSend() {
  if ($send.disabled) return;
  const text = $input.value.trim();
  if (!text) return;
  $input.value = "";
  $send.disabled        = true;
  $send.textContent     = "Streaming…";
  $topbarDots.hidden    = false;
  $topbarSubtitle.textContent = "streaming";
  $stopBtn.hidden       = false;

  try {
    await sendToPanes({
      panes:    activePanes(),
      userText: text,
      useVault: $useVault.checked,
      topK:     $topK.value,
    });
  } finally {
    $send.disabled        = false;
    $send.textContent     = "SEND ↵";
    $topbarDots.hidden    = true;
    $topbarSubtitle.textContent = "conversation";
    $stopBtn.hidden       = true;
  }
}

$send.addEventListener("click", handleSend);
$input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
});
$input.addEventListener("input", () => {
  for (const { meter } of Object.values(activePaneMap)) meter?.render();
});

// ── Vault ───────────────────────────────────────────────
function syncVaultCheckbox() {
  $vaultCheckVisual.classList.toggle("checked", $useVault.checked);
}
$useVault.addEventListener("change", syncVaultCheckbox);
document.getElementById("vault-label-wrap").addEventListener("click", () => {
  $useVault.checked = !$useVault.checked;
  syncVaultCheckbox();
});
syncVaultCheckbox();

$reindex.addEventListener("click", async () => {
  $reindex.disabled = true;
  $vaultStatus.textContent = "Reindexing…";
  try {
    const data = await reindexVault();
    $vaultStatus.textContent = `+${data.added} new, ${data.updated} updated, ${data.deleted} deleted`;
  } catch (err) {
    $vaultStatus.textContent = `Reindex failed: ${err.message}`;
  } finally {
    $reindex.disabled = false;
    setTimeout(() => { $vaultStatus.textContent = ""; }, 6000);
  }
});

async function tickVaultHealth() {
  const state = await pingVaultHealth();
  $vaultHealth.className  = `health-dot ${state}`;
  $vaultCardSub.textContent = state === "ok" ? "online" : "unreachable";
}
tickVaultHealth();
setInterval(tickVaultHealth, 10000);

// ── Sessions ─────────────────────────────────────────────
function currentSnapshot() {
  const panes = Object.entries(activePaneMap).map(([modelKey, { state }]) => ({
    systemPrompt: state.systemPrompt,
    messages:     [...state.messages],
    modelKey,
  }));
  const vaultConfig = {
    enabled: $useVault.checked,
    topK:    Math.max(1, Math.min(20, parseInt($topK.value, 10) || 5)),
  };
  return {
    panes,
    vaultConfig,
    promptRef: activePrompt ? { id: activePrompt.id, version: activePrompt.version } : null,
    models:    [...selectedModelKeys],
  };
}

function autoName() {
  for (const { state } of Object.values(activePaneMap)) {
    const first = state.messages.find(m => m.role === "user");
    if (first) {
      const raw = first.content.trim().split("\n", 1)[0];
      if (raw.length <= 40) return raw;
      const cut = raw.slice(0, 40);
      const last = cut.lastIndexOf(" ");
      return last > 10 ? cut.slice(0, last) : cut;
    }
  }
  return `Untitled ${new Date().toISOString().slice(0, 16).replace("T", " ")}`;
}

function resetToNewSession() {
  for (const { state, pane } of Object.values(activePaneMap)) {
    state.reset();
    pane.clearLog();
  }
  activeSessionId = null;
  $topbarSubtitle.textContent = "empty";
  $topbarSession.textContent  = "untitled";
  refreshSessionList();
}

function loadEntry(entry) {
  const { promptRef, models, panes, vaultConfig } = resolveSession(entry);

  // Restore model selection
  if (models.length) {
    const valid = models.filter(k => ALL_MODELS[k]);
    if (valid.length) {
      selectedModelKeys = new Set(valid);
      // Rebuild checkboxes — simplest: re-create model selector (replace DOM)
      $modelChecklist.innerHTML = "";
      const rebuilt = createModelSelector({
        container:   $modelChecklist,
        models:      ALL_MODELS,
        initialKeys: [...selectedModelKeys],
        onChange(keys) {
          selectedModelKeys = keys;
          syncPanes();
        },
      });
      syncPanes();
    }
  }

  // Restore prompt ref
  if (promptRef) {
    const prompt = registryPrompts.find(p => p.id === promptRef.id && p.version === promptRef.version);
    if (prompt) {
      $promptPicker.value = `${promptRef.id}|${promptRef.version}`;
      applyPromptToAllPanes(prompt);
    }
  }

  // Restore conversation per pane
  for (const saved of panes) {
    const modelKey = saved.modelKey;
    if (!modelKey || !activePaneMap[modelKey]) continue;
    const { state, pane } = activePaneMap[modelKey];
    state.loadSnapshot({
      systemPrompt: saved.systemPrompt ?? getSystemPrompt(),
      messages:     [...saved.messages],
    });
    pane.textarea.value = saved.systemPrompt ?? getSystemPrompt();
    pane.refreshPreview();
    pane.renderFromMessages(state.messages);
  }

  $useVault.checked = !!vaultConfig?.enabled;
  $topK.value       = String(vaultConfig?.topK ?? 5);
  syncVaultCheckbox();
}

async function refreshSessionList() {
  renderSessionList($sessionsList, await sessionsStore.load(), {
    activeId: activeSessionId,
    onClick: async (entry) => {
      activeSessionId = entry.id;
      $topbarSession.textContent = entry.name;
      loadEntry(entry);
      refreshSessionList();
    },
    onDelete: async (entry) => {
      const ok = confirm(`Delete '${entry.name}'?`);
      if (!ok) return;
      await sessionsStore.delete(entry.id);
      if (activeSessionId === entry.id) activeSessionId = null;
      refreshSessionList();
    },
  });
}

$newSession.addEventListener("click", resetToNewSession);

$saveSessionBtn.addEventListener("click", async () => {
  const name = autoName();
  try {
    const snap = currentSnapshot();
    const entry = await sessionsStore.save({
      name,
      panes:     snap.panes,
      vaultConfig: snap.vaultConfig,
      promptRef: snap.promptRef,
      models:    snap.models,
    });
    activeSessionId = entry.id;
    $topbarSession.textContent = name;
    refreshSessionList();
  } catch (err) {
    $vaultStatus.textContent = `Save failed: ${err.message}`;
    setTimeout(() => { $vaultStatus.textContent = ""; }, 5000);
  }
});

renderSaveSlot(document.getElementById("sessions-save-slot"), {
  defaultName: autoName,
  onSave: async (name) => {
    try {
      const snap = currentSnapshot();
      const entry = await sessionsStore.save({
        name,
        panes:     snap.panes,
        vaultConfig: snap.vaultConfig,
        promptRef: snap.promptRef,
        models:    snap.models,
      });
      activeSessionId = entry.id;
      refreshSessionList();
    } catch (err) {
      $vaultStatus.textContent = `Save failed: ${err.message}`;
      setTimeout(() => { $vaultStatus.textContent = ""; }, 5000);
    }
  },
});

$exportBtn.addEventListener("click", () => {
  const snap = currentSnapshot();
  const name = autoName();
  const markdown = buildMarkdown({ panes: snap.panes, vaultConfig: snap.vaultConfig }, name);
  const date     = new Date().toISOString().slice(0, 10);
  triggerMarkdownDownload({ filename: `${slugify(name)}-${date}.md`, markdown });
});

// ── Keyboard shortcuts ───────────────────────────────────
document.addEventListener("keydown", (e) => {
  if (e.key === "n" && (e.metaKey || e.ctrlKey) && !e.shiftKey) { e.preventDefault(); resetToNewSession(); }
  if (e.key === "k" && (e.metaKey || e.ctrlKey) && !e.shiftKey) {
    e.preventDefault();
    const firstRow = $sessionsList.querySelector(".rail-session-row");
    if (firstRow) firstRow.focus();
  }
  if (e.key === "v" && (e.metaKey || e.ctrlKey) && e.shiftKey) {
    e.preventDefault();
    $useVault.checked = !$useVault.checked;
    syncVaultCheckbox();
  }
});

// ── Boot ─────────────────────────────────────────────────
syncPanes();           // create initial pane for default model
loadRegistryPrompts(); // populate prompt picker
refreshSessionList();  // populate session rail
```

- [ ] **Step 2: Run JS tests**

```bash
node --test sandbox/js/*.test.js
```

Expected: 51 passed, 11 skipped.

- [ ] **Step 3: Manual smoke test**

```bash
python3 server.py
```

Open `http://localhost:8000/`. Verify:
- Left rail shows prompt picker dropdown, model checklist, sessions list
- Right panel shows registry panel
- Topbar has Eval / Registry tabs
- Composer input is present at bottom
- Selecting a model key from checklist creates/removes panes

- [ ] **Step 4: Commit**

```bash
git add sandbox/js/app.js
git commit -m "feat: rewrite app.js for unified SPA — prompt picker, model checklist, registry panel, directive composer"
```

---

## Task 11: registry_widget.html — "Open in Eval →" postMessage

**Files:**
- Modify: `registry/interface/registry_widget.html`

Each registry row gets an "Open in Eval →" button that fires a `postMessage` to the parent frame. The parent's `app.js` already listens for `{type: "loadPrompt", id, version}`.

- [ ] **Step 1: Add "Open in Eval →" to the row template**

In `registry/interface/registry_widget.html` at line ~395, find the `<div class="actions">` block inside the template string:

```js
          <div class="actions">
            ${d.body ? `<button onclick="event.stopPropagation(); showBody(${JSON.stringify(d.id)}, ${JSON.stringify(d.version)})">View body</button>` : ""}
          </div>
```

Replace it with:

```js
          <div class="actions">
            ${d.body ? `<button onclick="event.stopPropagation(); showBody(${JSON.stringify(d.id)}, ${JSON.stringify(d.version)})">View body</button>` : ""}
            <button onclick="event.stopPropagation(); window.parent.postMessage({type:'loadPrompt',id:${JSON.stringify(d.id)},version:${JSON.stringify(d.version)}},'*')">Open in Eval →</button>
          </div>
```

- [ ] **Step 3: Test the postMessage flow manually**

1. Start server: `python3 server.py`
2. Open `http://localhost:8000/`
3. Click the **Registry** tab — the registry iframe loads
4. Click "Open in Eval →" on any row
5. Verify: tab switches to Eval, prompt picker selects that prompt, pane system prompt updates

- [ ] **Step 4: Run all tests**

```bash
python3 -m pytest tests/ -v && node --test sandbox/js/*.test.js
```

Expected: 42 Python, 51 JS passed.

- [ ] **Step 5: Commit**

```bash
git add registry/interface/registry_widget.html
git commit -m "feat: add Open in Eval postMessage button to registry rows"
```

---

## Task 12: Full regression + acceptance checklist

**Files:** none changed — verification only.

- [ ] **Run all automated tests**

```bash
python3 -m pytest tests/ -v
node --test sandbox/js/*.test.js
```

Expected: 42 Python passed, 51 JS passed, 11 skipped.

- [ ] **Manual acceptance checklist**

Start server: `python3 server.py` → open `http://localhost:8000/`

```
[ ] Prompt picker populates from registry (dropdown shows prompt IDs + versions)
[ ] Select a prompt → system prompt preview updates in all active panes
[ ] Deselect a model → its pane disappears; at least 1 pane always visible
[ ] Add a model → new pane appears with same system prompt
[ ] Enter directive, ⌘↵ → all panes stream simultaneously
[ ] Stop button cancels in-flight streams
[ ] Save session → appears in sessions list; clicking it restores prompt + models + messages
[ ] Legacy session (old format, no promptRef) loads without crash
[ ] "Save as next draft" → new version appears in prompt picker dropdown
[ ] "Mark eval: validated" → eval badge updates in registry panel; button disables
[ ] Registry tab shows registry iframe; "Open in Eval →" switches back and loads prompt
[ ] Export .md downloads a markdown file
[ ] /registry/ URL still serves registry_widget.html standalone
[ ] Frontier model (claude-sonnet-4-6) with ANTHROPIC_API_KEY set → streams response
[ ] Frontier model without API key → error bubble in pane (server returns 503)
```

- [ ] **Commit if any last-minute fixes were needed**

```bash
git add -p  # stage only intentional changes
git commit -m "fix: <description of any acceptance fixes>"
```

- [ ] **Push to remote**

```bash
git push origin master
```
