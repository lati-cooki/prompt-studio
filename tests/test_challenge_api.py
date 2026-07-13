"""Route tests for the Challenge Run API (Phase 5 Wave 3 / Slice 7).

POST /api/challenge          — validate (fail-closed 409/422) + spawn the job
GET  /api/challenge/<job_id> — poll the job snapshot
GET  /api/challenge/demo     — the built-in fraud-threshold demo scenario

Follows tests/test_promotions_api.py's MockHandler pattern (shared-cache
in-memory SQLite so state persists across handler instances). The worker
thread itself is never started here — challenge.start_job is patched; the
orchestration is covered by tests/test_challenge.py.
"""
import io
import json
import os
import sqlite3
import sys
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import challenge
import server

SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")


class MockHandler(server.PromptStudioHandler):
    def __init__(self, db_uri):
        self.db_uri = db_uri
        self._last_status = None
        self._body_written = b""
        self._mock_headers = {}
        self._mock_rfile = io.BytesIO(b"")

    def get_db(self):
        conn = sqlite3.connect(self.db_uri, uri=True)
        conn.row_factory = sqlite3.Row
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

    def _json(self):
        return json.loads(self._body_written.decode("utf-8"))


class ChallengeApiTestCase(unittest.TestCase):
    def setUp(self):
        self.db_uri = f"file:challenge_api_{uuid.uuid4().hex}?mode=memory&cache=shared"
        self._keeper = sqlite3.connect(self.db_uri, uri=True)
        with open(SCHEMA_PATH) as f:
            self._keeper.executescript(f.read())
        self._keeper.commit()

    def tearDown(self):
        self._keeper.close()

    def _handler(self):
        return MockHandler(self.db_uri)

    def _seed(self, status="production", promotion=True):
        self._keeper.execute(
            "INSERT INTO prompts (id, version, status, body) VALUES (?,?,?,?)",
            ("fraud-analyst", "1.0.0", status, "body"))
        if promotion:
            self._keeper.execute(
                """INSERT INTO promotions (prompt_id, version, state, opened_at,
                   closes_at, resolved_at, thread_slug, sealed)
                   VALUES ('fraud-analyst','1.0.0','promoted',
                   '2026-07-09T00:00:00Z','2026-07-10T00:00:00Z',
                   '2026-07-10T00:00:00Z','fraud-analyst-promo',1)""")
        self._keeper.commit()

    def _post(self, body):
        h = self._handler()
        h.path = "/api/challenge"
        h._set_body(json.dumps(body).encode("utf-8"))
        h.do_POST()
        return h

    def _request_body(self):
        return {
            "scenario": "Raise the threshold?",
            "roles": {
                "maker": {"prompt_id": "fraud-analyst", "version": "1.0.0"},
                "checker": {"prompt_id": "fraud-analyst", "version": "1.0.0"},
            },
        }

    def test_post_valid_spawns_job(self):
        self._seed()
        captured = {}

        def fake_start(cfg):
            captured["cfg"] = cfg
            return "job-123"

        with patch.object(challenge, "start_job", fake_start):
            h = self._post(self._request_body())
        self.assertEqual(h._last_status, 202)
        self.assertEqual(h._json()["job_id"], "job-123")
        self.assertEqual(captured["cfg"]["rounds"], challenge.DEFAULT_ROUNDS)
        self.assertEqual(captured["cfg"]["roles"]["maker"]["model"],
                         challenge.DEFAULT_MODEL)

    def test_post_non_production_prompt_is_409_and_never_spawns(self):
        self._seed(status="draft")
        with patch.object(challenge, "start_job") as start:
            h = self._post(self._request_body())
        self.assertEqual(h._last_status, 409)
        self.assertIn("not production", h._json()["error"])
        start.assert_not_called()

    def test_post_missing_promotion_is_409(self):
        self._seed(promotion=False)
        with patch.object(challenge, "start_job") as start:
            h = self._post(self._request_body())
        self.assertEqual(h._last_status, 409)
        start.assert_not_called()

    def test_post_bad_rounds_is_422(self):
        self._seed()
        body = self._request_body()
        body["rounds"] = 99
        h = self._post(body)
        self.assertEqual(h._last_status, 422)

    def test_get_job_snapshot(self):
        job_id = challenge.create_job({"rounds": 2})
        challenge.job_event(job_id, "PositionTaken", "MAKER", "position")
        h = self._handler()
        h.path = f"/api/challenge/{job_id}"
        h.do_GET()
        self.assertEqual(h._last_status, 200)
        snap = h._json()
        self.assertEqual(snap["id"], job_id)
        self.assertEqual(snap["status"], "running")
        self.assertEqual(len(snap["events"]), 1)

    def test_get_unknown_job_is_404(self):
        h = self._handler()
        h.path = "/api/challenge/definitely-not-a-job"
        h.do_GET()
        self.assertEqual(h._last_status, 404)

    def test_get_demo_scenario(self):
        h = self._handler()
        h.path = "/api/challenge/demo"
        h.do_GET()
        self.assertEqual(h._last_status, 200)
        body = h._json()
        self.assertIn("fraud model auto-declines", body["scenario"])
        self.assertIn("genesis_prompt.md", body["source"])
        self.assertEqual(body["defaults"]["model"], challenge.DEFAULT_MODEL)
        self.assertEqual(body["defaults"]["provider"], challenge.DEFAULT_PROVIDER)
        self.assertEqual(body["defaults"]["rounds"], challenge.DEFAULT_ROUNDS)
        self.assertEqual(body["defaults"]["max_rounds"], challenge.MAX_ROUNDS)


if __name__ == "__main__":
    unittest.main()
