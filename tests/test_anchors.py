"""Tests for anchors.py — external anchoring of studio seals (Phase 5 Slice 3).

Everything is faked: temp repo root + temp ANCHORS.md, patched seal._th (hub
verify), patched subprocess (git). Tests never touch the live hub and never
run real git against the repo. Every failure branch must produce
anchored: False with a specific message — never an exception to the caller,
never a dirty git index, never a stray row left in ANCHORS.md.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import anchors
import seal

HEAD = "sha256:" + "ab" * 32
VERIFY = {"thread": "th_123", "slug": "ship-it", "records": 14,
          "head": HEAD, "valid": True, "problems": []}

HEADER = ("| anchored_at (ISO, UTC) | slug | head hash | records "
          "| hub thread id | note |\n|---|---|---|---|---|---|\n")


def _proc(rc=0, stderr="", stdout=""):
    p = MagicMock()
    p.returncode = rc
    p.stderr = stderr
    p.stdout = stdout
    return p


class AnchorTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="anchors-test-")
        self.path = os.path.join(self.repo, "ANCHORS.md")
        with open(self.path, "w") as f:
            f.write(HEADER)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        import shutil
        shutil.rmtree(self.repo, ignore_errors=True)

    def _content(self):
        with open(self.path) as f:
            return f.read()


class TestFormatRow(unittest.TestCase):
    def test_row_shape(self):
        row = anchors.format_row("2026-07-12T00:00:00Z", "ship-it", HEAD, 14,
                                 "th_123", "a caveat")
        self.assertEqual(
            row,
            f"| 2026-07-12T00:00:00Z | ship-it | {HEAD} | 14 | th_123 | a caveat |")

    def test_empty_note_cell(self):
        row = anchors.format_row("2026-07-12T00:00:00Z", "s", HEAD, 1, "t")
        self.assertTrue(row.endswith("| t |  |") or row.endswith("| t | |"))


class TestAnchorSealSuccess(AnchorTestCase):
    @patch("anchors.subprocess.run", return_value=_proc(0))
    @patch("seal._th", return_value=dict(VERIFY))
    def test_success_reports_anchored_and_pushed(self, mock_th, mock_run):
        result = anchors.anchor_seal("ship-it", repo_root=self.repo)
        self.assertEqual(result["anchored"], True)
        self.assertEqual(result["anchor_pushed"], True)
        self.assertNotIn("anchor_error", result)
        mock_th.assert_called_once_with("GET", "/t/ship-it/verify")

    @patch("anchors.subprocess.run", return_value=_proc(0))
    @patch("seal._th", return_value=dict(VERIFY))
    def test_success_appends_one_row(self, mock_th, mock_run):
        anchors.anchor_seal("ship-it", repo_root=self.repo)
        content = self._content()
        self.assertTrue(content.startswith(HEADER))
        rows = [l for l in content[len(HEADER):].splitlines() if l.strip()]
        self.assertEqual(len(rows), 1)
        self.assertIn("| ship-it |", rows[0])
        self.assertIn(f"| {HEAD} |", rows[0])
        self.assertIn("| 14 |", rows[0])
        self.assertIn("| th_123 |", rows[0])

    @patch("anchors.subprocess.run", return_value=_proc(0))
    @patch("seal._th", return_value=dict(VERIFY))
    def test_git_sequence_and_commit_message(self, mock_th, mock_run):
        anchors.anchor_seal("ship-it", repo_root=self.repo)
        calls = [c.args[0] for c in mock_run.call_args_list]
        self.assertEqual(calls[0][:2], ["git", "add"])
        self.assertIn("ANCHORS.md", calls[0])
        self.assertEqual(calls[1][:2], ["git", "commit"])
        self.assertIn("anchor: ship-it head " + "ab" * 6, calls[1])
        self.assertEqual(calls[2], ["git", "push"])
        for c in mock_run.call_args_list:
            self.assertEqual(c.kwargs.get("cwd"), self.repo)

    @patch("anchors.subprocess.run", return_value=_proc(0))
    @patch("seal._th", return_value=dict(VERIFY))
    def test_row_carries_note_when_given(self, mock_th, mock_run):
        anchors.anchor_seal("ship-it", repo_root=self.repo, note="a caveat")
        self.assertIn("| a caveat |", self._content())


class TestAnchorSealFailures(AnchorTestCase):
    @patch("anchors.subprocess.run")
    @patch("seal._th", side_effect=seal.SealError("ThreadHub is not reachable"))
    def test_verify_failure(self, mock_th, mock_run):
        result = anchors.anchor_seal("ship-it", repo_root=self.repo)
        self.assertEqual(result["anchored"], False)
        self.assertIn("verify", result["anchor_error"])
        self.assertIn("ThreadHub is not reachable", result["anchor_error"])
        mock_run.assert_not_called()          # no git activity
        self.assertEqual(self._content(), HEADER)  # no stray row

    @patch("anchors.subprocess.run")
    @patch("seal._th", return_value={"thread": "t", "records": 0, "head": None,
                                     "valid": True})
    def test_missing_head_fails(self, mock_th, mock_run):
        result = anchors.anchor_seal("empty", repo_root=self.repo)
        self.assertEqual(result["anchored"], False)
        self.assertIn("head", result["anchor_error"])
        mock_run.assert_not_called()

    @patch("anchors.subprocess.run")
    @patch("seal._th", return_value=dict(VERIFY))
    def test_missing_anchors_file_fails(self, mock_th, mock_run):
        os.remove(self.path)
        result = anchors.anchor_seal("ship-it", repo_root=self.repo)
        self.assertEqual(result["anchored"], False)
        self.assertIn("ANCHORS.md", result["anchor_error"])
        mock_run.assert_not_called()

    @patch("anchors.subprocess.run",
           return_value=_proc(128, stderr="fatal: not a git repository"))
    @patch("seal._th", return_value=dict(VERIFY))
    def test_add_failure_not_a_repo(self, mock_th, mock_run):
        result = anchors.anchor_seal("ship-it", repo_root=self.repo)
        self.assertEqual(result["anchored"], False)
        self.assertIn("git add failed", result["anchor_error"])
        self.assertIn("not a git repository", result["anchor_error"])
        # the appended row is rolled back — the file is exactly as it was
        self.assertEqual(self._content(), HEADER)

    @patch("seal._th", return_value=dict(VERIFY))
    def test_commit_failure_resets_index_and_file(self, mock_th):
        def fake_run(args, **kw):
            if args[:2] == ["git", "commit"]:
                return _proc(1, stderr="commit failed: no user.email")
            return _proc(0)

        with patch("anchors.subprocess.run", side_effect=fake_run) as mock_run:
            result = anchors.anchor_seal("ship-it", repo_root=self.repo)
        self.assertEqual(result["anchored"], False)
        self.assertIn("git commit failed", result["anchor_error"])
        self.assertIn("no user.email", result["anchor_error"])
        # index reset after failed commit: git reset -- ANCHORS.md was issued
        calls = [c.args[0] for c in mock_run.call_args_list]
        self.assertIn(["git", "reset", "--", "ANCHORS.md"], calls)
        # no push was attempted
        self.assertNotIn(["git", "push"], calls)
        # working tree restored — no stray row
        self.assertEqual(self._content(), HEADER)

    @patch("seal._th", return_value=dict(VERIFY))
    def test_push_failure_is_anchored_but_not_pushed(self, mock_th):
        def fake_run(args, **kw):
            if args[:2] == ["git", "push"]:
                return _proc(1, stderr="could not read from remote")
            return _proc(0)

        with patch("anchors.subprocess.run", side_effect=fake_run):
            result = anchors.anchor_seal("ship-it", repo_root=self.repo)
        # the LOCAL commit is the anchor's first witness; push makes it external
        self.assertEqual(result["anchored"], True)
        self.assertEqual(result["anchor_pushed"], False)
        self.assertIn("git push failed", result["anchor_push_error"])
        self.assertIn("could not read from remote", result["anchor_push_error"])
        self.assertNotIn("anchor_error", result)
        # the committed row stays — it is real testimony, locally witnessed
        self.assertIn("| ship-it |", self._content())

    @patch("anchors.subprocess.run", side_effect=FileNotFoundError("git"))
    @patch("seal._th", return_value=dict(VERIFY))
    def test_git_executable_missing(self, mock_th, mock_run):
        result = anchors.anchor_seal("ship-it", repo_root=self.repo)
        self.assertEqual(result["anchored"], False)
        self.assertIn("git", result["anchor_error"])
        self.assertEqual(self._content(), HEADER)

    @patch("anchors.subprocess.run",
           side_effect=subprocess.TimeoutExpired(["git", "add"], 60))
    @patch("seal._th", return_value=dict(VERIFY))
    def test_git_timeout(self, mock_th, mock_run):
        result = anchors.anchor_seal("ship-it", repo_root=self.repo)
        self.assertEqual(result["anchored"], False)
        self.assertIn("timed out", result["anchor_error"])
        self.assertEqual(self._content(), HEADER)

    @patch("anchors.subprocess.run")
    @patch("seal._th", side_effect=ValueError("totally unexpected"))
    def test_never_raises_even_on_unexpected_exception(self, mock_th, mock_run):
        result = anchors.anchor_seal("ship-it", repo_root=self.repo)
        self.assertEqual(result["anchored"], False)
        self.assertIn("totally unexpected", result["anchor_error"])


class TestAnchorsFileHeader(unittest.TestCase):
    """The seeded ANCHORS.md must state the weak proof honestly (rules 4.2/4.3)
    and never claim notarization."""

    def setUp(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "ANCHORS.md")
        with open(path) as f:
            self.text = f.read()

    def test_states_weak_timestamp_via_hosted_git(self):
        low = self.text.lower()
        self.assertIn("weak external timestamp", low)
        self.assertIn("git history", low)
        self.assertIn("push", low)

    def test_disclaims_notarization_and_canonicality(self):
        low = self.text.lower()
        self.assertIn("not cryptographic notarization", low)
        self.assertIn("never changes what is canonical", low)

    def test_table_header_columns(self):
        self.assertIn("| anchored_at (ISO, UTC) | slug | head hash | records "
                      "| hub thread id | note |", self.text)


if __name__ == "__main__":
    unittest.main()
