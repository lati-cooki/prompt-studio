import unittest
import json
import io
import sqlite3
import sys
import os
from unittest.mock import patch

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

    def test_rejects_percent_encoded_and_other_chars(self):
        self.assertFalse(server.is_safe_slug("%2Fetc%2Fpasswd"))
        self.assertFalse(server.is_safe_slug("a%00"))
        self.assertFalse(server.is_safe_slug("a.b"))
        self.assertFalse(server.is_safe_slug("a?b"))


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
        self.assertEqual(mock_open.call_args[0][0], "http://localhost:8110/threads")

    @patch("server.urllib.request.urlopen",
           side_effect=server.urllib.error.URLError("connection refused"))
    def test_threadhub_unreachable_returns_502(self, mock_open):
        h = MockHandler()
        h.handle_get_threads()
        self.assertEqual(h._last_status, 502)
        self.assertIn(b'threadhub_unreachable', h._body_written)

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
        self.assertEqual(mock_open.call_args[0][0], "http://localhost:8110/t/founding/verify")

    def test_thread_detail_rejects_bad_slug(self):
        h = MockHandler()
        h.handle_get_thread("../etc/passwd")
        self.assertEqual(h._last_status, 400)

    def test_thread_verify_rejects_bad_slug(self):
        h = MockHandler()
        h.handle_get_thread_verify("a/b")
        self.assertEqual(h._last_status, 400)

    @patch("server.urllib.request.urlopen",
           side_effect=server.urllib.error.HTTPError(
               "http://x", 404, "Not Found", {}, io.BytesIO(b'{"error":"nf","code":"not_found"}')))
    def test_thread_detail_forwards_upstream_404(self, mock_open):
        h = MockHandler()
        h.handle_get_thread("founding")
        self.assertEqual(h._last_status, 404)
        self.assertIn(b'not_found', h._body_written)

    @patch("server.urllib.request.urlopen")
    def test_thread_detail_strips_query_string(self, mock_open):
        mock_open.return_value = FakeResp(b'[{"seq":0}]', 200)
        h = MockHandler()
        h.path = '/api/threads/founding?foo=1'
        h.do_GET()
        self.assertEqual(h._last_status, 200)
        # upstream URL must be well-formed, with the query stripped
        self.assertEqual(mock_open.call_args[0][0], "http://localhost:8110/t/founding.json")


class TestThreadsRoute(unittest.TestCase):
    def test_threads_route_serves_widget(self):
        h = MockHandler()
        h.path = '/threads'
        h.do_GET()
        self.assertEqual(h._last_status, 200)
        self.assertTrue(len(h._body_written) > 0)


if __name__ == "__main__":
    unittest.main()
