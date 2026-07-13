"""Writer identity registry tests (Phase 5 slice 2, DR-phase5-topology 5.2/5.5).

All ThreadHub traffic is faked — no live hub, no real minting, ever.
"""
import os
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import seal
import writers

SCHEMA = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "schema.sql")).read()


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


class TestEnsureWriter(unittest.TestCase):
    def test_operator_mints_custodial_human_identity(self):
        conn = make_db()
        with patch("seal._th", return_value={"id": "id_troy1"}) as th:
            w = writers.ensure_writer(conn, "operator")
        self.assertEqual(w["name"], "operator")
        self.assertEqual(w["threadhub_id"], "id_troy1")
        self.assertEqual(w["display_name"], "Troy")
        self.assertEqual(w["kind"], "human")
        self.assertTrue(w["custodial"])
        th.assert_called_once_with("POST", "/identities",
                                   {"display_name": "Troy", "kind": "human"})
        # no key material stored anywhere (rule 5.5)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(writers)")]
        self.assertNotIn("private_key", cols)
        self.assertNotIn("public_key", cols)

    def test_delegate_defaults(self):
        conn = make_db()
        with patch("seal._th", return_value={"id": "id_del1"}) as th:
            w = writers.ensure_writer(conn, "delegate")
        self.assertEqual(w["display_name"], "Claude (delegate)")
        self.assertEqual(w["kind"], "agent")
        th.assert_called_once_with("POST", "/identities",
                                   {"display_name": "Claude (delegate)", "kind": "agent"})

    def test_ensure_is_idempotent_no_second_mint(self):
        conn = make_db()
        with patch("seal._th", return_value={"id": "id_troy1"}) as th:
            first = writers.ensure_writer(conn, "operator")
            second = writers.ensure_writer(conn, "operator")
        self.assertEqual(first, second)
        self.assertEqual(th.call_count, 1)

    def test_mint_first_insert_after_mint_failure_leaves_no_row(self):
        conn = make_db()
        with patch("seal._th", side_effect=seal.SealError("ThreadHub is not reachable",
                                                          status=502)):
            with self.assertRaises(seal.SealError):
                writers.ensure_writer(conn, "operator")
        row = conn.execute("SELECT * FROM writers WHERE name='operator'").fetchone()
        self.assertIsNone(row)

    def test_studio_adopts_legacy_seal_author_id_without_reminting(self):
        conn = make_db()
        cache = os.path.join(os.path.dirname(__file__), "_writers_author_cache")
        with open(cache, "w") as f:
            f.write("id_f71531f1d383")
        orig = seal.AUTHOR_CACHE
        seal.AUTHOR_CACHE = cache
        try:
            with patch("seal._th") as th:
                w = writers.ensure_writer(conn, "studio")
            th.assert_not_called()  # adopted, not re-minted
        finally:
            seal.AUTHOR_CACHE = orig
            os.remove(cache)
        self.assertEqual(w["threadhub_id"], "id_f71531f1d383")
        self.assertEqual(w["display_name"], "Prompt Studio")
        self.assertEqual(w["kind"], "agent")

    def test_unknown_writer_without_details_raises(self):
        conn = make_db()
        with patch("seal._th") as th:
            with self.assertRaises(writers.WriterError):
                writers.ensure_writer(conn, "rando")
            th.assert_not_called()

    def test_custom_writer_mints_with_explicit_details(self):
        conn = make_db()
        with patch("seal._th", return_value={"id": "id_obj1"}) as th:
            w = writers.ensure_writer(conn, "objector-1",
                                      display_name="External Objector", kind="human")
        self.assertEqual(w["threadhub_id"], "id_obj1")
        th.assert_called_once_with("POST", "/identities",
                                   {"display_name": "External Objector", "kind": "human"})

    def test_distinct_writers_get_distinct_identities(self):
        # DR 5.2: DISTINCT identity per writer, never shared.
        conn = make_db()
        with patch("seal._th", side_effect=[{"id": "id_a"}, {"id": "id_b"}]):
            op = writers.ensure_writer(conn, "operator")
            dl = writers.ensure_writer(conn, "delegate")
        self.assertNotEqual(op["threadhub_id"], dl["threadhub_id"])


class TestGetWriter(unittest.TestCase):
    def test_lookup_missing_returns_none_and_never_mints(self):
        conn = make_db()
        with patch("seal._th") as th:
            self.assertIsNone(writers.get_writer(conn, "operator"))
            th.assert_not_called()

    def test_lookup_returns_inserted_row(self):
        conn = make_db()
        with patch("seal._th", return_value={"id": "id_x"}):
            writers.ensure_writer(conn, "operator")
        w = writers.get_writer(conn, "operator")
        self.assertEqual(w["threadhub_id"], "id_x")
        self.assertTrue(w["custodial"])


if __name__ == "__main__":
    unittest.main()
