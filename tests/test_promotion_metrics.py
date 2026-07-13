"""Slice 5 — waive-ratio metrics (DR-2026-07-12-fcp-metrics).

Store-level tests for promotion_store.metrics plus API-layer tests for
GET /api/promotions/metrics. Definitions under test (must match the DR
verbatim — the DR seals them immutable):

- terminal FCP outcomes: promotions.state in ('closed', 'waived', 'aborted')
- fcp_waive_ratio(window_days) = waived terminal outcomes / all terminal
  outcomes, windowed on resolved_at; denominator 0 -> JSON null, never 0.0
- externally_contested_ratio(window_days) = terminal outcomes whose FCP
  window had >= 1 token invitation / all terminal outcomes; the fcp_tokens
  table does not exist until Slice 6, so table-absence is disclosed, not
  papered over.

The synthetic fcp_tokens table created below pins the Slice 6 query contract
ahead of the table's real migration — see promotion_store.metrics for the
contract comment.
"""
import json
import os
import sqlite3
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import promotion_store
from test_promotions_api import MockHandler

SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql"
)

_TS = "%Y-%m-%dT%H:%M:%SZ"


def _iso_days_ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=float(days))).strftime(_TS)


class MetricsTestCase(unittest.TestCase):
    """Shared in-memory SQLite (same pattern as test_promotions_api) seeded
    with schema.sql; promotions rows are inserted directly so tests control
    resolved_at for window filtering."""

    def setUp(self):
        self.db_uri = f"file:promo_metrics_{uuid.uuid4().hex}?mode=memory&cache=shared"
        self.conn = sqlite3.connect(self.db_uri, uri=True)
        self.conn.row_factory = sqlite3.Row
        with open(SCHEMA_PATH) as f:
            self.conn.executescript(f.read())
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _insert(self, state, resolved_days_ago=1, prompt_id="p1", version="1.0.0"):
        """Insert a promotion row directly. Terminal rows get resolved_at;
        open rows keep it NULL (they never enter the metrics)."""
        resolved = _iso_days_ago(resolved_days_ago) if state != "open" else None
        cur = self.conn.execute(
            """INSERT INTO promotions
               (prompt_id, version, state, opened_at, window_hours, closes_at,
                resolved_at, waive_reason)
               VALUES (?,?,?,?,?,?,?,?)""",
            (prompt_id, version, state,
             _iso_days_ago(resolved_days_ago + 1), 24.0,
             _iso_days_ago(resolved_days_ago), resolved,
             "solo window" if state == "waived" else None))
        self.conn.commit()
        return cur.lastrowid

    def _create_fcp_tokens_table(self):
        """Synthetic fcp_tokens table pinning the Slice 6 query contract:
        per-invitation rows with promotion_id + minted_at (UTC, _TS format).
        Slice 6's real migration may add columns but must keep these two."""
        self.conn.execute(
            """CREATE TABLE fcp_tokens (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 promotion_id INTEGER NOT NULL,
                 minted_at TEXT NOT NULL
               )""")
        self.conn.commit()

    def _mint_token(self, promotion_id, minted_days_ago):
        self.conn.execute(
            "INSERT INTO fcp_tokens (promotion_id, minted_at) VALUES (?,?)",
            (promotion_id, _iso_days_ago(minted_days_ago)))
        self.conn.commit()


class TestMetricsStore(MetricsTestCase):
    def test_empty_db_null_ratios_with_counts(self):
        m = promotion_store.metrics(self.conn)
        self.assertEqual(m["terminal_total"], 0)
        self.assertEqual(m["waived"], 0)
        self.assertEqual(m["invited"], 0)
        self.assertIsNone(m["fcp_waive_ratio"])          # null, never 0.0
        self.assertIsNone(m["externally_contested_ratio"])
        self.assertIsNone(m["window_days"])              # all-time

    def test_five_closed_clean_is_zero_ratio_not_null(self):
        for _ in range(5):
            self._insert("closed")
        m = promotion_store.metrics(self.conn)
        self.assertEqual(m["terminal_total"], 5)
        self.assertEqual(m["waived"], 0)
        self.assertIsNotNone(m["fcp_waive_ratio"])
        self.assertEqual(m["fcp_waive_ratio"], 0.0)      # measured zero, not absent
        self.assertEqual(m["externally_contested_ratio"], 0.0)

    def test_waived_row_moves_the_ratio(self):
        for _ in range(4):
            self._insert("closed")
        self._insert("waived")
        m = promotion_store.metrics(self.conn)
        self.assertEqual(m["terminal_total"], 5)
        self.assertEqual(m["waived"], 1)
        self.assertAlmostEqual(m["fcp_waive_ratio"], 0.2)

    def test_terminal_states_are_closed_waived_aborted(self):
        self._insert("closed")
        self._insert("waived")
        self._insert("aborted")
        self._insert("open")  # non-terminal: excluded
        m = promotion_store.metrics(self.conn)
        self.assertEqual(m["terminal_total"], 3)
        self.assertEqual(
            promotion_store.TERMINAL_STATES,
            (promotion_store.CLOSED, promotion_store.WAIVED, promotion_store.ABORTED))

    def test_window_filters_on_resolved_at(self):
        self._insert("waived", resolved_days_ago=30)
        self._insert("closed", resolved_days_ago=1)
        m = promotion_store.metrics(self.conn, window_days=7)
        self.assertEqual(m["window_days"], 7)
        self.assertEqual(m["terminal_total"], 1)
        self.assertEqual(m["waived"], 0)
        self.assertEqual(m["fcp_waive_ratio"], 0.0)
        # all-time sees both
        m_all = promotion_store.metrics(self.conn)
        self.assertEqual(m_all["terminal_total"], 2)
        self.assertAlmostEqual(m_all["fcp_waive_ratio"], 0.5)

    def test_window_with_no_outcomes_is_null_not_zero(self):
        self._insert("closed", resolved_days_ago=30)
        m = promotion_store.metrics(self.conn, window_days=7)
        self.assertEqual(m["terminal_total"], 0)
        self.assertIsNone(m["fcp_waive_ratio"])
        self.assertIsNone(m["externally_contested_ratio"])

    def test_tokens_table_absent_discloses(self):
        for _ in range(5):
            self._insert("closed")
        m = promotion_store.metrics(self.conn)
        self.assertEqual(m["invited"], 0)
        self.assertEqual(m["externally_contested_ratio"], 0.0)
        self.assertEqual(m["contested_data"],
                         promotion_store.CONTESTED_DATA_ABSENT)
        self.assertIn("no token table yet", m["contested_data"])

    def test_tokens_table_present_counts_invitations(self):
        self._create_fcp_tokens_table()
        # A: invitation minted before resolved_at -> contested
        a = self._insert("closed", resolved_days_ago=2)
        self._mint_token(a, minted_days_ago=3)
        # B: token minted AFTER resolved_at -> not an invitation to B's window
        b = self._insert("closed", resolved_days_ago=2)
        self._mint_token(b, minted_days_ago=1)
        # C: two invitations count the outcome once
        c = self._insert("waived", resolved_days_ago=2)
        self._mint_token(c, minted_days_ago=4)
        self._mint_token(c, minted_days_ago=3)
        # D: no invitations at all
        self._insert("closed", resolved_days_ago=2)
        m = promotion_store.metrics(self.conn)
        self.assertEqual(m["terminal_total"], 4)
        self.assertEqual(m["invited"], 2)
        self.assertAlmostEqual(m["externally_contested_ratio"], 0.5)
        self.assertEqual(m["contested_data"],
                         promotion_store.CONTESTED_DATA_MEASURED)

    def test_tokens_respect_window_filter(self):
        self._create_fcp_tokens_table()
        old = self._insert("closed", resolved_days_ago=30)
        self._mint_token(old, minted_days_ago=31)
        m = promotion_store.metrics(self.conn, window_days=7)
        self.assertEqual(m["terminal_total"], 0)
        self.assertEqual(m["invited"], 0)
        self.assertIsNone(m["externally_contested_ratio"])


class TestMetricsApi(MetricsTestCase):
    def _get(self, path):
        h = MockHandler(self.db_uri)
        h.path = path
        h.do_GET()
        return h

    def test_endpoint_shape_and_json_null(self):
        h = self._get("/api/promotions/metrics")
        self.assertEqual(h._last_status, 200)
        body = h._json()
        for key in ("window_days", "terminal_total", "waived", "fcp_waive_ratio",
                    "invited", "externally_contested_ratio", "contested_data",
                    "computed_at"):
            self.assertIn(key, body)
        # JSON null (not 0.0) on the empty DB — over the wire, not just in Python
        raw = json.loads(h._body_written.decode("utf-8"))
        self.assertIsNone(raw["fcp_waive_ratio"])
        self.assertIsNone(raw["externally_contested_ratio"])
        self.assertIsNone(raw["window_days"])
        self.assertEqual(raw["terminal_total"], 0)

    def test_endpoint_window_param(self):
        self._insert("waived", resolved_days_ago=30)
        self._insert("closed", resolved_days_ago=1)
        h = self._get("/api/promotions/metrics?window=7")
        self.assertEqual(h._last_status, 200)
        body = h._json()
        self.assertEqual(body["window_days"], 7)
        self.assertEqual(body["terminal_total"], 1)
        self.assertEqual(body["fcp_waive_ratio"], 0.0)

    def test_endpoint_rejects_bad_window(self):
        for bad in ("abc", "0", "-3", "1.5"):
            h = self._get(f"/api/promotions/metrics?window={bad}")
            self.assertEqual(h._last_status, 422, f"window={bad}")
            self.assertIn("error", h._json())

    def test_endpoint_does_not_shadow_promotion_lookup(self):
        pid = self._insert("closed")
        h = self._get(f"/api/promotions/{pid}")
        self.assertEqual(h._last_status, 200)
        self.assertEqual(h._json()["id"], pid)


if __name__ == "__main__":
    unittest.main()
