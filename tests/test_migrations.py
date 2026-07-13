"""Phase 5 slice 2 migration tests: actor columns are added by guarded
pragma-table_info ALTERs, idempotently, and fresh schema.sql already carries them."""
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server

SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")

# The pre-slice-2 table shapes, verbatim — what an existing deployed DB has.
OLD_SCHEMA = """
CREATE TABLE promotions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id TEXT NOT NULL,
    version TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'open',
    opened_at TEXT NOT NULL,
    window_hours REAL NOT NULL DEFAULT 24,
    closes_at TEXT NOT NULL,
    resolved_at TEXT,
    evidence_json TEXT,
    thread_slug TEXT,
    citation_hash TEXT,
    sealed INTEGER NOT NULL DEFAULT 0,
    seal_error TEXT,
    waive_reason TEXT
);
CREATE TABLE promotion_objections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    promotion_id INTEGER NOT NULL,
    raised_at TEXT NOT NULL,
    body TEXT NOT NULL,
    resolution TEXT,
    resolution_body TEXT
);
"""

PROMOTION_ACTOR_COLS = {"opened_by", "resolved_by"}
OBJECTION_ACTOR_COLS = {"author_writer", "resolved_by", "channel", "token_id",
                        "sealed_record_hash"}


def cols(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


class TestActorColumnMigration(unittest.TestCase):
    def test_migrates_old_db_and_preserves_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(OLD_SCHEMA)
        conn.execute(
            "INSERT INTO promotions (prompt_id, version, opened_at, closes_at)"
            " VALUES ('p1','1.0.0','t0','t1')")
        conn.execute(
            "INSERT INTO promotion_objections (promotion_id, raised_at, body)"
            " VALUES (1,'t0','concern')")
        conn.commit()
        server.migrate_actor_columns(conn)
        self.assertTrue(PROMOTION_ACTOR_COLS <= cols(conn, "promotions"))
        self.assertTrue(OBJECTION_ACTOR_COLS <= cols(conn, "promotion_objections"))
        row = conn.execute("SELECT prompt_id, opened_by FROM promotions").fetchone()
        self.assertEqual(row[0], "p1")
        self.assertIsNone(row[1])  # pre-migration rows: actor unknown, not faked

    def test_migration_is_idempotent(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(OLD_SCHEMA)
        server.migrate_actor_columns(conn)
        before = (cols(conn, "promotions"), cols(conn, "promotion_objections"))
        server.migrate_actor_columns(conn)  # re-run must be a no-op, not an error
        self.assertEqual(before,
                         (cols(conn, "promotions"), cols(conn, "promotion_objections")))

    def test_noop_when_tables_absent(self):
        conn = sqlite3.connect(":memory:")
        server.migrate_actor_columns(conn)  # must not raise

    def test_fresh_schema_already_carries_actor_columns(self):
        conn = sqlite3.connect(":memory:")
        with open(SCHEMA_PATH) as f:
            conn.executescript(f.read())
        self.assertTrue(PROMOTION_ACTOR_COLS <= cols(conn, "promotions"))
        self.assertTrue(OBJECTION_ACTOR_COLS <= cols(conn, "promotion_objections"))
        self.assertIn("writers", {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")})
        server.migrate_actor_columns(conn)  # no-op on fresh schema

    def test_init_db_is_idempotent_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "studio.db")
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                server.init_db()  # re-running the full boot path is a no-op
            conn = sqlite3.connect(db)
            try:
                self.assertTrue(PROMOTION_ACTOR_COLS <= cols(conn, "promotions"))
                self.assertTrue(OBJECTION_ACTOR_COLS <= cols(conn, "promotion_objections"))
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
