"""Tests for the one-shot append-only attribution correction script.

Everything is faked: temp DB, temp eval file, patched seal._th. The script
must NEVER write to the live hub from tests — and by default (--dry-run) it
must not write at all.
"""
import hashlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import correct_attribution as ca

SCHEMA = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "schema.sql")).read()


class TestBuildCorrectionEvent(unittest.TestCase):
    def test_event_shape(self):
        event = ca.build_correction_event("eval_file.json", "sha256:abc123")
        self.assertEqual(event["event_type"], "ContributionAttributionCorrected")
        corr = event["payload"]["attributionCorrection"]
        self.assertIsNone(corr["attributionId"])  # no ContributionAttributed exists
        self.assertTrue(corr["id"])
        self.assertIn("delegate", corr["reason"])
        self.assertEqual(corr["evidence"]["file"], "eval_file.json")
        self.assertEqual(corr["evidence"]["content_hash"], "sha256:abc123")
        self.assertEqual(corr["correctedAttribution"]["graded_by"], "delegate")
        self.assertEqual(corr["correctedAttribution"]["delegated_by"], "operator")

    def test_conformance_disclosure_is_explicit(self):
        event = ca.build_correction_event("f.json", "sha256:x")
        conformance = event["payload"]["conformance"]
        self.assertIn("no in-thread ContributionAttributed exists", conformance)
        self.assertIn("attributionId: null", conformance)
        self.assertIn("disclosed nonconformance", conformance)

    def test_delegate_note_acknowledges_grading(self):
        note = ca.build_delegate_note()
        self.assertIn("A-", note["text"])
        self.assertIn("agent_operational_checklist", note["text"])


class TestContentHash(unittest.TestCase):
    def test_hash_is_sha256_over_raw_bytes(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            f.write(b'{"grade": "A-"}')
            path = f.name
        try:
            expected = "sha256:" + hashlib.sha256(b'{"grade": "A-"}').hexdigest()
            self.assertEqual(ca.content_hash(path), expected)
        finally:
            os.unlink(path)


class ScriptTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "studio.db")
        conn = sqlite3.connect(self.db)
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO writers (name, threadhub_id, display_name, kind, custodial)"
            " VALUES (?,?,?,?,1)",
            [("operator", "id_troy", "Troy", "human"),
             ("delegate", "id_del", "Claude (delegate)", "agent")])
        conn.commit()
        conn.close()
        self.eval_file = os.path.join(self.tmp.name, "eval_agent_data.json")
        with open(self.eval_file, "w") as f:
            f.write('{"grade": "A-"}')

    def tearDown(self):
        self.tmp.cleanup()

    def _args(self, *extra):
        return ["--db", self.db, "--eval-file", self.eval_file] + list(extra)


class TestDryRunDefault(ScriptTestCase):
    def test_default_is_dry_run_nothing_written(self):
        with patch("seal._th") as th, redirect_stdout(io.StringIO()):
            rc = ca.main(self._args())
        th.assert_not_called()  # no mint, no record append — nothing at all
        self.assertEqual(rc, 0)

    def test_dry_run_prints_record_thread_and_author(self):
        buf = io.StringIO()
        with patch("seal._th") as th, redirect_stdout(buf):
            ca.main(self._args())
        out = buf.getvalue()
        self.assertIn("DRY RUN", out)
        self.assertIn(ca.THREAD_SLUG, out)
        self.assertIn("id_troy", out)
        self.assertIn("ContributionAttributionCorrected", out)
        expected_hash = "sha256:" + hashlib.sha256(b'{"grade": "A-"}').hexdigest()
        self.assertIn(expected_hash, out)


class TestPreSlice2Db(unittest.TestCase):
    """The live DB copy may predate slice 2 (no writers table until the server
    reboots on new code) — the script must handle that, not crash."""

    def test_dry_run_on_db_without_writers_table(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "old.db")
            sqlite3.connect(db).close()  # empty DB, no tables at all
            eval_file = os.path.join(d, "eval.json")
            with open(eval_file, "w") as f:
                f.write('{"grade": "A-"}')
            buf = io.StringIO()
            with patch("seal._th") as th, redirect_stdout(buf):
                rc = ca.main(["--db", db, "--eval-file", eval_file])
            th.assert_not_called()
            self.assertEqual(rc, 0)
            self.assertIn("unprovisioned", buf.getvalue())
            # dry run is fully read-only: it must not even heal the schema
            tables = {r[0] for r in sqlite3.connect(db).execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("writers", tables)


class TestExecute(ScriptTestCase):
    def test_execute_appends_correction_authored_by_operator(self):
        with patch("seal._th",
                   return_value={"record_hash": "sha256:r1", "seq": 9}) as th, \
             redirect_stdout(io.StringIO()):
            rc = ca.main(self._args("--execute"))
        self.assertEqual(rc, 0)
        th.assert_called_once()
        method, path, body = th.call_args[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, f"/t/{ca.THREAD_SLUG}/records")
        self.assertEqual(body["author"], "id_troy")  # operator identity
        self.assertEqual(body["kind"], "clista.event")
        event = body["payload"]
        self.assertEqual(event["event_type"], "ContributionAttributionCorrected")
        self.assertIsNone(event["payload"]["attributionCorrection"]["attributionId"])
        self.assertEqual(
            event["payload"]["attributionCorrection"]["evidence"]["content_hash"],
            "sha256:" + hashlib.sha256(b'{"grade": "A-"}').hexdigest())

    def test_execute_with_delegate_note_appends_delegate_keyed_record(self):
        with patch("seal._th",
                   side_effect=[{"record_hash": "sha256:r1", "seq": 9},
                                {"record_hash": "sha256:r2", "seq": 10}]) as th, \
             redirect_stdout(io.StringIO()):
            rc = ca.main(self._args("--execute", "--with-delegate-note"))
        self.assertEqual(rc, 0)
        self.assertEqual(th.call_count, 2)
        _, _, note_body = th.call_args_list[1][0]
        self.assertEqual(note_body["author"], "id_del")  # first delegate-keyed record
        self.assertEqual(note_body["kind"], "note")
        self.assertIn("A-", note_body["payload"]["text"])

    def test_execute_never_routes_through_clista_validate(self):
        # deliberate bypass: attributionId is null, the strict validator would
        # reject it — the script must disclose, not validate-and-fail (or fake).
        with patch("seal._th", return_value={"record_hash": "sha256:r1", "seq": 9}), \
             patch("seal.subprocess.run") as run, redirect_stdout(io.StringIO()):
            ca.main(self._args("--execute"))
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
