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


class TestSealRoute(unittest.TestCase):
    @patch("seal.seal_decision", return_value={"slug": "ship", "citationHash": "sha256:h"})
    def test_seal_success(self, mock_seal):
        h = MockHandler()
        h.path = "/api/threads/seal"
        h._set_body(json.dumps({"question": "q", "decision": "d", "decidedBy": "Troy",
                                "evidence": [{"source": "s", "finding": "f"}]}).encode())
        h.do_POST()
        self.assertEqual(h._last_status, 200)
        self.assertIn(b"ship", h._body_written)

    @patch("seal.seal_decision", side_effect=__import__("seal").SealValidationError({"question": "required"}))
    def test_seal_validation_error_is_400(self, mock_seal):
        h = MockHandler()
        h.path = "/api/threads/seal"
        h._set_body(json.dumps({}).encode())
        h.do_POST()
        self.assertEqual(h._last_status, 400)
        self.assertIn(b"question", h._body_written)

    @patch("seal.seal_decision",
           side_effect=__import__("seal").SealError("ThreadHub is not reachable",
                                                    status=502,
                                                    extra={"code": "threadhub_unreachable"}))
    def test_seal_error_maps_status_and_extra(self, mock_seal):
        h = MockHandler()
        h.path = "/api/threads/seal"
        h._set_body(json.dumps({"question": "q", "decision": "d", "decidedBy": "Troy",
                                "evidence": [{"source": "s", "finding": "f"}]}).encode())
        h.do_POST()
        self.assertEqual(h._last_status, 502)
        self.assertIn(b"threadhub_unreachable", h._body_written)


class TestThreadsRoute(unittest.TestCase):
    def test_threads_route_serves_widget(self):
        h = MockHandler()
        h.path = '/threads'
        h.do_GET()
        self.assertEqual(h._last_status, 200)
        self.assertTrue(len(h._body_written) > 0)


class TestServeSandboxIndex(unittest.TestCase):
    def setUp(self):
        # Reset the cached index.html
        server.PromptStudioHandler._cached_index_html = None
        self.original_environ = os.environ.copy()

        # Create a dummy index.html in a way that restores the original or use mocking if needed.
        # Actually, let's just make sure we save the original if it exists.
        self.original_index = None
        if os.path.exists('sandbox/index.html'):
            with open('sandbox/index.html', 'rb') as f:
                self.original_index = f.read()

        os.makedirs('sandbox', exist_ok=True)
        with open('sandbox/index.html', 'wb') as f:
            f.write(b'<html><head><script type="module" src="main.js"></script></head><body></body></html>')

    def tearDown(self):
        server.PromptStudioHandler._cached_index_html = None
        os.environ.clear()
        os.environ.update(self.original_environ)

        # Restore original index.html
        if hasattr(self, 'original_index') and self.original_index is not None:
            with open('sandbox/index.html', 'wb') as f:
                f.write(self.original_index)
        elif os.path.exists('sandbox/index.html') and getattr(self, 'original_index', None) is None:
             pass # In a real scenario we'd remove it, but let's just restore if we had it.

    def test_xss_prevention_in_lm_studio_url(self):
        h = MockHandler()
        xss_payload = '</script><script>alert("XSS")</script>'
        os.environ['LM_STUDIO_URL'] = xss_payload

        # Manually invoke serve_sandbox_index
        h.serve_sandbox_index()

        # Assert status code is 200
        self.assertEqual(h._last_status, 200)

        # Check response body
        response_body = h._body_written.decode()

        # Verify the original payload is not injected raw
        self.assertNotIn('<script>window.LM_STUDIO_URL="</script><script>alert("XSS")</script>";</script>', response_body)

        # Verify the safe encoding is present
        # json.dumps() quotes the string, and <, > are replaced with \u003c, \u003e
        safe_payload = '"\\u003c/script\\u003e\\u003cscript\\u003ealert(\\"XSS\\")\\u003c/script\\u003e"'
        expected_injection = f'<script>window.LM_STUDIO_URL={safe_payload};</script>'
        self.assertIn(expected_injection, response_body)


if __name__ == "__main__":
    unittest.main()


class TestRegistryFromDb(unittest.TestCase):
    """/api/registry serves live DB state, not the static INDEX.json snapshot."""

    def _handler(self):
        h = MockHandler()
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql"
        )
        with open(schema_path) as f:
            conn.executescript(f.read())
        conn.execute(
            "INSERT INTO prompts (id, version, status, tier, use_case, file, composes, tested_on) "
            "VALUES ('p1', '1.0.0', 'draft', 'audit', 'testing', 'prompts/p1.md', '[]', '[\"m\"]')"
        )
        conn.commit()

        class _SharedConn:
            """Handlers close per-request; keep the shared test conn alive."""
            def __init__(self, inner):
                self._inner = inner
            def close(self):
                pass
            def __getattr__(self, name):
                return getattr(self._inner, name)

        h.get_db = lambda: _SharedConn(conn)
        return h, conn

    def test_registry_reflects_live_status(self):
        h, conn = self._handler()
        h.path = "/api/registry"
        h.do_GET()
        self.assertEqual(h._last_status, 200)
        entry = [p for p in json.loads(h._body_written)["prompts"] if p["id"] == "p1"][0]
        self.assertEqual(entry["status"], "draft")
        conn.execute("UPDATE prompts SET status='production' WHERE id='p1'")
        conn.commit()
        h._body_written = b""
        h.do_GET()
        entry = [p for p in json.loads(h._body_written)["prompts"] if p["id"] == "p1"][0]
        self.assertEqual(entry["status"], "production")

    def test_registry_shape_matches_index_contract(self):
        h, _ = self._handler()
        h.path = "/api/registry"
        h.do_GET()
        data = json.loads(h._body_written)
        self.assertIn("registry_version", data)
        self.assertIn("generated_at", data)
        entry = data["prompts"][0]
        for key in ("id", "version", "status", "tier", "use_case", "file", "notes",
                    "cost_per_run_usd", "tokens_prompt_body", "default_model", "eval_status"):
            self.assertIn(key, entry)
        self.assertIsInstance(entry["composes"], list)
        self.assertIsInstance(entry["tested_on"], list)
        self.assertNotIn("body", entry)  # INDEX contract never exposed bodies


class TestSeedBackfill(unittest.TestCase):
    """Seeding backfills INDEX.json prompts missing from a non-empty table,
    without overwriting live state on rows that already exist."""

    def test_backfills_missing_prompts_and_preserves_existing_status(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql"
        )
        with open(schema_path) as f:
            conn.executescript(f.read())
        # one pre-existing row whose live status differs from INDEX.json
        conn.execute(
            "INSERT INTO prompts (id, version, status) "
            "VALUES ('agent_operational_checklist', '1.0.0', 'production')"
        )
        conn.commit()
        server._seed_prompts_from_index(conn)
        rows = {(r["id"], r["version"]): r["status"] for r in
                conn.execute("SELECT id, version, status FROM prompts")}
        index_prompts = json.load(open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "registry", "INDEX.json")))["prompts"]
        for p in index_prompts:
            self.assertIn((p["id"], p["version"]), rows)  # every INDEX prompt present
        self.assertEqual(rows[("agent_operational_checklist", "1.0.0")], "production")  # live wins
