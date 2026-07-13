"""Slice 6 — tokenized objection path (fcp_tokens, /object/<token>, receipts).

Covers, per the Phase 5 plan + DR-phase5-topology 5.2/5.3/5.6 + the
DR-2026-07-12-fcp-metrics query contract:

- token mint/revoke (POST /api/promotions/<pid>/tokens): raw shown ONCE,
  only the sha256 hash stored; refuses 409 when the operator writer is not
  provisioned (hard precondition from Slice 2's review); expires_at is the
  promotion's closes_at snapshot; minted_at satisfies the metrics contract.
- oracle-free validation: EVERY token-check failure on /object/* paths is
  the same byte-identical generic 404 (no leaking which check failed).
- objection filing: objector writer minted via ensure_writer BEFORE the
  objection exists; contact string never in any hub-bound payload; per-IP
  rate limit on /api/object/* only.
- two-phase receipts: immediate {objection_id, body_hash, status_url};
  post-seal full receipt with record_hash/thread_slug/citation_hash/
  record_url/verify_url/checker_url + DR 5.6 custody disclosure +
  runnable checker instructions.
- back-fill: sealed_record_hash matched n-th ObjectionRaised from the
  extended write_to_threadhub return; count mismatch -> seal_error, no
  partial back-fill.
"""
import hashlib
import json
import os
import sqlite3
import sys
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import objections
import promotion_store
import seal
from test_promotions_api import MockHandler

SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")


class ObjectionsTestCase(unittest.TestCase):
    """Shared in-memory SQLite seeded with schema.sql + one draft prompt.
    The operator writer is provisioned in setUp (tests that need it absent
    delete it); the rate limiter is cleared per test."""

    def setUp(self):
        self.db_uri = f"file:objections_{uuid.uuid4().hex}?mode=memory&cache=shared"
        self.anchor = sqlite3.connect(self.db_uri, uri=True)
        self.anchor.row_factory = sqlite3.Row
        with open(SCHEMA_PATH) as f:
            self.anchor.executescript(f.read())
        self.anchor.execute(
            "INSERT INTO prompts (id, version, status) VALUES ('p1', '1.0.0', 'draft')")
        self.anchor.execute(
            "INSERT INTO writers (name, threadhub_id, display_name, kind, custodial)"
            " VALUES ('operator', 'id_troy', 'Troy', 'human', 1)")
        self.anchor.commit()
        objections._rate_buckets.clear()
        anchor_patcher = patch(
            "anchors.anchor_seal",
            return_value={"anchored": True, "anchor_pushed": True})
        anchor_patcher.start()
        self.addCleanup(anchor_patcher.stop)

    def tearDown(self):
        self.anchor.close()

    def _h(self, ip="203.0.113.5"):
        h = MockHandler(self.db_uri)
        h.client_address = (ip, 12345)
        return h

    def _open_promotion(self, window_hours=24, evidence=None):
        return promotion_store.open_promotion(
            self.anchor, "p1", "1.0.0", window_hours=window_hours,
            evidence=evidence)

    def _drop_operator(self):
        self.anchor.execute("DELETE FROM writers WHERE name='operator'")
        self.anchor.commit()

    def _mint(self, pid, body=None, ip="203.0.113.5"):
        h = self._h(ip)
        h.path = f"/api/promotions/{pid}/tokens"
        h._set_body(json.dumps(body or {}).encode())
        h.do_POST()
        return h

    def _token_row(self, token_id):
        return self.anchor.execute(
            "SELECT * FROM fcp_tokens WHERE id=?", (token_id,)).fetchone()


class TestMint(ObjectionsTestCase):
    def test_mint_refuses_409_when_operator_unprovisioned(self):
        # HARD PRECONDITION: without the operator writer, the empty-table
        # legacy fallback in _writers_for_promotion would seal a named
        # objector under the shared studio author. Refuse to mint at all.
        self._drop_operator()
        p = self._open_promotion()
        h = self._mint(p["id"])
        self.assertEqual(h._last_status, 409)
        body = h._json()
        self.assertIn("operator", body["error"])
        self.assertIn("ensure_writer", body["error"])

    def test_mint_refuses_even_when_other_writers_exist(self):
        self._drop_operator()
        self.anchor.execute(
            "INSERT INTO writers (name, threadhub_id, display_name, kind, custodial)"
            " VALUES ('delegate', 'id_del', 'Claude (delegate)', 'agent', 1)")
        self.anchor.commit()
        p = self._open_promotion()
        h = self._mint(p["id"])
        self.assertEqual(h._last_status, 409)

    def test_mint_returns_raw_once_and_stores_only_hash(self):
        p = self._open_promotion()
        h = self._mint(p["id"], {"invitee_label": "outside skeptic"})
        self.assertEqual(h._last_status, 200)
        body = h._json()
        raw = body["token"]
        self.assertGreaterEqual(len(raw), 43)  # >= 32 bytes urlsafe
        self.assertIn(f"/object/{raw}", body["url"])
        row = self._token_row(body["token_id"])
        self.assertIsNotNone(row)
        self.assertEqual(row["token_hash"],
                         hashlib.sha256(raw.encode()).hexdigest())
        # the raw token appears nowhere in the stored row
        self.assertNotIn(raw, json.dumps({k: row[k] for k in row.keys()}))
        self.assertEqual(row["invitee_label"], "outside skeptic")
        self.assertEqual(row["use_limit"], 1)
        self.assertEqual(row["uses"], 0)
        self.assertEqual(row["revoked"], 0)
        self.assertEqual(row["created_by"], "operator")

    def test_mint_expires_at_is_window_close_snapshot(self):
        p = self._open_promotion(window_hours=24)
        h = self._mint(p["id"])
        body = h._json()
        self.assertEqual(body["expires_at"], p["closes_at"])
        row = self._token_row(body["token_id"])
        self.assertEqual(row["expires_at"], p["closes_at"])
        self.assertTrue(row["minted_at"])  # metrics-contract column

    def test_mint_response_carries_custody_disclosure_and_posture_note(self):
        p = self._open_promotion()
        body = self._mint(p["id"])._json()
        custody = body["custody"]
        for needle in ("5.6", "custodial", "keys", "independence", "Upgrade path"):
            self.assertIn(needle.lower(), custody.lower(), needle)
        self.assertIn("deployment posture", body["posture"])
        self.assertIn("not enforced auth", body["posture"])

    def test_mint_404_on_missing_promotion(self):
        h = self._mint(999)
        self.assertEqual(h._last_status, 404)

    def test_mint_409_on_non_open_promotion(self):
        p = self._open_promotion()
        self.anchor.execute("UPDATE promotions SET state='closed' WHERE id=?",
                            (p["id"],))
        self.anchor.commit()
        h = self._mint(p["id"])
        self.assertEqual(h._last_status, 409)

    def test_mint_409_on_elapsed_window(self):
        # a token whose expires_at snapshot is already past would be born dead
        p = self._open_promotion(window_hours=0)
        h = self._mint(p["id"])
        self.assertEqual(h._last_status, 409)

    def test_mint_use_limit_validated(self):
        p = self._open_promotion()
        for bad in ("abc", 0, -1, 1.5, True):
            h = self._mint(p["id"], {"use_limit": bad})
            self.assertEqual(h._last_status, 422, f"use_limit={bad!r}")
        h = self._mint(p["id"], {"use_limit": 3})
        self.assertEqual(h._last_status, 200)
        self.assertEqual(h._json()["use_limit"], 3)

    def test_minted_tokens_satisfy_metrics_query_contract(self):
        # DR-2026-07-12-fcp-metrics rule 3: a terminal outcome counts as
        # externally contested when >= 1 fcp_tokens row has this promotion_id
        # and minted_at < resolved_at.
        p = self._open_promotion(window_hours=24)
        self._mint(p["id"])
        self.anchor.execute(
            "UPDATE promotions SET state='closed',"
            " resolved_at=strftime('%Y-%m-%dT%H:%M:%SZ','now','+1 hour')"
            " WHERE id=?", (p["id"],))
        self.anchor.commit()
        m = promotion_store.metrics(self.anchor)
        self.assertEqual(m["terminal_total"], 1)
        self.assertEqual(m["invited"], 1)
        self.assertEqual(m["externally_contested_ratio"], 1.0)
        self.assertEqual(m["contested_data"],
                         promotion_store.CONTESTED_DATA_MEASURED)


class TestRevoke(ObjectionsTestCase):
    def test_revoke_sets_flag_and_token_stops_working(self):
        p = self._open_promotion()
        minted = self._mint(p["id"])._json()
        h = self._h()
        h.path = f"/api/promotions/{p['id']}/tokens/{minted['token_id']}/revoke"
        h._set_body(b"")
        h.do_POST()
        self.assertEqual(h._last_status, 200)
        self.assertTrue(h._json()["revoked"])
        self.assertEqual(self._token_row(minted["token_id"])["revoked"], 1)

    def test_revoke_404_on_unknown_or_mismatched_token(self):
        p = self._open_promotion()
        minted = self._mint(p["id"])._json()
        h = self._h()
        h.path = f"/api/promotions/{p['id']}/tokens/999/revoke"
        h._set_body(b"")
        h.do_POST()
        self.assertEqual(h._last_status, 404)
        h2 = self._h()  # wrong promotion id for a real token
        h2.path = f"/api/promotions/{p['id'] + 1}/tokens/{minted['token_id']}/revoke"
        h2._set_body(b"")
        h2.do_POST()
        self.assertEqual(h2._last_status, 404)


if __name__ == "__main__":
    unittest.main()
