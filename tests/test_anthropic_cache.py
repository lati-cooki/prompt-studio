import unittest
from unittest.mock import patch, MagicMock
import server

class DummyReq:
    def makefile(self, *args, **kwargs):
        class DummyFile:
            def readline(self, *a, **k): return b""
            def write(self, *a, **k): pass
            def flush(self): pass
            def close(self): pass
            def read(self, *a, **k): return b""
        return DummyFile()
    def sendall(self, *args, **kwargs): pass

class DummyServer:
    pass

class TestAnthropicCache(unittest.TestCase):
    def setUp(self):
        server.PromptStudioHandler._anthropic_clients.clear()

    @patch('server.anthropic')
    @patch('os.environ.get')
    def test_anthropic_client_reused(self, mock_env_get, mock_anthropic):
        # Setup mock environment
        mock_env_get.return_value = 'dummy_key'
        mock_anthropic.Anthropic = MagicMock()

        # Create handler instance
        handler = server.PromptStudioHandler(DummyReq(), ('127.0.0.1', 8080), DummyServer())
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = DummyReq().makefile()

        # Mock the stream context manager
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_stream = MagicMock()
        mock_stream.text_stream = ["test chunk"]
        mock_msg = MagicMock()
        mock_msg.usage.input_tokens = 10
        mock_msg.usage.output_tokens = 20
        mock_stream.get_final_message.return_value = mock_msg

        mock_client.messages.stream.return_value.__enter__.return_value = mock_stream

        # First call should instantiate Anthropic
        handler._stream_anthropic("model_id", [{"role": "user", "content": "hi"}])
        mock_anthropic.Anthropic.assert_called_once_with(api_key='dummy_key')

        # Reset mock to check if it's called again
        mock_anthropic.Anthropic.reset_mock()

        # Second call should reuse the client
        handler._stream_anthropic("model_id", [{"role": "user", "content": "hello"}])
        mock_anthropic.Anthropic.assert_not_called()

if __name__ == '__main__':
    unittest.main()
