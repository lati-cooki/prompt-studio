import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import promotion_seal as psl
import seal


def promo(**over):
    base = {
        "id": 7, "prompt_id": "p1", "version": "1.0.0", "state": "closed",
        "opened_at": "2026-07-12T00:00:00Z", "closes_at": "2026-07-13T00:00:00Z",
        "resolved_at": "2026-07-13T01:00:00Z", "window_hours": 24.0,
        "waive_reason": None, "evidence": None, "objections": [],
        "unresolved_objections": 0, "window_elapsed": True,
        "thread_slug": None, "citation_hash": None, "sealed": 0, "seal_error": None,
    }
    base.update(over)
    return base


class TestBuildSealPayload(unittest.TestCase):
    def test_payload_validates_against_phase2_contract(self):
        p = psl.build_seal_payload(promo(), "promoted", "Troy")
        seal.validate_payload(p)  # must not raise

    def test_fcp_metadata_embedded_in_decision(self):
        p = psl.build_seal_payload(promo(state="waived",
                                         waive_reason="solo, evidence attached"),
                                   "promoted", "Troy")
        meta = json.loads(p["decision"].split("FCP: ", 1)[1])
        self.assertTrue(meta["fcp_waived"])
        self.assertEqual(meta["waive_reason"], "solo, evidence attached")
        self.assertEqual(meta["objection_count"], 0)

    def test_evidence_absence_is_disclosed_not_faked(self):
        p = psl.build_seal_payload(promo(evidence=None), "promoted", "Troy")
        self.assertIn("evidence_attached: false", p["evidence"][0]["finding"])

    def test_pinned_evidence_carries_hash_and_honesty_boundary(self):
        ev = {"source_file": "eval_p1_v1_0_0_x_data.json", "model": "m",
              "tokens": {"total": 2}, "run_at": "2026-07-01",
              "content_hash": "sha256:abc", "rerun": "python3 scripts/evaluate_prompt.py ..."}
        p = psl.build_seal_payload(promo(evidence=ev), "promoted", "Troy")
        finding = p["evidence"][0]["finding"]
        self.assertIn("sha256:abc", finding)
        self.assertIn(psl.HONESTY_BOUNDARY, finding)

    def test_objections_survive_with_resolutions(self):
        objs = [{"id": 1, "body": "eval regressed", "raised_at": "t",
                 "resolution": "responded", "resolution_body": "re-ran, clean",
                 "promotion_id": 7}]
        p = psl.build_seal_payload(promo(objections=objs), "promoted", "Troy")
        self.assertEqual(len(p["objections"]), 1)
        self.assertIn("eval regressed", p["objections"][0])
        self.assertIn("responded", p["objections"][0])

    def test_aborted_outcome_states_abort(self):
        p = psl.build_seal_payload(promo(state="aborted"), "aborted", "Troy")
        self.assertIn("NOT promoted", p["decision"])

    def test_invalid_outcome_raises(self):
        with self.assertRaises(ValueError):
            psl.build_seal_payload(promo(), "not-a-real-outcome", "Troy")

    def test_malformed_evidence_dict_does_not_crash(self):
        # Missing source_file/content_hash used to hard-index and raise KeyError.
        p = psl.build_seal_payload(promo(evidence={"unexpected": "shape"}), "promoted", "Troy")
        self.assertEqual(len(p["evidence"]), 1)  # must not raise


class TestDemotionPayload(unittest.TestCase):
    def test_validates_and_references_superseded_slug(self):
        p = psl.build_demotion_payload("p1", "1.0.0", "superseded by 1.1.0",
                                       "Troy", superseded_slug="promote-p1-1-0-0")
        seal.validate_payload(p)
        self.assertIn("promote-p1-1-0-0", p["decision"])
