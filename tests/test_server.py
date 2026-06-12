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



class SharedMemoryMockHandler(MockHandler):
    """Mock handler that uses a shared in-memory database."""
    def __init__(self, db_uri):
        super().__init__()
        self.db_uri = db_uri

    def get_db(self):
        import sqlite3
        import os
        conn = sqlite3.connect(self.db_uri, uri=True)
        conn.row_factory = sqlite3.Row
        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql"
        )
        with open(schema_path) as f:
            conn.executescript(f.read())
        return conn


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


if __name__ == "__main__":
    unittest.main()

class TestPutPrompt(unittest.TestCase):
    def test_put_updates_prompt(self):
        import uuid
        import sqlite3
        db_uri = f"file:testdb_{uuid.uuid4().hex}?mode=memory&cache=shared"

        # Initialize and insert a prompt
        h = SharedMemoryMockHandler(db_uri)
        conn = h.get_db()
        conn.execute("INSERT INTO prompts (id, version, status, body) VALUES ('prompt1', '1.0', 'draft', 'old body')")
        conn.commit()

        # Prepare request
        update_data = {
            "version": "1.0",
            "status": "production",
            "body": "new body"
        }
        h._set_body(json.dumps(update_data).encode())

        # Execute put
        h.handle_put_prompt("prompt1")
        self.assertEqual(h._last_status, 200, "Expected successful put request")

        # Verify db update
        conn2 = sqlite3.connect(db_uri, uri=True)
        conn2.row_factory = sqlite3.Row
        row = conn2.execute("SELECT status, body FROM prompts WHERE id='prompt1' AND version='1.0'").fetchone()
        self.assertEqual(row['status'], 'production')
        self.assertEqual(row['body'], 'new body')
        conn2.close()


    def test_put_requires_version(self):
        import uuid
        db_uri = f"file:testdb_{uuid.uuid4().hex}?mode=memory&cache=shared"
        h = SharedMemoryMockHandler(db_uri)

        # Missing 'version'
        update_data = {
            "status": "production",
            "body": "new body"
        }
        h._set_body(json.dumps(update_data).encode())

        h.handle_put_prompt("prompt1")
        self.assertEqual(h._last_status, 400, "Expected 400 when version is omitted")

    def test_put_not_found(self):
        import uuid
        db_uri = f"file:testdb_{uuid.uuid4().hex}?mode=memory&cache=shared"
        h = SharedMemoryMockHandler(db_uri)

        update_data = {
            "version": "1.0",
            "status": "production"
        }
        h._set_body(json.dumps(update_data).encode())

        h.handle_put_prompt("does-not-exist")
        self.assertEqual(h._last_status, 404, "Expected 404 for non-existent prompt")
