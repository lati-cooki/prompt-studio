import unittest
import json
import io
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server


_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")


class _NonClosingConn:
    """Wraps a sqlite3 connection and swallows close() calls so the in-memory
    DB survives across multiple handler method calls within one test."""

    def __init__(self, conn):
        self._conn = conn

    def close(self):
        pass  # intentionally no-op

    def cursor(self):
        return self._conn.cursor()

    def commit(self):
        self._conn.commit()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _make_shared_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with open(_SCHEMA_PATH) as f:
        conn.executescript(f.read())
    return conn


class MockHandler(server.PromptStudioHandler):
    """Minimal mock that replaces network I/O with in-memory buffers."""

    def __init__(self, shared_conn=None):
        self._last_status = None
        self._body_written = b""
        self._mock_headers = {}
        self._mock_rfile = io.BytesIO(b"")
        self._shared_conn = shared_conn

    # ── Overrides ────────────────────────────────────────────────────
    def get_db(self):
        if self._shared_conn is not None:
            self._shared_conn.row_factory = sqlite3.Row
            return _NonClosingConn(self._shared_conn)
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with open(_SCHEMA_PATH) as f:
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
    def headers(self):
        return self._mock_headers

    @property
    def rfile(self):
        return self._mock_rfile

    @property
    def wfile(self):
        return self

    def write(self, data):
        self._body_written += data

    def _set_body(self, body: bytes):
        self._mock_headers = {"Content-Length": str(len(body))}
        self._mock_rfile = io.BytesIO(body)
        self._body_written = b""


class TestBodySizeLimit(unittest.TestCase):
    def test_rejects_oversized_body(self):
        h = MockHandler()
        oversized = b"x" * (server.MAX_BODY_BYTES + 1)
        h._mock_headers = {"Content-Length": str(len(oversized))}
        h._mock_rfile = io.BytesIO(oversized)
        result = h.read_json_body()
        self.assertIsNone(result)
        self.assertEqual(h._last_status, 413)

    def test_rejects_malformed_json(self):
        h = MockHandler()
        body = b"{not json"
        h._set_body(body)
        result = h.read_json_body()
        self.assertIsNone(result)
        self.assertEqual(h._last_status, 400)

    def test_parses_valid_json(self):
        h = MockHandler()
        body = json.dumps({"key": "val"}).encode()
        h._set_body(body)
        result = h.read_json_body()
        self.assertEqual(result, {"key": "val"})

    def test_rejects_missing_required_fields_in_post_sessions(self):
        h = MockHandler()
        # Missing "vaultConfig"
        payload = {"id": "s1", "name": "n", "createdAt": "t", "updatedAt": "t", "panes": []}
        h._set_body(json.dumps(payload).encode())
        h.handle_post_sessions()
        self.assertEqual(h._last_status, 400)


class TestNotFound(unittest.TestCase):
    def test_delete_nonexistent_session_returns_404(self):
        h = MockHandler()
        h._set_body(b"")
        h.handle_delete_session("does-not-exist")
        self.assertEqual(h._last_status, 404)

    def test_delete_nonexistent_prompt_returns_404(self):
        h = MockHandler()
        h._set_body(b"")
        h.handle_delete_prompt("does-not-exist")
        self.assertEqual(h._last_status, 404)

    def test_get_prompt_body_returns_404_for_unknown_id(self):
        h = MockHandler()
        h.handle_get_prompt_body("no-such-prompt")
        self.assertEqual(h._last_status, 404)


class TestPromptBody(unittest.TestCase):
    def setUp(self):
        self._conn = _make_shared_db()

    def tearDown(self):
        self._conn.close()

    def _handler(self):
        return MockHandler(shared_conn=self._conn)

    def _insert_prompt(self, prompt_id, body=None, file=None):
        h = self._handler()
        payload = {
            "id": prompt_id, "version": "1.0.0", "status": "draft",
            "tier": "audit", "owner": "test", "body": body,
            "useCase": "test", "costPerRunUsd": None, "tokensPromptBody": None,
            "defaultModel": None, "evalStatus": "unevaluated", "file": file,
            "notes": "", "composes": [], "testedOn": [],
            "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-01-01T00:00:00Z",
        }
        h._set_body(json.dumps(payload).encode())
        h.handle_post_prompts()

    def test_returns_body_from_db(self):
        self._insert_prompt("my_prompt", body="You are helpful.")
        h = self._handler()
        h.handle_get_prompt_body("my_prompt")
        self.assertEqual(h._last_status, 200)
        result = json.loads(h._body_written)
        self.assertEqual(result["body"], "You are helpful.")

    def test_returns_404_when_no_body_and_no_file(self):
        self._insert_prompt("bodyless", body=None, file=None)
        h = self._handler()
        h.handle_get_prompt_body("bodyless")
        self.assertEqual(h._last_status, 404)

    def test_returns_404_for_missing_file(self):
        self._insert_prompt("file_prompt", body=None, file="prompts/nonexistent.md")
        h = self._handler()
        h.handle_get_prompt_body("file_prompt")
        self.assertEqual(h._last_status, 404)


if __name__ == "__main__":
    unittest.main()
