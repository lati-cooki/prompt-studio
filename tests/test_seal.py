import os
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
