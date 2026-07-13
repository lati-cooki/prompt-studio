import os
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import promotion_store as ps

SCHEMA = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "schema.sql")).read()


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO prompts (id, version, status) VALUES ('p1', '1.0.0', 'draft')")
    conn.commit()
    return conn


class TestOpen(unittest.TestCase):
    def test_open_creates_open_promotion_with_window(self):
        conn = make_db()
        p = ps.open_promotion(conn, "p1", "1.0.0", window_hours=24)
        self.assertEqual(p["state"], "open")
        self.assertEqual(p["window_hours"], 24)
        self.assertFalse(p["window_elapsed"])
        self.assertEqual(p["objections"], [])
        # status NOT flipped by opening
        row = conn.execute("SELECT status FROM prompts WHERE id='p1'").fetchone()
        self.assertEqual(row["status"], "draft")

    def test_second_open_for_same_prompt_version_409(self):
        conn = make_db()
        ps.open_promotion(conn, "p1", "1.0.0")
        with self.assertRaises(ps.PromotionError) as ctx:
            ps.open_promotion(conn, "p1", "1.0.0")
        self.assertEqual(ctx.exception.status, 409)

    def test_unknown_prompt_404(self):
        conn = make_db()
        with self.assertRaises(ps.PromotionError) as ctx:
            ps.open_promotion(conn, "nope", "1.0.0")
        self.assertEqual(ctx.exception.status, 404)

    def test_already_production_409(self):
        conn = make_db()
        conn.execute("UPDATE prompts SET status='production'")
        conn.commit()
        with self.assertRaises(ps.PromotionError) as ctx:
            ps.open_promotion(conn, "p1", "1.0.0")
        self.assertEqual(ctx.exception.status, 409)


class TestClose(unittest.TestCase):
    def test_close_before_window_elapsed_409(self):
        conn = make_db()
        p = ps.open_promotion(conn, "p1", "1.0.0")
        with self.assertRaises(ps.PromotionError) as ctx:
            ps.close_promotion(conn, p["id"])
        self.assertEqual(ctx.exception.status, 409)

    def test_close_after_window_flips_status(self):
        conn = make_db()
        p = ps.open_promotion(conn, "p1", "1.0.0", window_hours=0)  # closes immediately
        out = ps.close_promotion(conn, p["id"])
        self.assertEqual(out["state"], "closed")
        self.assertIsNotNone(out["resolved_at"])
        row = conn.execute("SELECT status, eval_status FROM prompts WHERE id='p1'").fetchone()
        self.assertEqual(row["status"], "production")
        # no evidence was pinned -> eval_status must NOT be stamped 'validated'
        self.assertIsNone(row["eval_status"])

    def test_close_with_pinned_evidence_stamps_validated(self):
        conn = make_db()
        ev = {"source_file": "eval_p1_v1_0_0_x_data.json", "content_hash": "sha256:abc"}
        p = ps.open_promotion(conn, "p1", "1.0.0", window_hours=0, evidence=ev)
        ps.close_promotion(conn, p["id"])
        row = conn.execute("SELECT status, eval_status FROM prompts WHERE id='p1'").fetchone()
        self.assertEqual(row["status"], "production")
        self.assertEqual(row["eval_status"], "validated")

    def test_evidenceless_close_preserves_prior_eval_status(self):
        conn = make_db()
        conn.execute("UPDATE prompts SET eval_status='passed' WHERE id='p1'")
        conn.commit()
        p = ps.open_promotion(conn, "p1", "1.0.0", window_hours=0)
        ps.close_promotion(conn, p["id"])
        row = conn.execute("SELECT eval_status FROM prompts WHERE id='p1'").fetchone()
        self.assertEqual(row["eval_status"], "passed")  # untouched

    def test_unresolved_objection_blocks_close_past_window(self):
        conn = make_db()
        p = ps.open_promotion(conn, "p1", "1.0.0", window_hours=0)
        ps.add_objection(conn, p["id"], "hold on")
        with self.assertRaises(ps.PromotionError) as ctx:
            ps.close_promotion(conn, p["id"])
        self.assertEqual(ctx.exception.status, 409)

    def test_responded_objection_allows_close(self):
        conn = make_db()
        p = ps.open_promotion(conn, "p1", "1.0.0", window_hours=0)
        o = ps.add_objection(conn, p["id"], "hold on")
        ps.resolve_objection(conn, p["id"], o["id"], "responded", "addressed in v1.0.1 notes")
        out = ps.close_promotion(conn, p["id"])
        self.assertEqual(out["state"], "closed")


class TestWaiveAbortUpheld(unittest.TestCase):
    def test_waive_requires_reason(self):
        conn = make_db()
        p = ps.open_promotion(conn, "p1", "1.0.0")
        with self.assertRaises(ps.PromotionError):
            ps.waive_promotion(conn, p["id"], "")

    def test_waive_flips_status_and_records_reason(self):
        conn = make_db()
        p = ps.open_promotion(conn, "p1", "1.0.0")
        out = ps.waive_promotion(conn, p["id"], "solo operator, evidence attached")
        self.assertEqual(out["state"], "waived")
        self.assertEqual(out["waive_reason"], "solo operator, evidence attached")
        row = conn.execute("SELECT status FROM prompts WHERE id='p1'").fetchone()
        self.assertEqual(row["status"], "production")

    def test_abort_leaves_status_untouched(self):
        conn = make_db()
        p = ps.open_promotion(conn, "p1", "1.0.0")
        out = ps.abort_promotion(conn, p["id"])
        self.assertEqual(out["state"], "aborted")
        row = conn.execute("SELECT status FROM prompts WHERE id='p1'").fetchone()
        self.assertEqual(row["status"], "draft")

    def test_upheld_objection_forces_abort(self):
        conn = make_db()
        p = ps.open_promotion(conn, "p1", "1.0.0")
        o = ps.add_objection(conn, p["id"], "eval regressed")
        out = ps.resolve_objection(conn, p["id"], o["id"], "upheld", "regression confirmed")
        self.assertEqual(out["state"], "aborted")
        row = conn.execute("SELECT status FROM prompts WHERE id='p1'").fetchone()
        self.assertEqual(row["status"], "draft")

    def test_terminal_promotions_reject_further_actions(self):
        conn = make_db()
        p = ps.open_promotion(conn, "p1", "1.0.0")
        ps.abort_promotion(conn, p["id"])
        for fn, args in [(ps.add_objection, ("x",)), (ps.waive_promotion, ("r",)),
                         (ps.abort_promotion, ()), (ps.close_promotion, ())]:
            with self.assertRaises(ps.PromotionError) as ctx:
                fn(conn, p["id"], *args)
            self.assertEqual(ctx.exception.status, 409)


class TestActorThreading(unittest.TestCase):
    """Phase 5 slice 2: every promotion act carries its acting writer."""

    def test_open_defaults_actor_to_operator(self):
        conn = make_db()
        p = ps.open_promotion(conn, "p1", "1.0.0")
        self.assertEqual(p["opened_by"], "operator")

    def test_open_records_explicit_actor(self):
        conn = make_db()
        p = ps.open_promotion(conn, "p1", "1.0.0", actor="delegate")
        self.assertEqual(p["opened_by"], "delegate")

    def test_objection_records_author_writer(self):
        conn = make_db()
        p = ps.open_promotion(conn, "p1", "1.0.0")
        o = ps.add_objection(conn, p["id"], "hold on")
        self.assertEqual(o["author_writer"], "operator")
        o2 = ps.add_objection(conn, p["id"], "me too", actor="objector-1")
        self.assertEqual(o2["author_writer"], "objector-1")

    def test_resolution_records_resolver_on_objection(self):
        conn = make_db()
        p = ps.open_promotion(conn, "p1", "1.0.0")
        o = ps.add_objection(conn, p["id"], "hold on", actor="objector-1")
        out = ps.resolve_objection(conn, p["id"], o["id"], "responded", "addressed",
                                   actor="delegate")
        obj = out["objections"][0]
        self.assertEqual(obj["author_writer"], "objector-1")  # untouched
        self.assertEqual(obj["resolved_by"], "delegate")

    def test_close_waive_abort_record_resolved_by(self):
        for fn, kwargs, actor in [
            (ps.close_promotion, {}, None),                      # default
            (ps.waive_promotion, {"reason": "solo"}, "delegate"),
            (ps.abort_promotion, {}, "delegate"),
        ]:
            conn = make_db()
            p = ps.open_promotion(conn, "p1", "1.0.0", window_hours=0)
            if actor:
                kwargs["actor"] = actor
            args = [conn, p["id"]] + ([kwargs.pop("reason")] if "reason" in kwargs else [])
            out = fn(*args, **kwargs)
            self.assertEqual(out["resolved_by"], actor or "operator")

    def test_upheld_resolution_stamps_resolver_on_promotion_abort(self):
        conn = make_db()
        p = ps.open_promotion(conn, "p1", "1.0.0")
        o = ps.add_objection(conn, p["id"], "eval regressed")
        out = ps.resolve_objection(conn, p["id"], o["id"], "upheld", "stands",
                                   actor="delegate")
        self.assertEqual(out["state"], "aborted")
        self.assertEqual(out["resolved_by"], "delegate")


class TestSealBookkeeping(unittest.TestCase):
    def test_mark_seal_success(self):
        conn = make_db()
        p = ps.open_promotion(conn, "p1", "1.0.0", window_hours=0)
        ps.close_promotion(conn, p["id"])
        out = ps.mark_seal_result(conn, p["id"], slug="promote-p1-1-0-0", citation_hash="abc")
        self.assertEqual(out["sealed"], 1)
        self.assertEqual(out["thread_slug"], "promote-p1-1-0-0")
        self.assertIsNone(out["seal_error"])

    def test_mark_seal_failure_keeps_status_flip(self):
        conn = make_db()
        p = ps.open_promotion(conn, "p1", "1.0.0", window_hours=0)
        ps.close_promotion(conn, p["id"])
        out = ps.mark_seal_result(conn, p["id"], error="ThreadHub is not reachable")
        self.assertEqual(out["sealed"], 0)
        self.assertIn("reachable", out["seal_error"])
        row = conn.execute("SELECT status FROM prompts WHERE id='p1'").fetchone()
        self.assertEqual(row["status"], "production")  # flip survives seal failure


if __name__ == "__main__":
    unittest.main()
