import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import seal


class TestValidatePayload(unittest.TestCase):
    def _valid(self):
        return {
            "title": "Ship beta?",
            "question": "Ship the support beta?",
            "decision": "Ship to redacted tickets only",
            "decidedBy": "Troy",
            "evidence": [{"source": "support logs", "finding": "82% FAQ-shaped"}],
            "objections": [{"text": "Privacy risk remains"}],
        }

    def test_accepts_valid_payload(self):
        out = seal.validate_payload(self._valid())
        self.assertEqual(out["question"], "Ship the support beta?")
        self.assertEqual(out["evidence"], [{"source": "support logs", "finding": "82% FAQ-shaped"}])
        self.assertEqual(out["objections"], ["Privacy risk remains"])

    def test_title_defaults_to_question(self):
        p = self._valid(); del p["title"]
        self.assertEqual(seal.validate_payload(p)["title"], p["question"])

    def test_missing_required_fields_collected(self):
        with self.assertRaises(seal.SealValidationError) as ctx:
            seal.validate_payload({"evidence": []})
        fields = ctx.exception.fields
        self.assertIn("question", fields)
        self.assertIn("decision", fields)
        self.assertIn("decidedBy", fields)
        self.assertIn("evidence", fields)

    def test_evidence_requires_source_and_finding(self):
        p = self._valid(); p["evidence"] = [{"source": "x", "finding": ""}]
        with self.assertRaises(seal.SealValidationError) as ctx:
            seal.validate_payload(p)
        self.assertIn("evidence", ctx.exception.fields)

    def test_non_dict_payload_raises(self):
        with self.assertRaises(seal.SealValidationError):
            seal.validate_payload(["not", "a", "dict"])

    def test_non_dict_evidence_items_skipped(self):
        p = self._valid(); p["evidence"] = ["bad", None, {"source": "s", "finding": "f"}]
        out = seal.validate_payload(p)
        self.assertEqual(out["evidence"], [{"source": "s", "finding": "f"}])

    def test_non_list_evidence_treated_as_missing(self):
        p = self._valid(); p["evidence"] = "oops"
        with self.assertRaises(seal.SealValidationError) as ctx:
            seal.validate_payload(p)
        self.assertIn("evidence", ctx.exception.fields)


def _proc(stdout, returncode=0):
    m = MagicMock()
    m.stdout = stdout
    m.stderr = ""
    m.returncode = returncode
    return m


class TestAuthorClistaLog(unittest.TestCase):
    def _data(self):
        return {
            "title": "Ship?", "question": "Ship?", "decision": "Ship redacted",
            "decidedBy": "Troy",
            "evidence": [{"source": "logs", "finding": "82% FAQ"},
                         {"source": "privacy", "finding": "PII risk"}],
            "objections": ["Privacy risk remains"],
        }

    @patch("seal.subprocess.run")
    def test_authoring_sequence_and_id_threading(self, run):
        run.side_effect = [
            _proc(json.dumps({"thread": {"id": "thd_1"}})),
            _proc(json.dumps({"participant": {"id": "par_troy"}})),
            _proc(json.dumps({"evidence": {"id": "evd_1"}})),
            _proc(json.dumps({"evidence": {"id": "evd_2"}})),
            _proc(json.dumps({"claim": {"id": "clm_1"}})),
            _proc(json.dumps({"objection": {"id": "obj_1"}})),
            _proc(json.dumps({"valid": True, "errors": []})),
        ]
        seal.author_clista_log(self._data(), "/tmp/x")
        calls = [c.args[0] for c in run.call_args_list]
        claim_call = next(a for a in calls if "claim" in a and "create" in a)
        self.assertIn("evd_1,evd_2", claim_call)
        obj_call = next(a for a in calls if "objection" in a and "raise" in a)
        self.assertIn("clm_1", obj_call)
        self.assertIn("validate", calls[-1])

    @patch("seal.subprocess.run")
    def test_validate_failure_raises(self, run):
        run.side_effect = [
            _proc(json.dumps({"thread": {"id": "thd_1"}})),
            _proc(json.dumps({"participant": {"id": "par_troy"}})),
            _proc(json.dumps({"evidence": {"id": "evd_1"}})),
            _proc(json.dumps({"evidence": {"id": "evd_2"}})),
            _proc(json.dumps({"claim": {"id": "clm_1"}})),
            _proc(json.dumps({"objection": {"id": "obj_1"}})),
            _proc(json.dumps({"valid": False, "errors": [{"reason": "bad"}]})),
        ]
        with self.assertRaises(seal.SealError):
            seal.author_clista_log(self._data(), "/tmp/x")

    @patch("seal.subprocess.run")
    def test_non_json_stdout_raises_sealerror(self, run):
        run.return_value = _proc("Usage: clista ...\n")  # non-JSON, returncode 0
        with self.assertRaises(seal.SealError):
            seal.author_clista_log(self._data(), "/tmp/x")

    @patch("seal.subprocess.run")
    def test_missing_key_in_response_raises_sealerror(self, run):
        run.return_value = _proc(json.dumps({"unexpected": True}))  # no thread.id
        with self.assertRaises(seal.SealError):
            seal.author_clista_log(self._data(), "/tmp/x")


if __name__ == "__main__":
    unittest.main()
