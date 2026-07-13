import io
import json
import sys
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scripts.evaluate_prompt as ep


class TestBuildEvalId(unittest.TestCase):
    def test_format(self):
        eid = ep.build_eval_id("consensus_protocol", "1.1.0", date(2026, 5, 10))
        self.assertEqual(eid, "eval_consensus_protocol_v1_1_0_2026-05-10")

    def test_version_dots_replaced(self):
        eid = ep.build_eval_id("my_prompt", "0.1.0", date(2026, 1, 1))
        self.assertIn("v0_1_0", eid)

    def test_includes_model_slug(self):
        eid = ep.build_eval_id(
            "consensus_protocol", "1.1.0", date(2026, 6, 4), "claude-opus-4-7"
        )
        self.assertEqual(
            eid, "eval_consensus_protocol_v1_1_0_2026-06-04_claude_opus_4_7"
        )


class TestEstimateCost(unittest.TestCase):
    def test_sonnet_4_6(self):
        cost = ep.estimate_cost("claude-sonnet-4-6", input_tokens=1000, output_tokens=1000, cache_read_tokens=0)
        self.assertAlmostEqual(cost, 0.018, places=4)

    def test_opus_4_7(self):
        cost = ep.estimate_cost("claude-opus-4-7", input_tokens=1000, output_tokens=1000, cache_read_tokens=0)
        self.assertAlmostEqual(cost, 0.09, places=4)

    def test_haiku_4_5(self):
        cost = ep.estimate_cost("claude-haiku-4-5-20251001", input_tokens=1000, output_tokens=1000, cache_read_tokens=0)
        self.assertAlmostEqual(cost, 0.0048, places=5)

    def test_cache_read_is_cheaper(self):
        cost_with_cache = ep.estimate_cost("claude-sonnet-4-6", input_tokens=0, output_tokens=0, cache_read_tokens=1000000)
        self.assertAlmostEqual(cost_with_cache, 0.30, places=2)

    def test_unknown_model_returns_none(self):
        cost = ep.estimate_cost("gpt-999", input_tokens=1000, output_tokens=1000, cache_read_tokens=0)
        self.assertIsNone(cost)


class TestFormatEvalMarkdown(unittest.TestCase):
    def _sample_data(self):
        return {
            "id": "eval_my_prompt_v0_1_0_2026-05-10",
            "directive_file": "registry/evals/strategiai_directive.md",
            "date": "2026-05-10",
            "prompt_under_test": {"id": "my_prompt", "version": "0.1.0"},
            "model": "claude-sonnet-4-6",
            "tokens": {"input": 1000, "output": 500, "cache_read": 200, "total": 1700},
            "cost_usd_estimated": 0.012,
            "response": "This is the model response.",
            "grade": None,
            "notes": "",
        }

    def test_header_contains_id_and_model(self):
        md = ep.format_eval_markdown(self._sample_data())
        self.assertIn("my_prompt@0.1.0", md)
        self.assertIn("claude-sonnet-4-6", md)

    def test_response_is_included(self):
        md = ep.format_eval_markdown(self._sample_data())
        self.assertIn("This is the model response.", md)

    def test_token_counts_present(self):
        md = ep.format_eval_markdown(self._sample_data())
        self.assertIn("1,000", md)
        self.assertIn("500", md)
        self.assertIn("$0.012", md)

    def test_grade_placeholder_present(self):
        md = ep.format_eval_markdown(self._sample_data())
        self.assertIn("<!-- A / A- / B+ / B / C / F", md)

    def test_run_by_writer_shown_when_present(self):
        md = ep.format_eval_markdown({**self._sample_data(), "run_by": "delegate"})
        self.assertIn("delegate", md)


class TestWriterStamping(unittest.TestCase):
    """Phase 5 slice 2: the invoking writer is stamped into the eval artifacts."""

    def _run_main(self, extra_args):
        with tempfile.TemporaryDirectory() as d:
            prompt = os.path.join(d, "my_prompt_v1_0_0.md")
            directive = os.path.join(d, "directive.md")
            with open(prompt, "w") as f:
                f.write("You are a helpful assistant.")
            with open(directive, "w") as f:
                f.write("Do the thing.")
            fake_result = {"response_text": "ok",
                           "tokens": {"input": 1, "output": 1, "cache_read": 0,
                                      "total": 2}}
            argv = ["evaluate_prompt.py", "--prompt", prompt,
                    "--directive", directive, "--output-dir", d] + extra_args
            with patch.object(ep, "run_eval", return_value=fake_result), \
                 patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                ep.main()
            data_files = [f for f in os.listdir(d) if f.endswith("_data.json")]
            self.assertEqual(len(data_files), 1)
            with open(os.path.join(d, data_files[0])) as f:
                return json.load(f)

    def test_writer_stamped_into_eval_data(self):
        data = self._run_main(["--writer", "delegate"])
        self.assertEqual(data["run_by"], "delegate")

    def test_writer_defaults_to_operator(self):
        data = self._run_main([])
        self.assertEqual(data["run_by"], "operator")


if __name__ == "__main__":
    unittest.main()
