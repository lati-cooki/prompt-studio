import unittest
import urllib.request
import urllib.error
import subprocess
import time
import os
import signal
import socket

class TestSecurityFix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Start the server
        cls.server_process = subprocess.Popen(['python3', 'server.py'],
                                             stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE)
        # Wait for the server to start by polling the port
        timeout = 10
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with socket.create_connection(("localhost", 8000), timeout=1):
                    break
            except (socket.timeout, ConnectionRefusedError):
                time.sleep(0.5)
        else:
            cls.tearDownClass()
            print(cls.server_process.stderr.read())
            print(cls.server_process.stdout.read())
            raise RuntimeError("Server failed to start within timeout")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'server_process'):
            os.kill(cls.server_process.pid, signal.SIGTERM)
            cls.server_process.wait()

    def test_static_files_not_accessible_get(self):
        # Test that sensitive files are not accessible via GET
        files = ['server.py', 'prompt_studio.db', 'schema.sql', 'README.md']
        for file in files:
            url = f'http://localhost:8000/{file}'
            with self.subTest(file=file, method='GET'):
                try:
                    urllib.request.urlopen(url)
                    self.fail(f"File {file} should not be accessible via GET")
                except urllib.error.HTTPError as e:
                    self.assertEqual(e.code, 404, f"File {file} should return 404 for GET, but got {e.code}")

    def test_static_files_not_accessible_head(self):
        # Test that sensitive files are not accessible via HEAD
        files = ['server.py', 'prompt_studio.db', 'schema.sql', 'README.md']
        for file in files:
            url = f'http://localhost:8000/{file}'
            with self.subTest(file=file, method='HEAD'):
                req = urllib.request.Request(url, method='HEAD')
                try:
                    urllib.request.urlopen(req)
                    self.fail(f"File {file} should not be accessible via HEAD")
                except urllib.error.HTTPError as e:
                    self.assertEqual(e.code, 404, f"File {file} should return 404 for HEAD, but got {e.code}")

    def test_api_endpoints_accessible(self):
        # Test that API endpoints are still accessible
        endpoints = ['/api/sessions', '/api/prompts']
        for endpoint in endpoints:
            url = f'http://localhost:8000{endpoint}'
            with self.subTest(endpoint=endpoint):
                try:
                    response = urllib.request.urlopen(url)
                    self.assertEqual(response.getcode(), 200, f"Endpoint {endpoint} should be accessible")
                except urllib.error.HTTPError as e:
                    self.fail(f"Endpoint {endpoint} should be accessible, but got {e.code}")

class TestCors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = os.environ.copy()
        env['ALLOWED_ORIGIN'] = 'http://localhost:7777'
        env['PORT'] = '8001' # Run on a different port to avoid conflicts
        cls.server_process = subprocess.Popen(['python3', 'server.py'],
                                             stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE,
                                             env=env)
        # Wait for the server to start by polling the port
        timeout = 10
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with socket.create_connection(("localhost", 8001), timeout=1):
                    break
            except (socket.timeout, ConnectionRefusedError):
                time.sleep(0.5)
        else:
            cls.tearDownClass()
            raise RuntimeError("Server failed to start within timeout")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'server_process'):
            os.kill(cls.server_process.pid, signal.SIGTERM)
            cls.server_process.wait()

    def test_cors_header(self):
        url = 'http://localhost:8001/api/prompts'
        req = urllib.request.Request(url, method='OPTIONS')
        try:
            response = urllib.request.urlopen(req)
            self.assertEqual(response.getheader('Access-Control-Allow-Origin'), 'http://localhost:7777')
        except urllib.error.HTTPError as e:
            self.fail(f"OPTIONS request failed: {e}")

if __name__ == '__main__':
    unittest.main()
