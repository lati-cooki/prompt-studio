import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

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
        handler.read_json_body = lambda: {
            "model": "claude-sonnet-4-6",
            "messages": [],
            "stream": True,
        }
        handler.send_json = MagicMock()

        with patch.dict(os.environ, {}, clear=True):
            handler.handle_post_chat()

        handler.send_json.assert_called_once()
        call_kwargs = handler.send_json.call_args
        self.assertEqual(
            call_kwargs.kwargs.get("status") or call_kwargs[1].get("status"), 503
        )
        self.assertIn("error", call_kwargs[0][0])

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
        import sqlite3

        handler = object.__new__(server.PromptStudioHandler)
        handler.send_json = MagicMock()
        handler.send_error = MagicMock()

        # Use a file-based temp DB so we can re-query after the handler closes its connection
        import tempfile, os

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            setup_conn = sqlite3.connect(db_path)
            setup_conn.row_factory = sqlite3.Row
            setup_conn.executescript("""
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
            setup_conn.close()

            handler.get_db = lambda: sqlite3.connect(
                db_path, detect_types=sqlite3.PARSE_DECLTYPES
            )

            handler.handle_post_prompt_validate("my_prompt", "1.1.0")

            verify_conn = sqlite3.connect(db_path)
            verify_conn.row_factory = sqlite3.Row
            row = verify_conn.execute(
                "SELECT status, eval_status FROM prompts WHERE id='my_prompt' AND version='1.1.0'"
            ).fetchone()
            verify_conn.close()
            self.assertEqual(row["status"], "production")
            self.assertEqual(row["eval_status"], "validated")
        finally:
            os.unlink(db_path)

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

    def test_anthropic_stream_error_concealed(self):
        import server

        handler = object.__new__(server.PromptStudioHandler)
        handler.read_json_body = lambda: {
            "provider": "anthropic",
            "model": "test-model",
            "messages": [{"role": "user", "content": "hello"}],
        }
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.send_json = MagicMock()
        handler._anthropic_clients = {}

        mock_client = MagicMock()
        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(
            side_effect=Exception("Super secret exception details")
        )
        mock_stream.__exit__ = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=mock_stream)

        written = []
        handler.wfile = MagicMock()
        handler.wfile.write = lambda b: written.append(b)
        handler.wfile.flush = MagicMock()

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("server.anthropic") as mock_anthropic:
                mock_anthropic.Anthropic = MagicMock(return_value=mock_client)
                handler.handle_post_chat()

        self.assertGreater(len(written), 0)
        chunk = json.loads(written[0].decode().removeprefix("data: ").strip())
        self.assertEqual(chunk["error"], "An internal error occurred.")
        self.assertNotIn("Super secret exception details", written[0].decode())
        self.assertIn(b"[DONE]", written[-1])

    def test_openai_compat_stream_error_concealed(self):
        import server

        handler = object.__new__(server.PromptStudioHandler)
        handler.read_json_body = lambda: {
            "provider": "openai",
            "model": "test-model",
            "messages": [{"role": "user", "content": "hello"}],
        }
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.send_json = MagicMock()

        written = []
        handler.wfile = MagicMock()
        handler.wfile.write = lambda b: written.append(b)
        handler.wfile.flush = MagicMock()

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_urlopen.side_effect = Exception(
                    "Top secret internal path /var/lib/..."
                )
                handler.handle_post_chat()

        self.assertGreater(len(written), 0)
        chunk = json.loads(written[0].decode().removeprefix("data: ").strip())
        self.assertEqual(chunk["error"], "An internal error occurred.")
        self.assertNotIn("Top secret internal path", written[0].decode())
        self.assertIn(b"[DONE]", written[-1])
