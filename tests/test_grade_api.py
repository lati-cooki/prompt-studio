"""POST /api/evals/<eval_id>/grade — grading is an act with an actor.

Uses the MockHandler pattern from test_promotions_api; all hub traffic is faked.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server

try:
    from tests.test_promotions_api import MockHandler  # python3 -m unittest tests.test_grade_api
except ImportError:
    from test_promotions_api import MockHandler  # unittest discover -s tests

SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")


class GradeApiTestCase(unittest.TestCase):
    def setUp(self):
        self.db_uri = f"file:grade_api_{uuid.uuid4().hex}?mode=memory&cache=shared"
        self.anchor = sqlite3.connect(self.db_uri, uri=True)
        self.anchor.row_factory = sqlite3.Row
        with open(SCHEMA_PATH) as f:
            self.anchor.executescript(f.read())
        self.anchor.commit()
        self.evals_dir = tempfile.TemporaryDirectory()
        self._evals_patch = patch.object(server, "EVALS_DIR", self.evals_dir.name)
        self._evals_patch.start()
        self._seed_eval("eval_p1_v1_0_0_x")

    def tearDown(self):
        self._evals_patch.stop()
        self.evals_dir.cleanup()
        self.anchor.close()

    def _seed_eval(self, eval_id):
        with open(os.path.join(self.evals_dir.name, f"{eval_id}_data.json"), "w") as f:
            json.dump({"id": eval_id, "model": "m", "grade": None, "notes": ""}, f)
        with open(os.path.join(self.evals_dir.name, f"{eval_id}.md"), "w") as f:
            f.write("# Eval\n\n## Grade\n\n<!-- fill in -->\n")

    def _grade(self, eval_id, body):
        h = MockHandler(self.db_uri)
        h.path = f"/api/evals/{eval_id}/grade"
        h._set_body(json.dumps(body).encode())
        h.do_POST()
        return h

    def test_grade_stamps_actor_into_artifacts(self):
        with patch("seal._th", return_value={"id": "id_del1"}) as th:
            h = self._grade("eval_p1_v1_0_0_x",
                            {"grade": "A-", "notes": "solid", "writer": "delegate"})
        self.assertEqual(h._last_status, 200)
        out = h._json()
        self.assertEqual(out["grade"], "A-")
        self.assertEqual(out["graded_by"], "delegate")
        self.assertTrue(out["graded_at"])
        # writer was resolved through writers.py (minted once, custodial)
        th.assert_called_once_with("POST", "/identities",
                                   {"display_name": "Claude (delegate)", "kind": "agent"})
        row = self.anchor.execute("SELECT * FROM writers WHERE name='delegate'").fetchone()
        self.assertEqual(row["threadhub_id"], "id_del1")
        data = json.load(open(os.path.join(self.evals_dir.name,
                                           "eval_p1_v1_0_0_x_data.json")))
        self.assertEqual(data["graded_by"], "delegate")
        md = open(os.path.join(self.evals_dir.name, "eval_p1_v1_0_0_x.md")).read()
        self.assertIn("delegate", md)

    def test_writer_defaults_to_operator(self):
        with patch("seal._th", return_value={"id": "id_troy1"}) as th:
            h = self._grade("eval_p1_v1_0_0_x", {"grade": "B"})
        self.assertEqual(h._last_status, 200)
        self.assertEqual(h._json()["graded_by"], "operator")
        th.assert_called_once_with("POST", "/identities",
                                   {"display_name": "Troy", "kind": "human"})

    def test_unknown_writer_is_422_and_nothing_stamped(self):
        with patch("seal._th") as th:
            h = self._grade("eval_p1_v1_0_0_x", {"grade": "A", "writer": "rando"})
            th.assert_not_called()
        self.assertEqual(h._last_status, 422)
        data = json.load(open(os.path.join(self.evals_dir.name,
                                           "eval_p1_v1_0_0_x_data.json")))
        self.assertIsNone(data["grade"])

    def test_missing_grade_is_422(self):
        with patch("seal._th"):
            h = self._grade("eval_p1_v1_0_0_x", {"writer": "operator"})
        self.assertEqual(h._last_status, 422)

    def test_unknown_eval_is_404(self):
        with patch("seal._th", return_value={"id": "id_troy1"}):
            h = self._grade("eval_missing", {"grade": "A"})
        self.assertEqual(h._last_status, 404)

    def test_regrade_is_409(self):
        with patch("seal._th", return_value={"id": "id_troy1"}):
            self._grade("eval_p1_v1_0_0_x", {"grade": "A-"})
            h = self._grade("eval_p1_v1_0_0_x", {"grade": "A"})
        self.assertEqual(h._last_status, 409)

    def test_bad_eval_id_is_400(self):
        with patch("seal._th"):
            h = self._grade("..%2Fetc", {"grade": "A"})
        self.assertEqual(h._last_status, 400)


if __name__ == "__main__":
    unittest.main()
