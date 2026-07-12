"""API-layer tests for the promotion FCP routes + production-flip guards.

Exercises server.py's HTTP dispatch (do_GET/do_POST/do_PUT) through a MockHandler
that mimics tests/test_server.py's pattern, but backed by a *shared* in-memory
SQLite DB (via sqlite3's shared-cache URI) so state persists across the multiple
handler instances a single test needs to simulate successive HTTP requests.
"""
import io
import json
import os
import sqlite3
import sys
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server
import seal
import promotion_evidence

SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql"
)


class MockHandler(server.PromptStudioHandler):
    """Minimal mock that replaces network I/O with in-memory buffers, backed by
    a shared-cache in-memory SQLite DB identified by db_uri."""

    def __init__(self, db_uri):
        self.db_uri = db_uri
        self._last_status = None
        self._body_written = b""
        self._mock_headers = {}
        self._mock_rfile = io.BytesIO(b"")

    def get_db(self):
        conn = sqlite3.connect(self.db_uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def send_response(self, code, message=None):
        self._last_status = code

    def send_header(self, key, val):
        pass

    def end_headers(self):
        pass

    def send_error(self, code, message=None):
        self._last_status = code

    @property
    def headers(self):
        return self._mock_headers

    @property
    def rfile(self):
        return self._mock_rfile

    @property
    def wfile(self):
        return self

    def write(self, data):
        self._body_written += data

    def _set_body(self, body: bytes):
        self._mock_headers = {"Content-Length": str(len(body))}
        self._mock_rfile = io.BytesIO(body)
        self._body_written = b""

    def _json(self):
        return json.loads(self._body_written.decode("utf-8"))


class PromotionApiTestCase(unittest.TestCase):
    """Seeds a shared in-memory DB with schema.sql + one draft prompt ('p1','1.0.0','draft')."""

    def setUp(self):
        self.db_uri = f"file:promo_api_{uuid.uuid4().hex}?mode=memory&cache=shared"
        # Anchor connection keeps the shared in-memory DB alive across the test;
        # SQLite drops shared-cache memory DBs once every connection to them closes.
        self.anchor = sqlite3.connect(self.db_uri, uri=True)
        self.anchor.row_factory = sqlite3.Row
        with open(SCHEMA_PATH) as f:
            self.anchor.executescript(f.read())
        self.anchor.execute(
            "INSERT INTO prompts (id, version, status) VALUES ('p1', '1.0.0', 'draft')"
        )
        self.anchor.commit()

    def tearDown(self):
        self.anchor.close()

    def _h(self):
        return MockHandler(self.db_uri)

    def _prompt_row(self, prompt_id="p1", version="1.0.0"):
        return self.anchor.execute(
            "SELECT * FROM prompts WHERE id=? AND version=?", (prompt_id, version)
        ).fetchone()

    def _open_promotion(self, window_hours=24, evidence_patch_value=None):
        """Helper: POST promote and return the parsed promotion dict."""
        with patch("promotion_evidence.pin_evidence", return_value=evidence_patch_value):
            h = self._h()
            h.path = "/api/prompts/p1/promote/1.0.0"
            h._set_body(json.dumps({"window_hours": window_hours}).encode())
            h.do_POST()
        self.assertEqual(h._last_status, 200)
        return h._json()


class TestPromote(PromotionApiTestCase):
    def test_promote_opens_fcp_and_does_not_flip_status(self):
        p = self._open_promotion(window_hours=24)
        self.assertEqual(p["state"], "open")
        row = self._prompt_row()
        self.assertEqual(row["status"], "draft")

    def test_promote_attaches_pinned_evidence_when_available(self):
        fake_evidence = {"source_file": "eval_p1_v1_0_0_x_data.json", "model": "m",
                          "content_hash": "sha256:abc"}
        p = self._open_promotion(window_hours=24, evidence_patch_value=fake_evidence)
        self.assertEqual(p["evidence"], fake_evidence)

    def test_promote_conflict_when_already_open(self):
        self._open_promotion(window_hours=24)
        with patch("promotion_evidence.pin_evidence", return_value=None):
            h = self._h()
            h.path = "/api/prompts/p1/promote/1.0.0"
            h._set_body(json.dumps({"window_hours": 24}).encode())
            h.do_POST()
        self.assertEqual(h._last_status, 409)


class TestValidateRetired(PromotionApiTestCase):
    def test_validate_route_now_409_pointing_at_promote(self):
        h = self._h()
        h.path = "/api/prompts/p1/1.0.0/validate"
        h._set_body(b"")
        h.do_POST()
        self.assertEqual(h._last_status, 409)
        self.assertIn(b"promote", h._body_written)


class TestPutPromptGuard(PromotionApiTestCase):
    def test_put_prompt_rejects_direct_production_flip(self):
        h = self._h()
        h.path = "/api/prompts/p1"
        body = {"version": "1.0.0", "status": "production", "body": "x"}
        h._set_body(json.dumps(body).encode())
        h.do_PUT()
        self.assertEqual(h._last_status, 409)
        row = self._prompt_row()
        self.assertEqual(row["status"], "draft")  # unchanged

    def test_put_prompt_allows_production_to_production_edit(self):
        self.anchor.execute("UPDATE prompts SET status='production' WHERE id='p1' AND version='1.0.0'")
        self.anchor.commit()

        h = self._h()
        h.path = "/api/prompts/p1"
        body = {"version": "1.0.0", "status": "production", "body": "edited body"}
        h._set_body(json.dumps(body).encode())
        h.do_PUT()
        self.assertEqual(h._last_status, 200)
        row = self._prompt_row()
        self.assertEqual(row["status"], "production")
        self.assertEqual(row["body"], "edited body")


class TestObjections(PromotionApiTestCase):
    def test_object_and_resolve_roundtrip(self):
        p = self._open_promotion()
        pid = p["id"]

        h = self._h()
        h.path = f"/api/promotions/{pid}/object"
        h._set_body(json.dumps({"body": "concerned about latency"}).encode())
        h.do_POST()
        self.assertEqual(h._last_status, 200)
        objection = h._json()
        oid = objection["id"]
        self.assertEqual(objection["body"], "concerned about latency")

        h2 = self._h()
        h2.path = f"/api/promotions/{pid}/objections/{oid}/resolve"
        h2._set_body(json.dumps({"resolution": "responded", "body": "fixed"}).encode())
        h2.do_POST()
        self.assertEqual(h2._last_status, 200)
        result = h2._json()
        self.assertEqual(result["state"], "open")  # responded, not upheld -> stays open
        self.assertEqual(result["unresolved_objections"], 0)


class TestClose(PromotionApiTestCase):
    def test_close_seals_and_records_slug(self):
        p = self._open_promotion(window_hours=0)
        pid = p["id"]

        with patch("seal.seal_decision", return_value={"slug": "s", "citationHash": "h"}):
            h = self._h()
            h.path = f"/api/promotions/{pid}/close"
            h._set_body(b"")
            h.do_POST()

        self.assertEqual(h._last_status, 200)
        result = h._json()
        self.assertEqual(result["sealed"], 1)
        self.assertEqual(result["thread_slug"], "s")
        row = self._prompt_row()
        self.assertEqual(row["status"], "production")

    def test_close_seal_failure_reports_sealed_false_and_keeps_flip(self):
        p = self._open_promotion(window_hours=0)
        pid = p["id"]

        with patch("seal.seal_decision",
                    side_effect=seal.SealError("ThreadHub is not reachable", status=502)):
            h = self._h()
            h.path = f"/api/promotions/{pid}/close"
            h._set_body(b"")
            h.do_POST()

        result = h._json()
        self.assertEqual(result["sealed"], 0)
        self.assertIn("seal_error", result)
        self.assertTrue(result["seal_error"])
        row = self._prompt_row()
        self.assertEqual(row["status"], "production")  # flip survives seal failure

        with patch("seal.seal_decision", return_value={"slug": "s2", "citationHash": "h2"}):
            h2 = self._h()
            h2.path = f"/api/promotions/{pid}/reseal"
            h2._set_body(b"")
            h2.do_POST()

        self.assertEqual(h2._last_status, 200)
        result2 = h2._json()
        self.assertEqual(result2["sealed"], 1)
        self.assertEqual(result2["thread_slug"], "s2")


class TestWaive(PromotionApiTestCase):
    def test_waive_requires_reason_and_seals_with_fcp_waived(self):
        p = self._open_promotion(window_hours=24)
        pid = p["id"]

        # Missing reason -> 422
        h = self._h()
        h.path = f"/api/promotions/{pid}/waive"
        h._set_body(json.dumps({}).encode())
        h.do_POST()
        self.assertEqual(h._last_status, 422)

        with patch("seal.seal_decision", return_value={"slug": "w", "citationHash": "hw"}) as mock_seal:
            h2 = self._h()
            h2.path = f"/api/promotions/{pid}/waive"
            h2._set_body(json.dumps({"reason": "urgent launch"}).encode())
            h2.do_POST()

        self.assertEqual(h2._last_status, 200)
        result = h2._json()
        self.assertEqual(result["sealed"], 1)
        mock_seal.assert_called_once()
        payload = mock_seal.call_args[0][0]
        self.assertIn('"fcp_waived": true', payload["decision"])
        row = self._prompt_row()
        self.assertEqual(row["status"], "production")


class TestObjectionUpheldAbort(PromotionApiTestCase):
    def test_upheld_resolution_aborts_and_seals_abort(self):
        p = self._open_promotion(window_hours=24)
        pid = p["id"]

        h = self._h()
        h.path = f"/api/promotions/{pid}/object"
        h._set_body(json.dumps({"body": "not enough eval coverage"}).encode())
        h.do_POST()
        oid = h._json()["id"]

        with patch("seal.seal_decision", return_value={"slug": "abort-s", "citationHash": "ah"}) as mock_seal:
            h2 = self._h()
            h2.path = f"/api/promotions/{pid}/objections/{oid}/resolve"
            h2._set_body(json.dumps({"resolution": "upheld", "body": "objection stands"}).encode())
            h2.do_POST()

        self.assertEqual(h2._last_status, 200)
        result = h2._json()
        self.assertEqual(result["state"], "aborted")
        mock_seal.assert_called_once()
        payload = mock_seal.call_args[0][0]
        self.assertIn("NOT promoted", payload["decision"])
        row = self._prompt_row()
        self.assertEqual(row["status"], "draft")  # aborted -> never flips to production


class TestDemote(PromotionApiTestCase):
    def test_demote_flips_to_deprecated_and_references_promotion_slug(self):
        p = self._open_promotion(window_hours=0)
        pid = p["id"]

        with patch("seal.seal_decision", return_value={"slug": "prod-slug", "citationHash": "ph"}):
            h = self._h()
            h.path = f"/api/promotions/{pid}/close"
            h._set_body(b"")
            h.do_POST()
        self.assertEqual(h._json()["thread_slug"], "prod-slug")

        with patch("seal.seal_decision", return_value={"slug": "demote-slug", "citationHash": "dh"}) as mock_seal:
            h2 = self._h()
            h2.path = "/api/prompts/p1/demote/1.0.0"
            h2._set_body(json.dumps({"reason": "superseded"}).encode())
            h2.do_POST()

        self.assertEqual(h2._last_status, 200)
        result = h2._json()
        self.assertEqual(result["status"], "deprecated")
        row = self._prompt_row()
        self.assertEqual(row["status"], "deprecated")
        mock_seal.assert_called_once()
        payload = mock_seal.call_args[0][0]
        self.assertIn("prod-slug", payload["decision"])

    def test_demote_rejects_non_production_status(self):
        # p1@1.0.0 is 'draft' (never promoted) — demoting a non-production
        # prompt would notarize a false "was in production" claim.
        with patch("seal.seal_decision") as mock_seal:
            h = self._h()
            h.path = "/api/prompts/p1/demote/1.0.0"
            h._set_body(json.dumps({"reason": "changed my mind"}).encode())
            h.do_POST()

        self.assertEqual(h._last_status, 409)
        body = h._json()
        self.assertIn("only production prompts can be deprecated", body["error"])
        self.assertEqual(body["status"], "draft")
        mock_seal.assert_not_called()
        row = self._prompt_row()
        self.assertEqual(row["status"], "draft")  # unchanged


class TestCreatePromptGuard(PromotionApiTestCase):
    """POST /api/prompts (create) must not let a caller mint status='production'
    with no FCP — same invariant handle_put_prompt already enforces."""

    def test_create_rejects_direct_production_status(self):
        h = self._h()
        h.path = "/api/prompts"
        body = {"id": "p2", "version": "1.0.0", "status": "production",
                "createdAt": "2026-07-12T00:00:00Z", "updatedAt": "2026-07-12T00:00:00Z"}
        h._set_body(json.dumps(body).encode())
        h.do_POST()

        self.assertEqual(h._last_status, 409)
        row = self.anchor.execute(
            "SELECT * FROM prompts WHERE id=? AND version=?", ("p2", "1.0.0")).fetchone()
        self.assertIsNone(row)  # no row inserted

    def test_create_allows_draft_status(self):
        h = self._h()
        h.path = "/api/prompts"
        body = {"id": "p2", "version": "1.0.0", "status": "draft",
                "createdAt": "2026-07-12T00:00:00Z", "updatedAt": "2026-07-12T00:00:00Z"}
        h._set_body(json.dumps(body).encode())
        h.do_POST()

        self.assertEqual(h._last_status, 200)
        row = self.anchor.execute(
            "SELECT * FROM prompts WHERE id=? AND version=?", ("p2", "1.0.0")).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "draft")


class TestPromoteWindowHoursGuard(PromotionApiTestCase):
    def test_non_numeric_window_hours_is_422(self):
        h = self._h()
        h.path = "/api/prompts/p1/promote/1.0.0"
        h._set_body(json.dumps({"window_hours": "abc"}).encode())
        h.do_POST()
        self.assertEqual(h._last_status, 422)


class TestPromoteEvidenceValidation(PromotionApiTestCase):
    def test_malformed_evidence_dict_is_422(self):
        h = self._h()
        h.path = "/api/prompts/p1/promote/1.0.0"
        h._set_body(json.dumps({"evidence": {"random_field": "nope"}}).encode())
        h.do_POST()

        self.assertEqual(h._last_status, 422)
        body = h._json()
        self.assertIn("source_file", body["error"])
        self.assertIn("content_hash", body["error"])
        # nothing opened
        self.assertEqual(
            self.anchor.execute("SELECT COUNT(*) c FROM promotions").fetchone()["c"], 0)

    def test_explicit_null_evidence_disclosed_and_not_autopinned(self):
        with patch("promotion_evidence.pin_evidence") as mock_pin:
            h = self._h()
            h.path = "/api/prompts/p1/promote/1.0.0"
            h._set_body(json.dumps({"evidence": None}).encode())
            h.do_POST()

        self.assertEqual(h._last_status, 200)
        mock_pin.assert_not_called()  # explicit null means disclosed absence, not auto-pin
        p = h._json()
        self.assertIsNone(p["evidence"])

    def test_absent_evidence_key_still_autopins(self):
        fake = {"source_file": "eval_p1_v1_0_0_x_data.json", "model": "m",
                "content_hash": "sha256:abc"}
        with patch("promotion_evidence.pin_evidence", return_value=fake) as mock_pin:
            h = self._h()
            h.path = "/api/prompts/p1/promote/1.0.0"
            h._set_body(json.dumps({}).encode())
            h.do_POST()

        self.assertEqual(h._last_status, 200)
        mock_pin.assert_called_once()
        p = h._json()
        self.assertEqual(p["evidence"], fake)


class TestSealNeverCrashesOnMalformedEvidence(PromotionApiTestCase):
    """Reproduces the poisoning bug: a promotion with malformed stored evidence
    used to crash the seal path forever (payload build lived outside the try,
    caught only SealError/SealValidationError). Now the payload build is inside
    the try and `except Exception` records the failure instead of propagating."""

    def test_close_with_malformed_evidence_records_seal_error_then_reseal_recovers(self):
        p = self._open_promotion(window_hours=0, evidence_patch_value=None)
        pid = p["id"]

        # Directly corrupt the stored evidence — bypasses promote-time validation,
        # simulating stale/legacy data already sitting in the DB.
        self.anchor.execute(
            "UPDATE promotions SET evidence_json=? WHERE id=?",
            (json.dumps({"totally": "unexpected shape"}), pid))
        self.anchor.commit()

        with patch("seal.seal_decision", side_effect=Exception("boom, downstream failure")):
            h = self._h()
            h.path = f"/api/promotions/{pid}/close"
            h._set_body(b"")
            h.do_POST()

        self.assertEqual(h._last_status, 200)  # request must not crash
        result = h._json()
        self.assertEqual(result["sealed"], 0)
        self.assertTrue(result["seal_error"])
        row = self._prompt_row()
        self.assertEqual(row["status"], "production")  # flip still survives seal failure

        # "Fix" the evidence and reseal — must recover, not stay poisoned forever.
        self.anchor.execute(
            "UPDATE promotions SET evidence_json=NULL WHERE id=?", (pid,))
        self.anchor.commit()

        with patch("seal.seal_decision", return_value={"slug": "fixed-slug", "citationHash": "fh"}):
            h2 = self._h()
            h2.path = f"/api/promotions/{pid}/reseal"
            h2._set_body(b"")
            h2.do_POST()

        self.assertEqual(h2._last_status, 200)
        result2 = h2._json()
        self.assertEqual(result2["sealed"], 1)
        self.assertEqual(result2["thread_slug"], "fixed-slug")


if __name__ == "__main__":
    unittest.main()
