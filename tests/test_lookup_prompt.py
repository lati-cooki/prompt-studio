import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.lookup_prompt import find_prompt

PROMPTS = [
    {"id": "consensus_protocol", "version": "1.0.0", "status": "deprecated", "file": "prompts/cp_v1_0_0.md"},
    {"id": "consensus_protocol", "version": "1.1.0", "status": "draft",      "file": "prompts/cp_v1_1_0.md"},
    {"id": "committee_review",   "version": "1.1",   "status": "production", "file": "prompts/cr_v1_1.md"},
    {"id": "lite_fast_review",   "version": "1.0",   "status": "active",     "file": None},
]


class TestFindPrompt(unittest.TestCase):
    def test_returns_none_for_unknown_id(self):
        self.assertIsNone(find_prompt(PROMPTS, "does_not_exist"))

    def test_returns_none_for_unknown_version(self):
        self.assertIsNone(find_prompt(PROMPTS, "consensus_protocol", version="9.9.9"))

    def test_picks_draft_over_deprecated_when_no_active(self):
        result = find_prompt(PROMPTS, "consensus_protocol")
        self.assertIsNotNone(result)
        self.assertEqual(result["version"], "1.1.0")
        self.assertEqual(result["status"], "draft")

    def test_picks_production_first(self):
        result = find_prompt(PROMPTS, "committee_review")
        self.assertEqual(result["status"], "production")

    def test_exact_version_match(self):
        result = find_prompt(PROMPTS, "consensus_protocol", version="1.0.0")
        self.assertIsNotNone(result)
        self.assertEqual(result["version"], "1.0.0")

    def test_returns_entry_with_null_file(self):
        result = find_prompt(PROMPTS, "lite_fast_review")
        self.assertIsNotNone(result)
        self.assertIsNone(result["file"])

    def test_empty_prompts_list(self):
        self.assertIsNone(find_prompt([], "consensus_protocol"))


if __name__ == "__main__":
    unittest.main()
