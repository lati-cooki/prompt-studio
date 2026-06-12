import unittest
import json
import io
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server


class MockHandler(server.PromptStudioHandler):
    """Minimal mock that replaces network I/O with in-memory buffers."""

    def __init__(self):
        self._last_status = None
        self._body_written = b""
        self._mock_headers = {}
        self._mock_rfile = io.BytesIO(b"")

    # ── Overrides ────────────────────────────────────────────────────
    def get_db(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql"
        )
        with open(schema_path) as f:
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



class TestDeletePrompt(unittest.TestCase):

    def test_delete_existing_prompt_returns_200(self):
        h = MockHandler()

        shared_conn = sqlite3.connect("file:test_delete_prompt?mode=memory&cache=shared", uri=True)
        shared_conn.row_factory = sqlite3.Row
        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql"
        )
        with open(schema_path) as f:
            shared_conn.executescript(f.read())

        shared_conn.execute("INSERT INTO prompts (id, version, status, body) VALUES ('prompt-1', 'v1', 'draft', 'hello')")
        shared_conn.commit()

        def mock_get_db():
            conn = sqlite3.connect("file:test_delete_prompt?mode=memory&cache=shared", uri=True)
            conn.row_factory = sqlite3.Row
            return conn

        h.get_db = mock_get_db

        h._set_body(b"")
        h.handle_delete_prompt("prompt-1")

        self.assertEqual(h._last_status, 200)
        self.assertEqual(json.loads(h._body_written), {"status": "success"})

        cursor = shared_conn.cursor()
        cursor.execute("SELECT * FROM prompts WHERE id = 'prompt-1'")
        self.assertIsNone(cursor.fetchone())
        shared_conn.close()


if __name__ == "__main__":
    unittest.main()
