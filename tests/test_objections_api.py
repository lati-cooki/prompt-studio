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


class TokenPathTestCase(ObjectionsTestCase):
    """Adds helpers for the public /object/* surface."""

    def _minted(self, window_hours=24, evidence=None, mint_body=None):
        p = self._open_promotion(window_hours=window_hours, evidence=evidence)
        minted = self._mint(p["id"], mint_body)._json()
        return p, minted

    def _get_page(self, raw):
        h = self._h()
        h.path = f"/object/{raw}"
        h.do_GET()
        return h

    def _post_objection(self, raw, body=None, ip="203.0.113.5"):
        h = self._h(ip)
        h.path = f"/api/object/{raw}"
        h._set_body(json.dumps(body or {}).encode())
        h.do_POST()
        return h

    def _file(self, raw, body="too risky", contact="bob@x.com", label=None,
              hub_id="id_obj"):
        with patch("seal._th", return_value={"id": hub_id}) as mock_th:
            h = self._post_objection(
                raw, {"body": body, "contact": contact,
                      **({"label": label} if label is not None else {})})
        return h, mock_th


class TestTokenOracle(TokenPathTestCase):
    """EVERY validation failure -> one identical generic 404. No oracle for
    which check failed (exists / revoked / exhausted / expired / closed)."""

    def _failure_modes(self):
        """Yield (name, raw_token) for every distinguishable failure."""
        yield "bogus", "not-a-token"
        p, minted = self._minted()
        self.anchor.execute("UPDATE fcp_tokens SET revoked=1 WHERE id=?",
                            (minted["token_id"],))
        self.anchor.commit()
        yield "revoked", minted["token"]
        # exhausted
        pid = p["id"]
        h = self._mint(pid)
        exhausted = h._json()
        self.anchor.execute("UPDATE fcp_tokens SET uses=use_limit WHERE id=?",
                            (exhausted["token_id"],))
        self.anchor.commit()
        yield "exhausted", exhausted["token"]
        # expired window snapshot
        h = self._mint(pid)
        expired = h._json()
        self.anchor.execute(
            "UPDATE fcp_tokens SET expires_at='2000-01-01T00:00:00Z' WHERE id=?",
            (expired["token_id"],))
        self.anchor.commit()
        yield "expired", expired["token"]
        # promotion no longer open
        h = self._mint(pid)
        closed = h._json()
        self.anchor.execute("UPDATE promotions SET state='aborted' WHERE id=?",
                            (pid,))
        self.anchor.commit()
        yield "closed-promotion", closed["token"]

    def test_page_failures_are_byte_identical_404(self):
        bodies = set()
        for name, raw in self._failure_modes():
            h = self._get_page(raw)
            self.assertEqual(h._last_status, 404, name)
            bodies.add(h._body_written)
        self.assertEqual(len(bodies), 1)  # byte-identical across all modes
        # malformed sub-path: same body again
        h = self._h()
        h.path = "/object/whatever/junk"
        h.do_GET()
        self.assertEqual(h._last_status, 404)
        self.assertIn(h._body_written, bodies)

    def test_api_failures_are_byte_identical_404(self):
        bodies = set()
        for name, raw in self._failure_modes():
            h = self._post_objection(raw, {"body": "x", "contact": "a@b.c"})
            self.assertEqual(h._last_status, 404, name)
            bodies.add(h._body_written)
        self.assertEqual(len(bodies), 1)


class TestObjectPage(TokenPathTestCase):
    def test_page_renders_prompt_window_and_form(self):
        p, minted = self._minted()
        h = self._get_page(minted["token"])
        self.assertEqual(h._last_status, 200)
        page = h._body_written.decode()
        self.assertIn("p1", page)
        self.assertIn("1.0.0", page)
        self.assertIn(p["closes_at"], page)
        self.assertIn("<textarea", page)
        self.assertIn('name="contact"', page)
        self.assertIn("countdown", page)
        # no studio shell/nav
        self.assertNotIn("sandbox", page)

    def test_page_shows_pinned_evidence_hash(self):
        ev = {"source_file": "eval_x_data.json", "content_hash": "sha256:abc123"}
        p, minted = self._minted(evidence=ev)
        page = self._get_page(minted["token"])._body_written.decode()
        self.assertIn("sha256:abc123", page)

    def test_page_discloses_evidence_absence(self):
        p, minted = self._minted(evidence=None)
        page = self._get_page(minted["token"])._body_written.decode()
        self.assertIn("absence disclosed", page)

    def test_page_escapes_user_derived_strings(self):
        p, minted = self._minted(
            mint_body={"invitee_label": '<script>alert(1)</script>'})
        page = self._get_page(minted["token"])._body_written.decode()
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)


class TestFileObjection(TokenPathTestCase):
    def test_files_objection_with_immediate_receipt(self):
        p, minted = self._minted(mint_body={"invitee_label": "outside skeptic"})
        h, mock_th = self._file(minted["token"], body="too risky  ",
                                contact="  Bob@X.COM ")
        self.assertEqual(h._last_status, 200)
        receipt = h._json()
        import hashlib as _hl
        self.assertEqual(receipt["body_hash"],
                         "sha256:" + _hl.sha256(b"too risky").hexdigest())
        self.assertEqual(
            receipt["status_url"],
            f"/object/{minted['token']}/status/{receipt['objection_id']}")
        row = self.anchor.execute(
            "SELECT * FROM promotion_objections WHERE id=?",
            (receipt["objection_id"],)).fetchone()
        self.assertEqual(row["channel"], "token")
        self.assertEqual(int(row["token_id"]), minted["token_id"])
        self.assertEqual(row["author_writer"], "objector:bob@x.com")  # normalized
        self.assertEqual(row["body"], "too risky")
        self.assertEqual(self._token_row(minted["token_id"])["uses"], 1)
        # writer provisioned BEFORE the objection can seal (hard precondition)
        w = self.anchor.execute(
            "SELECT * FROM writers WHERE name='objector:bob@x.com'").fetchone()
        self.assertIsNotNone(w)
        self.assertEqual(w["kind"], "human")
        self.assertEqual(w["display_name"], "outside skeptic")  # invitee_label wins
        self.assertEqual(w["custodial"], 1)

    def test_same_contact_reuses_writer_across_fcp(self):
        p, minted = self._minted(mint_body={"use_limit": 2})
        self._file(minted["token"], contact="bob@x.com")
        self._file(minted["token"], contact="  BOB@x.com ")
        n = self.anchor.execute(
            "SELECT COUNT(*) FROM writers WHERE name LIKE 'objector:%'"
        ).fetchone()[0]
        self.assertEqual(n, 1)

    def test_display_name_fallbacks(self):
        p, minted = self._minted(mint_body={"use_limit": 3})
        # no invitee_label: request label drives display_name (pseudonymity)
        h, _ = self._file(minted["token"], contact="a@x.com", label="Skeptic A")
        self.assertEqual(self.anchor.execute(
            "SELECT display_name FROM writers WHERE name='objector:a@x.com'"
        ).fetchone()[0], "Skeptic A")
        # neither label nor invitee_label -> objector-<n>
        h, _ = self._file(minted["token"], contact="b@x.com")
        self.assertEqual(self.anchor.execute(
            "SELECT display_name FROM writers WHERE name='objector:b@x.com'"
        ).fetchone()[0], "objector-2")
        # a label containing the contact is discarded — privacy invariant is
        # unconditional, not advisory
        h, _ = self._file(minted["token"], contact="c@x.com",
                          label="Carol (c@x.com)")
        self.assertEqual(self.anchor.execute(
            "SELECT display_name FROM writers WHERE name='objector:c@x.com'"
        ).fetchone()[0], "objector-3")

    def test_contact_never_in_any_hub_bound_payload(self):
        # Filing mints the identity; sealing writes the thread. The contact
        # must appear in NEITHER set of hub-bound bytes.
        p, minted = self._minted()
        contact = "Sue.Skeptic@Example.COM"
        h, mock_th = self._file(minted["token"], contact=contact)
        self.assertEqual(h._last_status, 200)
        self.assertTrue(mock_th.called)  # identity really was minted
        for call in mock_th.call_args_list:
            wire = json.dumps([call.args, call.kwargs])
            self.assertNotIn(contact.lower(), wire.lower())
        # now seal: elapse the window, resolve inline, close for real up to
        # the seal boundary and inspect everything that would cross it
        self.anchor.execute(
            "UPDATE promotions SET closes_at='2000-01-01T00:00:00Z' WHERE id=?",
            (p["id"],))
        self.anchor.execute(
            "UPDATE promotion_objections SET resolution='responded',"
            " resolution_body='ok' WHERE promotion_id=?", (p["id"],))
        self.anchor.commit()
        with patch("seal.seal_decision",
                   return_value={"slug": "s", "citationHash": "h",
                                 "records": [{"seq": 4, "record_hash": "sha256:o1",
                                              "event_type": "ObjectionRaised"}]}) as mock_seal:
            hc = self._h()
            hc.path = f"/api/promotions/{p['id']}/close"
            hc._set_body(b"")
            hc.do_POST()
        self.assertEqual(hc._json()["sealed"], 1)
        seal_wire = json.dumps([mock_seal.call_args.args,
                                mock_seal.call_args.kwargs])
        self.assertNotIn(contact.lower(), seal_wire.lower())

    def test_non_string_json_values_rejected_not_crashed(self):
        p, minted = self._minted(mint_body={"use_limit": 5})
        for body in ({"body": ["x"], "contact": "a@b.c"},
                     {"body": "x", "contact": {"e": "a@b.c"}},
                     {"body": 7, "contact": "a@b.c"}):
            h = self._post_objection(minted["token"], body)
            self.assertEqual(h._last_status, 422, body)
        # a non-string label must not crash either — it is just ignored
        with patch("seal._th", return_value={"id": "id_obj"}):
            h = self._post_objection(
                minted["token"],
                {"body": "concern", "contact": "a@b.c", "label": ["x"]})
        self.assertEqual(h._last_status, 200)

    def test_body_and_contact_required(self):
        p, minted = self._minted(mint_body={"use_limit": 5})
        h = self._post_objection(minted["token"], {"contact": "a@b.c"})
        self.assertEqual(h._last_status, 422)
        h = self._post_objection(minted["token"],
                                 {"body": "  ", "contact": "a@b.c"})
        self.assertEqual(h._last_status, 422)
        h = self._post_objection(minted["token"], {"body": "concern"})
        self.assertEqual(h._last_status, 422)
        # no writer minted, no objection row, no use burned
        self.assertEqual(self.anchor.execute(
            "SELECT COUNT(*) FROM promotion_objections").fetchone()[0], 0)
        self.assertEqual(self._token_row(minted["token_id"])["uses"], 0)

    def test_use_limit_exhaustion_returns_generic_404(self):
        p, minted = self._minted()  # use_limit 1
        h, _ = self._file(minted["token"])
        self.assertEqual(h._last_status, 200)
        h2 = self._post_objection(minted["token"],
                                  {"body": "again", "contact": "bob@x.com"})
        self.assertEqual(h2._last_status, 404)
        self.assertEqual(h2._json(), objections.GENERIC_404_JSON)

    def test_hub_unreachable_is_502_not_silent(self):
        p, minted = self._minted()
        with patch("seal._th",
                   side_effect=seal.SealError("ThreadHub is not reachable",
                                              status=502)):
            h = self._post_objection(
                minted["token"], {"body": "concern", "contact": "a@b.c"})
        self.assertEqual(h._last_status, 502)
        # nothing half-filed
        self.assertEqual(self.anchor.execute(
            "SELECT COUNT(*) FROM promotion_objections").fetchone()[0], 0)
        self.assertEqual(self._token_row(minted["token_id"])["uses"], 0)


class TestRateLimit(TokenPathTestCase):
    def test_allow_request_unit(self):
        for i in range(10):
            self.assertTrue(objections.allow_request("1.1.1.1", now=100.0 + i))
        self.assertFalse(objections.allow_request("1.1.1.1", now=110.0))
        self.assertTrue(objections.allow_request("2.2.2.2", now=110.0))
        # window slides: a minute later the ip may post again
        self.assertTrue(objections.allow_request("1.1.1.1", now=161.0))

    def test_api_object_rate_limited_per_ip(self):
        for i in range(10):
            h = self._post_objection("bogus", {"body": "x", "contact": "a@b"},
                                     ip="198.51.100.7")
            self.assertEqual(h._last_status, 404)
        h = self._post_objection("bogus", {"body": "x", "contact": "a@b"},
                                 ip="198.51.100.7")
        self.assertEqual(h._last_status, 429)
        # a different ip is unaffected
        h = self._post_objection("bogus", {"body": "x", "contact": "a@b"},
                                 ip="198.51.100.8")
        self.assertEqual(h._last_status, 404)

    def test_rate_limit_scoped_to_api_object_only(self):
        p, minted = self._minted()
        for _ in range(11):
            self._post_objection("bogus", {"body": "x", "contact": "a@b"})
        # the standalone page and the mint route are NOT under /api/object/*
        h = self._get_page(minted["token"])
        self.assertEqual(h._last_status, 200)
        h2 = self._mint(p["id"])
        self.assertEqual(h2._last_status, 200)


class TestStatusReceipt(TokenPathTestCase):
    """Two-phase receipts: pre-seal {status: filed}, post-seal the full
    verifiable receipt with the DR 5.6 custody disclosure and runnable
    checker instructions. The status route re-validates the token but stays
    readable post-close and post-exhaustion — the receipt must outlive the
    window that produced it."""

    def _status(self, raw, oid):
        h = self._h()
        h.path = f"/object/{raw}/status/{oid}"
        h.do_GET()
        return h

    def _filed(self, **mint_body):
        p, minted = self._minted(mint_body=mint_body or None)
        h, _ = self._file(minted["token"])
        return p, minted, h._json()

    def test_pre_seal_status_is_filed(self):
        p, minted, receipt = self._filed()
        h = self._status(minted["token"], receipt["objection_id"])
        self.assertEqual(h._last_status, 200)
        body = h._json()
        self.assertEqual(body["status"], "filed")
        self.assertEqual(body["objection_id"], receipt["objection_id"])
        self.assertEqual(body["body_hash"], receipt["body_hash"])
        self.assertEqual(body["promotion_state"], "open")

    def test_status_readable_after_exhaustion_and_close(self):
        p, minted, receipt = self._filed()  # use_limit 1, now exhausted
        self.anchor.execute("UPDATE promotions SET state='closed' WHERE id=?",
                            (p["id"],))
        self.anchor.commit()
        h = self._status(minted["token"], receipt["objection_id"])
        self.assertEqual(h._last_status, 200)
        self.assertEqual(h._json()["promotion_state"], "closed")

    def test_status_404s_are_generic(self):
        p, minted, receipt = self._filed()
        oid = receipt["objection_id"]
        bodies = set()
        # unknown token / wrong objection / non-integer oid / revoked token
        for raw, o in (("bogus", oid), (minted["token"], oid + 99),
                       (minted["token"], "abc")):
            h = self._status(raw, o)
            self.assertEqual(h._last_status, 404, (raw, o))
            bodies.add(h._body_written)
        # an objection belonging to a DIFFERENT token
        other = self._mint(p["id"], {"use_limit": 1})
        self.assertEqual(other._last_status, 200)
        h = self._status(other._json()["token"], oid)
        self.assertEqual(h._last_status, 404)
        bodies.add(h._body_written)
        self.anchor.execute("UPDATE fcp_tokens SET revoked=1 WHERE id=?",
                            (minted["token_id"],))
        self.anchor.commit()
        h = self._status(minted["token"], oid)
        self.assertEqual(h._last_status, 404)
        bodies.add(h._body_written)
        self.assertEqual(len(bodies), 1)  # byte-identical across all modes

    def _close_sealed(self, p, records):
        """Elapse the window, resolve open objections inline (Phase 4 form),
        and close through the API with a mocked seal returning `records`."""
        self.anchor.execute(
            "UPDATE promotions SET closes_at='2000-01-01T00:00:00Z' WHERE id=?",
            (p["id"],))
        self.anchor.execute(
            "UPDATE promotion_objections SET resolution='responded',"
            " resolution_body='addressed' WHERE promotion_id=?", (p["id"],))
        self.anchor.commit()
        ret = {"slug": "promo-thread", "citationHash": "sha256:head"}
        if records is not None:
            ret["records"] = records
        with patch("seal.seal_decision", return_value=ret):
            h = self._h()
            h.path = f"/api/promotions/{p['id']}/close"
            h._set_body(b"")
            h.do_POST()
        return h

    def _records_with_objections(self, hashes):
        recs = [{"seq": 0, "record_hash": "sha256:g0", "event_type": "ThreadCreated"},
                {"seq": 1, "record_hash": "sha256:g1", "event_type": "ParticipantDeclared"},
                {"seq": 2, "record_hash": "sha256:g2", "event_type": "EvidenceCommitted"},
                {"seq": 3, "record_hash": "sha256:g3", "event_type": "ClaimCreated"}]
        for i, rh in enumerate(hashes):
            recs.append({"seq": 4 + i, "record_hash": rh,
                         "event_type": "ObjectionRaised"})
        return recs

    def test_post_seal_receipt_full_shape(self):
        p, minted, receipt = self._filed(invitee_label="outside skeptic")
        oid = receipt["objection_id"]
        h = self._close_sealed(p, self._records_with_objections(["sha256:obj1"]))
        self.assertEqual(h._json()["sealed"], 1)

        s = self._status(minted["token"], oid)
        self.assertEqual(s._last_status, 200)
        body = s._json()
        hub = f"http://localhost:{seal.THREADHUB_PORT}"
        self.assertEqual(body["status"], "sealed")
        self.assertEqual(body["record_hash"], "sha256:obj1")
        self.assertEqual(body["thread_slug"], "promo-thread")
        self.assertEqual(body["citation_hash"], "sha256:head")
        self.assertEqual(body["record_url"], f"{hub}/r/sha256:obj1")
        self.assertEqual(body["verify_url"], f"{hub}/t/promo-thread/verify")
        self.assertEqual(body["checker_url"], f"{hub}/verify.mjs")
        # DR 5.6 custody disclosure: custodial identity, downgraded
        # independence, upgrade path — on the receipt, no hub query needed
        custody = body["custody"]
        self.assertIn("5.6", custody)
        self.assertIn("custodial", custody.lower())
        self.assertIn("id_obj", custody)              # the actual hub identity
        self.assertIn("outside skeptic", custody)     # its display name
        self.assertIn("downgraded", custody.lower())
        self.assertIn("upgrade path", custody.lower())
        self.assertNotIn("bob@x.com", json.dumps(body))  # contact stays local
        # runnable instructions: save checker, fetch thread, run, compare
        instr = body["instructions"]
        self.assertIn(f"{hub}/verify.mjs", instr)
        self.assertIn(f"{hub}/t/promo-thread.json", instr)
        self.assertIn("node verify.mjs", instr)
        self.assertIn("sha256:head", instr)  # the citation hash to compare
        self.assertIn("signatures verified", instr)
        self.assertIn("not", instr.lower())  # proves recording, not truth

    def test_backfill_writes_hashes_in_objection_order(self):
        p, minted, r1 = self._filed(use_limit=2)
        h2, _ = self._file(minted["token"], body="second concern",
                           contact="carol@y.org")
        r2 = h2._json()
        h = self._close_sealed(
            p, self._records_with_objections(["sha256:objA", "sha256:objB"]))
        self.assertEqual(h._json()["sealed"], 1)
        rows = self.anchor.execute(
            "SELECT id, sealed_record_hash FROM promotion_objections"
            " WHERE promotion_id=? ORDER BY id", (p["id"],)).fetchall()
        self.assertEqual([r["sealed_record_hash"] for r in rows],
                         ["sha256:objA", "sha256:objB"])
        self.assertEqual([r["id"] for r in rows],
                         [r1["objection_id"], r2["objection_id"]])

    def test_backfill_count_mismatch_is_seal_error_no_partial(self):
        p, minted, r1 = self._filed(use_limit=2)
        self._file(minted["token"], body="second concern",
                   contact="carol@y.org")
        # hub return claims only ONE ObjectionRaised for TWO stored objections
        h = self._close_sealed(
            p, self._records_with_objections(["sha256:only-one"]))
        result = h._json()
        self.assertEqual(result["sealed"], 0)
        self.assertIn("mismatch", result["seal_error"])
        # NO partial back-fill: not a single row got a hash
        rows = self.anchor.execute(
            "SELECT sealed_record_hash FROM promotion_objections"
            " WHERE promotion_id=?", (p["id"],)).fetchall()
        self.assertEqual([r["sealed_record_hash"] for r in rows], [None, None])

    def test_legacy_seal_return_without_records_skips_backfill(self):
        # a mocked/legacy seal return with no 'records' key must neither
        # back-fill nor fail — the receipt just stays at 'filed', disclosed
        p, minted, receipt = self._filed()
        h = self._close_sealed(p, records=None)
        self.assertEqual(h._json()["sealed"], 1)
        s = self._status(minted["token"], receipt["objection_id"])
        body = s._json()
        self.assertEqual(body["status"], "filed")
        self.assertEqual(body["promotion_state"], "closed")


if __name__ == "__main__":
    unittest.main()
