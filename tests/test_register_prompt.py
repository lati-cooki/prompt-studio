import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scripts.register_prompt as rp


def _make_index(prompts=None):
    return {
        "registry_version": "0.1",
        "generated_at": "2026-05-10",
        "owner": "test_owner",
        "owner_entity": "Test LLC",
        "prompts": prompts or [],
        "evals": [],
        "open_questions": [],
    }


def _sample_draft():
    return {
        "id": "my_prompt",
        "version": "0.1.0",
        "status": "draft",
        "tier": "audit",
        "owner": "unknown",
        "body": "You are a helpful assistant.",
        "use_case": "Draft exported from sandbox",
        "default_model": "claude-sonnet-4-6",
        "cost_per_run_usd": None,
        "tokens_prompt_body": None,
        "tested_on": ["claude-sonnet-4-6"],
        "eval_status": "unevaluated",
        "composes": [],
        "file": None,
        "notes": "",
    }


def _sample_eval_data():
    return {
        "id": "eval_my_prompt_v0_1_0_2026-05-10",
        "directive_file": "registry/evals/strategiai_directive.md",
        "date": "2026-05-10",
        "prompt_under_test": {"id": "my_prompt", "version": "0.1.0"},
        "model": "claude-sonnet-4-6",
        "tokens": {"input": 1000, "output": 500, "cache_read": 0, "total": 1500},
        "cost_usd_estimated": 0.0105,
        "response": "...",
        "grade": "A",
        "notes": "Caught arithmetic check.",
    }


class TestCheckDuplicate(unittest.TestCase):
    def test_no_duplicate_on_empty(self):
        index = _make_index()
        self.assertFalse(rp.check_duplicate(index, "my_prompt", "0.1.0"))

    def test_detects_exact_match(self):
        existing = {"id": "my_prompt", "version": "0.1.0"}
        index = _make_index(prompts=[existing])
        self.assertTrue(rp.check_duplicate(index, "my_prompt", "0.1.0"))

    def test_different_version_not_duplicate(self):
        existing = {"id": "my_prompt", "version": "0.2.0"}
        index = _make_index(prompts=[existing])
        self.assertFalse(rp.check_duplicate(index, "my_prompt", "0.1.0"))


class TestMergeEvalIntoDraft(unittest.TestCase):
    def test_updates_eval_status_from_grade(self):
        draft = _sample_draft()
        eval_data = _sample_eval_data()
        result = rp.merge_eval_into_draft(draft, eval_data)
        self.assertEqual(result["eval_status"], "passed")
        self.assertEqual(result["eval_batch"], eval_data["id"])

    def test_cost_and_tokens_updated(self):
        draft = _sample_draft()
        eval_data = _sample_eval_data()
        result = rp.merge_eval_into_draft(draft, eval_data)
        self.assertEqual(result["cost_per_run_usd"], 0.0105)

    def test_failing_grade_sets_status_failed(self):
        draft = _sample_draft()
        eval_data = {**_sample_eval_data(), "grade": "F"}
        result = rp.merge_eval_into_draft(draft, eval_data)
        self.assertEqual(result["eval_status"], "failed")

    def test_none_grade_sets_pending(self):
        draft = _sample_draft()
        eval_data = {**_sample_eval_data(), "grade": None}
        result = rp.merge_eval_into_draft(draft, eval_data)
        self.assertEqual(result["eval_status"], "pending")

    def test_body_field_removed_from_registry_entry(self):
        draft = _sample_draft()
        eval_data = _sample_eval_data()
        result = rp.merge_eval_into_draft(draft, eval_data)
        self.assertNotIn("body", result)


class TestAppendToIndex(unittest.TestCase):
    def _write_index(self, tmp_dir, index):
        path = Path(tmp_dir) / "INDEX.json"
        path.write_text(json.dumps(index, indent=2))
        return str(path)

    def test_appends_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_index(tmp, _make_index())
            entry = {"id": "my_prompt", "version": "0.1.0"}
            rp.append_to_index(path, entry)
            with open(path) as f:
                loaded = json.load(f)
            self.assertEqual(len(loaded["prompts"]), 1)
            self.assertEqual(loaded["prompts"][0]["id"], "my_prompt")

    def test_write_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_index(tmp, _make_index())
            entry = {"id": "my_prompt", "version": "0.1.0"}
            rp.append_to_index(path, entry)
            with open(path) as f:
                loaded = json.load(f)
            self.assertIn("prompts", loaded)

    def test_updates_generated_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_index(tmp, _make_index())
            rp.append_to_index(path, {"id": "x", "version": "0.1.0"})
            with open(path) as f:
                loaded = json.load(f)
            self.assertNotEqual(loaded["generated_at"], "2026-05-10")


if __name__ == "__main__":
    unittest.main()
