import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import promotion_evidence as pe


def write_eval(d, name, payload):
    path = os.path.join(d, name)
    with open(path, "w") as f:
        json.dump(payload, f)
    return path


class TestPinEvidence(unittest.TestCase):
    def test_none_when_no_eval_exists(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(pe.pin_evidence("p1", "1.0.0", evals_dir=d))

    def test_pins_latest_matching_eval(self):
        with tempfile.TemporaryDirectory() as d:
            write_eval(d, "eval_p1_v1_0_0_2026-06-01_m_data.json",
                       {"model": "old", "tokens": {"total": 1}})
            newer = write_eval(d, "eval_p1_v1_0_0_2026-07-01_m_data.json",
                               {"model": "claude-sonnet-4-6", "tokens": {"total": 2},
                                "date": "2026-07-01"})
            os.utime(newer, None)  # ensure newest mtime
            out = pe.pin_evidence("p1", "1.0.0", evals_dir=d)
            self.assertEqual(out["model"], "claude-sonnet-4-6")
            self.assertEqual(out["source_file"], "eval_p1_v1_0_0_2026-07-01_m_data.json")
            self.assertTrue(out["content_hash"].startswith("sha256:"))
            self.assertIn("evaluate_prompt.py", out["rerun"])

    def test_hash_is_over_file_bytes_and_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            write_eval(d, "eval_p1_v1_0_0_x_data.json", {"model": "m"})
            a = pe.pin_evidence("p1", "1.0.0", evals_dir=d)
            b = pe.pin_evidence("p1", "1.0.0", evals_dir=d)
            self.assertEqual(a["content_hash"], b["content_hash"])

    def test_other_prompts_evals_not_matched(self):
        with tempfile.TemporaryDirectory() as d:
            write_eval(d, "eval_OTHER_v1_0_0_x_data.json", {"model": "m"})
            self.assertIsNone(pe.pin_evidence("p1", "1.0.0", evals_dir=d))

    def test_pin_returns_grade_and_graded_by(self):
        with tempfile.TemporaryDirectory() as d:
            write_eval(d, "eval_p1_v1_0_0_x_data.json",
                       {"model": "m", "grade": "A-", "graded_by": "delegate"})
            out = pe.pin_evidence("p1", "1.0.0", evals_dir=d)
            self.assertEqual(out["grade"], "A-")
            self.assertEqual(out["graded_by"], "delegate")

    def test_pin_ungraded_eval_has_null_grade_fields(self):
        with tempfile.TemporaryDirectory() as d:
            write_eval(d, "eval_p1_v1_0_0_x_data.json", {"model": "m"})
            out = pe.pin_evidence("p1", "1.0.0", evals_dir=d)
            self.assertIsNone(out["grade"])
            self.assertIsNone(out["graded_by"])


class TestGradeEval(unittest.TestCase):
    """Grading is an act with an actor: grade_eval stamps graded_by/graded_at
    append-only — new keys and appended lines, never rewritten values."""

    def _seed(self, d, grade=None, notes="", graded_by=None):
        payload = {"id": "eval_x", "model": "m", "grade": grade, "notes": notes,
                   "response": "r"}
        if graded_by:
            payload["graded_by"] = graded_by
        write_eval(d, "eval_x_data.json", payload)
        with open(os.path.join(d, "eval_x.md"), "w") as f:
            f.write("# Eval\n\n## Grade\n\n<!-- fill in -->\n")

    def test_stamps_grade_graded_by_and_graded_at(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            out = pe.grade_eval("eval_x", "A-", "solid run", "delegate", evals_dir=d)
            self.assertEqual(out["grade"], "A-")
            self.assertEqual(out["graded_by"], "delegate")
            self.assertTrue(out["graded_at"])
            data = json.load(open(os.path.join(d, "eval_x_data.json")))
            self.assertEqual(data["grade"], "A-")
            self.assertEqual(data["graded_by"], "delegate")
            self.assertEqual(data["notes"], "solid run")
            self.assertEqual(data["response"], "r")  # existing fields untouched

    def test_md_gains_appended_grade_line_without_rewrite(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            before = open(os.path.join(d, "eval_x.md")).read()
            pe.grade_eval("eval_x", "B+", None, "operator", evals_dir=d)
            after = open(os.path.join(d, "eval_x.md")).read()
            self.assertTrue(after.startswith(before))  # append-only
            appended = after[len(before):]
            self.assertIn("B+", appended)
            self.assertIn("operator", appended)

    def test_already_graded_is_409(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d, grade="A-", graded_by="delegate")
            with self.assertRaises(pe.GradeError) as ctx:
                pe.grade_eval("eval_x", "A", None, "operator", evals_dir=d)
            self.assertEqual(ctx.exception.status, 409)

    def test_conflicting_prior_grade_without_grader_is_409(self):
        # a recorded grade value is never rewritten (append-only)
        with tempfile.TemporaryDirectory() as d:
            self._seed(d, grade="A-")
            with self.assertRaises(pe.GradeError) as ctx:
                pe.grade_eval("eval_x", "B", None, "delegate", evals_dir=d)
            self.assertEqual(ctx.exception.status, 409)

    def test_matching_prior_grade_gets_grader_stamped(self):
        # legacy case: grade recorded, grader missing — stamping the actor is
        # additive, the grade value itself is not rewritten
        with tempfile.TemporaryDirectory() as d:
            self._seed(d, grade="A-", notes="prior notes")
            out = pe.grade_eval("eval_x", "A-", "grader disclosed", "delegate", evals_dir=d)
            data = json.load(open(os.path.join(d, "eval_x_data.json")))
            self.assertEqual(data["grade"], "A-")
            self.assertEqual(data["graded_by"], "delegate")
            self.assertIn("prior notes", data["notes"])       # kept
            self.assertIn("grader disclosed", data["notes"])  # appended

    def test_unknown_eval_is_404(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(pe.GradeError) as ctx:
                pe.grade_eval("nope", "A", None, "operator", evals_dir=d)
            self.assertEqual(ctx.exception.status, 404)

    def test_invalid_grade_is_422(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            with self.assertRaises(pe.GradeError) as ctx:
                pe.grade_eval("eval_x", "amazing", None, "operator", evals_dir=d)
            self.assertEqual(ctx.exception.status, 422)
