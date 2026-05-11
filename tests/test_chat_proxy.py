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
        handler.read_json_body = lambda: {"model": "claude-sonnet-4-6", "messages": [], "stream": True}
        handler.send_error = MagicMock()

        with patch.dict(os.environ, {}, clear=True):
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
