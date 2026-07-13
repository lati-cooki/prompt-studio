"""Tests for scripts/anchor_backfill.py — retroactive anchor rows.

Everything is faked: fetch_json is patched with a fake hub, ANCHORS.md is a
temp file. The script must never git-commit, must be idempotent by
(slug, head), must only ever APPEND (never edit an existing row), and must be
a pure dry run unless --execute is passed.
"""
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import anchor_backfill as ab

HEADER = ("# Anchors\n\nheader prose\n\n"
          "| anchored_at (ISO, UTC) | slug | head hash | records "
          "| hub thread id | note |\n|---|---|---|---|---|---|\n")

HEAD_A = "sha256:" + "aa" * 32
HEAD_B = "sha256:" + "bb" * 32

THREADS = [
    {"id": "th_1", "slug": "founding", "title": "Founding"},
    {"id": "th_2", "slug": "phase-4-ships", "title": "Phase 4"},
]
VERIFIES = {
    "founding": {"thread": "th_1", "slug": "founding", "records": 14,
                 "head": HEAD_A, "valid": True},
    "phase-4-ships": {"thread": "th_2", "slug": "phase-4-ships", "records": 9,
                      "head": HEAD_B, "valid": True},
}
# Record envelopes (GET /t/<slug>.json): founding is legacy single-custodial-
# author era; phase-4-ships has distinct per-record writers (post-provisioning).
RECORDS = {
    "founding": [{"seq": 0, "author": "id_studio"},
                 {"seq": 1, "author": "id_studio"},
                 {"seq": 2, "author": "id_studio"}],
    "phase-4-ships": [{"seq": 0, "author": "id_operator"},
                      {"seq": 1, "author": "id_grader"},
                      {"seq": 2, "author": "id_objector"},
                      {"seq": 3, "author": "id_operator"}],
}


def fake_fetch(url):
    if url.endswith("/threads"):
        return [dict(t) for t in THREADS]
    if url.endswith(".json"):
        slug = url.split("/t/")[1].rsplit(".json", 1)[0]
        return [dict(r) for r in RECORDS[slug]]
    slug = url.split("/t/")[1].split("/verify")[0]
    return dict(VERIFIES[slug])


class BackfillTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix="-ANCHORS.md")
        os.close(fd)
        with open(self.path, "w") as f:
            f.write(HEADER)
        self.addCleanup(os.remove, self.path)

    def _content(self):
        with open(self.path) as f:
            return f.read()

    def _run(self, *extra):
        out = StringIO()
        with patch("scripts.anchor_backfill.fetch_json", side_effect=fake_fetch):
            with redirect_stdout(out), redirect_stderr(out):
                rc = ab.main(["--anchors", self.path, *extra])
        return rc, out.getvalue()


class TestDryRun(BackfillTestCase):
    def test_dry_run_is_default_and_writes_nothing(self):
        rc, out = self._run()
        self.assertEqual(rc, 0)
        self.assertEqual(self._content(), HEADER)  # untouched
        self.assertIn("DRY RUN", out)
        self.assertIn("founding", out)
        self.assertIn("phase-4-ships", out)
        self.assertIn(HEAD_A, out)
        self.assertIn("--execute", out)

    def test_dry_run_never_invokes_git(self):
        with patch("subprocess.run") as mock_run:
            self._run()
        mock_run.assert_not_called()


class TestExecute(BackfillTestCase):
    def test_execute_appends_rows_for_all_threads(self):
        rc, out = self._run("--execute")
        self.assertEqual(rc, 0)
        content = self._content()
        self.assertTrue(content.startswith(HEADER))  # header never edited
        rows = [l for l in content[len(HEADER):].splitlines() if l.strip()]
        self.assertEqual(len(rows), 2)
        self.assertIn(f"| founding | {HEAD_A} | 14 | th_1 |", rows[0])
        self.assertIn(f"| phase-4-ships | {HEAD_B} | 9 | th_2 |", rows[1])

    def test_note_invariant_parts_on_every_row(self):
        # the two-timestamp honesty never varies, whatever the custody regime
        self._run("--execute")
        for row in self._content()[len(HEADER):].splitlines():
            self.assertIn("retroactive backfill;", row)
            self.assertIn("anchored_at is the backfill time, not the seal time",
                          row)

    def test_single_author_thread_gets_derived_single_author_clause(self):
        # custody is DERIVED from the records, never asserted — including the
        # parenthetical: "(one distinct record author)" is observed fact, not
        # an era claim (a post-provisioning thread can legitimately have one
        # distinct author, e.g. operator-only waived promotions)
        self._run("--execute")
        founding = [r for r in self._content().splitlines()
                    if "| founding |" in r][0]
        self.assertIn("sealed under single custodial author id_studio "
                      "(one distinct record author)", founding)
        self.assertNotIn("per-record authors", founding)
        self.assertNotIn("era", founding)  # no asserted-era wording anywhere

    def test_multi_author_thread_gets_per_record_clause(self):
        # a post-provisioning thread must NOT testify to single-author custody
        self._run("--execute")
        p4 = [r for r in self._content().splitlines()
              if "| phase-4-ships |" in r][0]
        self.assertIn("per-record authors (3 distinct); custody regime "
                      "legible per record (DR 5.3)", p4)
        self.assertNotIn("single custodial author", p4)
        self.assertNotIn("pre-Phase-5", p4)
        self.assertNotIn("era", p4)

    def test_execute_never_invokes_git(self):
        # the controller makes the one retroactive commit, not the script
        with patch("subprocess.run") as mock_run:
            self._run("--execute")
        mock_run.assert_not_called()


class TestIdempotency(BackfillTestCase):
    def test_second_run_appends_nothing(self):
        self._run("--execute")
        first = self._content()
        rc, out = self._run("--execute")
        self.assertEqual(rc, 0)
        self.assertEqual(self._content(), first)
        self.assertIn("already anchored", out)

    def test_new_head_appends_new_row_and_never_edits_old(self):
        self._run("--execute")
        first = self._content()
        moved = "sha256:" + "cc" * 32

        def fetch_moved(url):
            resp = fake_fetch(url)
            if url.endswith("/t/founding/verify"):
                resp = dict(resp, head=moved, records=15)
            return resp

        out = StringIO()
        with patch("scripts.anchor_backfill.fetch_json", side_effect=fetch_moved):
            with redirect_stdout(out):
                rc = ab.main(["--anchors", self.path, "--execute"])
        self.assertEqual(rc, 0)
        content = self._content()
        # append-only: the previous file is a byte-for-byte prefix
        self.assertTrue(content.startswith(first))
        new_rows = [l for l in content[len(first):].splitlines() if l.strip()]
        self.assertEqual(len(new_rows), 1)
        self.assertIn(f"| founding | {moved} | 15 | th_1 |", new_rows[0])
        # the old founding row (old head) is still there, untouched
        self.assertIn(f"| founding | {HEAD_A} | 14 | th_1 |", content)

    def test_dry_run_after_execute_reports_nothing_to_add(self):
        self._run("--execute")
        rc, out = self._run()
        self.assertEqual(rc, 0)
        self.assertIn("Would add 0 row(s)", out)
        self.assertIn("2 already anchored", out)
        self.assertNotIn(HEAD_A, out)  # nothing listed to add


class TestEdgeCases(BackfillTestCase):
    def test_headless_thread_is_skipped_with_notice(self):
        def fetch(url):
            if url.endswith("/threads"):
                return [{"id": "th_9", "slug": "empty-thread"}]
            return {"thread": "th_9", "slug": "empty-thread", "records": 0,
                    "head": None, "valid": True}

        out = StringIO()
        with patch("scripts.anchor_backfill.fetch_json", side_effect=fetch):
            with redirect_stdout(out):
                rc = ab.main(["--anchors", self.path, "--execute"])
        self.assertEqual(rc, 0)
        self.assertEqual(self._content(), HEADER)
        self.assertIn("empty-thread", out.getvalue())
        self.assertIn("no head", out.getvalue())

    def test_missing_anchors_file_errors_instead_of_creating_headerless(self):
        os.remove(self.path)
        try:
            rc, out = self._run("--execute")
            self.assertNotEqual(rc, 0)
            self.assertFalse(os.path.exists(self.path))
        finally:
            with open(self.path, "w") as f:  # recreate for addCleanup
                f.write(HEADER)

    def test_fetch_failure_mid_run_is_clean_and_writes_nothing(self):
        # a hub hiccup must name the thread and the failure, exit nonzero
        # without a traceback, and — because rows are gathered before any
        # write — append nothing
        def fetch(url):
            if url.endswith("/threads"):
                return [dict(t) for t in THREADS]
            if "/t/founding" in url:
                return (dict(VERIFIES["founding"]) if url.endswith("/verify")
                        else [dict(r) for r in RECORDS["founding"]])
            raise ab.urllib.error.URLError("connection refused")

        out, err = StringIO(), StringIO()
        with patch("scripts.anchor_backfill.fetch_json", side_effect=fetch):
            with redirect_stdout(out), redirect_stderr(err):
                rc = ab.main(["--anchors", self.path, "--execute"])
        self.assertNotEqual(rc, 0)
        self.assertIn("phase-4-ships", err.getvalue())       # which thread
        self.assertIn("connection refused", err.getvalue())  # what failed
        self.assertNotIn("Traceback", err.getvalue())
        self.assertEqual(self._content(), HEADER)            # nothing written

    def test_existing_keys_ignores_header_and_separator(self):
        keys = ab.existing_keys(self.path)
        self.assertEqual(keys, set())
        with open(self.path, "a") as f:
            f.write(f"| 2026-07-12T00:00:00Z | s | {HEAD_A} | 3 | th | n |\n")
        self.assertEqual(ab.existing_keys(self.path), {("s", HEAD_A)})


if __name__ == "__main__":
    unittest.main()
