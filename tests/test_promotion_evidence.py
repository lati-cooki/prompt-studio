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
