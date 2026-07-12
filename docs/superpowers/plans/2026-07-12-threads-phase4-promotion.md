# Threads Phase 4 — Promotion as Recorded ClisTa Decision: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Registry promotion opens a time-boxed FCP (final comment period) with pinned eval evidence, and every terminal outcome (closed/waived/aborted/demoted) seals a decision-as-claim record to ThreadHub.

**Architecture:** Three new stdlib-Python modules beside `seal.py` — `promotion_store.py` (SQLite state machine), `promotion_evidence.py` (pin latest eval run + content hash), `promotion_seal.py` (build the decision-as-claim payload) — wired into thin handlers in `server.py`. UI in the existing registry widget iframe; picker filter in `sandbox/js/registry.js`. Sealing reuses Phase 2's `seal.seal_decision()` custodial path unchanged.

**Tech Stack:** Python 3 stdlib (`http.server`, `sqlite3`, `unittest`), vanilla JS ES modules with `node --test`, ThreadHub sidecar on :8110.

**Spec:** `docs/superpowers/specs/2026-07-12-threads-phase4-promotion-decision-design.md` — binding for all payload shapes and state-machine rules.

## Global Constraints

- Python stdlib only — no new pip dependencies (matches `server.py`/`seal.py`).
- Sealing goes ONLY through `seal.seal_decision(payload)` (Phase 2 custodial path). Never call ThreadHub write routes directly from new code. Never touch `packages/threadhub` internals — sidecar + proxy, never reimplement.
- Decision-as-claim only: the seal payload is `{title, question, decision, decidedBy, evidence, objections}`. No formal DecisionRequested/ReviewSubmitted/DecisionRecorded events.
- Timestamps: ISO-8601 UTC `strftime('%Y-%m-%dT%H:%M:%SZ')` — the format already used across `server.py`.
- Absence is disclosed, never faked: missing evidence → `evidence_attached: false` in the sealed record; waived window → `fcp_waived: true` + reason.
- Honesty boundary (verbatim in every promotion seal): "Inputs and scores are pinned and hash-verifiable; LLM outputs are nondeterministic, so a re-run is fresh evidence, not a replay. The chain proves what was recorded and when — not that the prompt is good."
- State machine invariants: at most one `open` promotion per (prompt_id, version); window elapse is evaluated lazily (no scheduler); an unresolved objection blocks close past the window; an `upheld` objection forces `aborted`; seal failure never un-flips `prompts.status` (record `sealed=0` + `seal_error`, retry via reseal).
- Python tests: `unittest`, run `python3 -m unittest tests.<module> -v` from repo root. JS tests: `node --test sandbox/js/`.

---

### Task 1: Promotions schema + `promotion_store.py` state machine

**Files:**
- Modify: `schema.sql` (append after the `evals` table)
- Create: `promotion_store.py`
- Test: `tests/test_promotion_store.py`

**Interfaces:**
- Produces: `promotion_store.PromotionError(message, status)` with `.message`/`.status`; `open_promotion(conn, prompt_id, version, window_hours=24.0, evidence=None) -> dict`; `get_promotion(conn, pid) -> dict`; `list_promotions(conn) -> list[dict]`; `add_objection(conn, pid, body) -> dict`; `resolve_objection(conn, pid, oid, resolution, body) -> dict`; `close_promotion(conn, pid) -> dict`; `waive_promotion(conn, pid, reason) -> dict`; `abort_promotion(conn, pid) -> dict`; `mark_seal_result(conn, pid, slug=None, citation_hash=None, error=None) -> dict`. Every returned promotion dict includes keys `id, prompt_id, version, state, opened_at, window_hours, closes_at, resolved_at, evidence, thread_slug, citation_hash, sealed, seal_error, waive_reason, objections (list of dicts), window_elapsed (bool), unresolved_objections (int)`.
- Consumes: existing `prompts` table (composite PK `(id, version)`).

- [ ] **Step 1: Append the two tables to `schema.sql`**

```sql
CREATE TABLE IF NOT EXISTS promotions (
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

CREATE TABLE IF NOT EXISTS promotion_objections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    promotion_id INTEGER NOT NULL,
    raised_at TEXT NOT NULL,
    body TEXT NOT NULL,
    resolution TEXT,
    resolution_body TEXT
);
```

(`init_db()` runs `conn.executescript(schema)` on every start, so `IF NOT EXISTS` is the whole migration.)

- [ ] **Step 2: Write failing tests**

`tests/test_promotion_store.py` — follow `tests/test_seal.py` conventions (unittest, top-of-file `sys.path.insert`). Use an in-memory DB seeded with the schema and one draft prompt:

```python
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
        self.assertEqual(row["eval_status"], "validated")

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
```

- [ ] **Step 3: Run tests, confirm they fail**

Run: `python3 -m unittest tests.test_promotion_store -v`
Expected: `ModuleNotFoundError: No module named 'promotion_store'`

- [ ] **Step 4: Implement `promotion_store.py`**

```python
"""Promotion FCP state machine over SQLite. No HTTP, no sealing — pure storage + rules.

States: open -> closed | waived | aborted. Window elapse is evaluated lazily on read;
there is no scheduler. An unresolved objection blocks close even past the window; an
upheld objection forces abort. Seal outcome is bookkeeping only (sealed/seal_error) —
a failed seal never un-flips prompts.status.
"""
import json
from datetime import datetime, timedelta, timezone

OPEN, CLOSED, WAIVED, ABORTED = "open", "closed", "waived", "aborted"
_TS = "%Y-%m-%dT%H:%M:%SZ"


class PromotionError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status = status
        super().__init__(message)


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.strftime(_TS)


def _parse(ts):
    return datetime.strptime(ts, _TS).replace(tzinfo=timezone.utc)


def get_promotion(conn, pid):
    row = conn.execute("SELECT * FROM promotions WHERE id=?", (pid,)).fetchone()
    if row is None:
        raise PromotionError("promotion not found", 404)
    p = dict(row)
    p["evidence"] = json.loads(p.pop("evidence_json")) if p.get("evidence_json") else None
    p["objections"] = [dict(o) for o in conn.execute(
        "SELECT * FROM promotion_objections WHERE promotion_id=? ORDER BY id", (pid,))]
    p["window_elapsed"] = _now() >= _parse(p["closes_at"])
    p["unresolved_objections"] = sum(
        1 for o in p["objections"] if o["resolution"] is None)
    return p


def list_promotions(conn):
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM promotions ORDER BY id DESC")]
    return [get_promotion(conn, i) for i in ids]


def open_promotion(conn, prompt_id, version, window_hours=24.0, evidence=None):
    row = conn.execute("SELECT status FROM prompts WHERE id=? AND version=?",
                       (prompt_id, version)).fetchone()
    if row is None:
        raise PromotionError("prompt/version not found", 404)
    if row["status"] == "production":
        raise PromotionError("already in production", 409)
    dup = conn.execute(
        "SELECT id FROM promotions WHERE prompt_id=? AND version=? AND state=?",
        (prompt_id, version, OPEN)).fetchone()
    if dup:
        raise PromotionError(
            f"promotion {dup['id']} already open for {prompt_id}@{version}", 409)
    opened = _now()
    closes = opened + timedelta(hours=float(window_hours))
    cur = conn.execute(
        """INSERT INTO promotions
           (prompt_id, version, state, opened_at, window_hours, closes_at, evidence_json)
           VALUES (?,?,?,?,?,?,?)""",
        (prompt_id, version, OPEN, _iso(opened), float(window_hours), _iso(closes),
         json.dumps(evidence) if evidence is not None else None))
    conn.commit()
    return get_promotion(conn, cur.lastrowid)


def _require_open(conn, pid):
    p = get_promotion(conn, pid)
    if p["state"] != OPEN:
        raise PromotionError(f"promotion is {p['state']}, not open", 409)
    return p


def add_objection(conn, pid, body):
    _require_open(conn, pid)
    body = (body or "").strip()
    if not body:
        raise PromotionError("objection body required", 422)
    cur = conn.execute(
        "INSERT INTO promotion_objections (promotion_id, raised_at, body) VALUES (?,?,?)",
        (pid, _iso(_now()), body))
    conn.commit()
    return dict(conn.execute("SELECT * FROM promotion_objections WHERE id=?",
                             (cur.lastrowid,)).fetchone())


def resolve_objection(conn, pid, oid, resolution, body):
    _require_open(conn, pid)
    if resolution not in ("responded", "upheld"):
        raise PromotionError("resolution must be 'responded' or 'upheld'", 422)
    body = (body or "").strip()
    if not body:
        raise PromotionError("resolution body required", 422)
    row = conn.execute(
        "SELECT * FROM promotion_objections WHERE id=? AND promotion_id=?",
        (oid, pid)).fetchone()
    if row is None:
        raise PromotionError("objection not found", 404)
    if row["resolution"] is not None:
        raise PromotionError("objection already resolved", 409)
    conn.execute(
        "UPDATE promotion_objections SET resolution=?, resolution_body=? WHERE id=?",
        (resolution, body, oid))
    conn.commit()
    if resolution == "upheld":
        return _terminate(conn, pid, ABORTED)  # upheld objection forces abort
    return get_promotion(conn, pid)


def _flip_to_production(conn, prompt_id, version):
    conn.execute(
        """UPDATE prompts SET status='production', eval_status='validated',
           updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=? AND version=?""",
        (prompt_id, version))


def _terminate(conn, pid, state, waive_reason=None, flip=False):
    p = _require_open(conn, pid)
    if flip:
        _flip_to_production(conn, p["prompt_id"], p["version"])
    conn.execute(
        "UPDATE promotions SET state=?, resolved_at=?, waive_reason=? WHERE id=?",
        (state, _iso(_now()), waive_reason, pid))
    conn.commit()
    return get_promotion(conn, pid)


def close_promotion(conn, pid):
    p = _require_open(conn, pid)
    if not p["window_elapsed"]:
        raise PromotionError(
            f"window open until {p['closes_at']} — close later or waive", 409)
    if p["unresolved_objections"]:
        raise PromotionError(
            f"{p['unresolved_objections']} unresolved objection(s) block close", 409)
    return _terminate(conn, pid, CLOSED, flip=True)


def waive_promotion(conn, pid, reason):
    reason = (reason or "").strip()
    if not reason:
        raise PromotionError("waive reason required", 422)
    return _terminate(conn, pid, WAIVED, waive_reason=reason, flip=True)


def abort_promotion(conn, pid):
    return _terminate(conn, pid, ABORTED)


def mark_seal_result(conn, pid, slug=None, citation_hash=None, error=None):
    if error is None:
        conn.execute(
            "UPDATE promotions SET sealed=1, seal_error=NULL, thread_slug=?, citation_hash=? WHERE id=?",
            (slug, citation_hash, pid))
    else:
        conn.execute("UPDATE promotions SET sealed=0, seal_error=? WHERE id=?",
                     (str(error), pid))
    conn.commit()
    return get_promotion(conn, pid)
```

- [ ] **Step 5: Run tests, confirm all pass**

Run: `python3 -m unittest tests.test_promotion_store -v`
Expected: all PASS. Also run the full suite to prove no regressions: `python3 -m unittest discover tests -v`

- [ ] **Step 6: Commit**

```bash
git add schema.sql promotion_store.py tests/test_promotion_store.py
git commit -m "feat(threads-p4): promotions FCP state machine + schema"
```

---

### Task 2: Evidence pinning — `promotion_evidence.py`

**Files:**
- Create: `promotion_evidence.py`
- Test: `tests/test_promotion_evidence.py`

**Interfaces:**
- Produces: `pin_evidence(prompt_id, version, evals_dir=None) -> dict | None`. Returns `None` when no eval file exists. The dict: `{"source_file": str, "model": str|None, "tokens": dict|None, "run_at": str|None, "content_hash": "sha256:<hex>", "rerun": str}`.
- Consumes: eval output files written by `scripts/evaluate_prompt.py` as `registry/evals/eval_<prompt_id>_v<version-dots-as-underscores>_*_data.json` (see `build_eval_id` in that script).

- [ ] **Step 1: Write failing tests**

```python
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import promotion_evidence as pe


def write_eval(d, name, payload):
    path = os.path.join(d, name)
    with open(path, "w") as f:
        json.dump(payload, f)
    return path


class TestPinEvidence(unittest.TestCase):
    def test_none_when_no_eval_exists(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(pe.pin_evidence("p1", "1.0.0", evals_dir=d))

    def test_pins_latest_matching_eval(self):
        with tempfile.TemporaryDirectory() as d:
            write_eval(d, "eval_p1_v1_0_0_2026-06-01_m_data.json",
                       {"model": "old", "tokens": {"total": 1}})
            newer = write_eval(d, "eval_p1_v1_0_0_2026-07-01_m_data.json",
                               {"model": "claude-sonnet-4-6", "tokens": {"total": 2},
                                "date": "2026-07-01"})
            os.utime(newer, None)  # ensure newest mtime
            out = pe.pin_evidence("p1", "1.0.0", evals_dir=d)
            self.assertEqual(out["model"], "claude-sonnet-4-6")
            self.assertEqual(out["source_file"], "eval_p1_v1_0_0_2026-07-01_m_data.json")
            self.assertTrue(out["content_hash"].startswith("sha256:"))
            self.assertIn("evaluate_prompt.py", out["rerun"])

    def test_hash_is_over_file_bytes_and_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            write_eval(d, "eval_p1_v1_0_0_x_data.json", {"model": "m"})
            a = pe.pin_evidence("p1", "1.0.0", evals_dir=d)
            b = pe.pin_evidence("p1", "1.0.0", evals_dir=d)
            self.assertEqual(a["content_hash"], b["content_hash"])

    def test_other_prompts_evals_not_matched(self):
        with tempfile.TemporaryDirectory() as d:
            write_eval(d, "eval_OTHER_v1_0_0_x_data.json", {"model": "m"})
            self.assertIsNone(pe.pin_evidence("p1", "1.0.0", evals_dir=d))
```

- [ ] **Step 2: Run tests, confirm ModuleNotFoundError**

Run: `python3 -m unittest tests.test_promotion_evidence -v`

- [ ] **Step 3: Implement `promotion_evidence.py`**

```python
"""Pin the latest eval run for a prompt version as promotion evidence.

Attach-latest strategy (decided at plan time): promotion does NOT invoke the
Claude API synchronously; it pins the newest existing
registry/evals/eval_<id>_v<ver>_*_data.json written by scripts/evaluate_prompt.py.
The content_hash is sha256 over the file bytes — the whole eval record is pinned,
not a summary of it.
"""
import hashlib
import json
import os
from pathlib import Path

DEFAULT_EVALS_DIR = Path(__file__).resolve().parent / "registry" / "evals"


def pin_evidence(prompt_id, version, evals_dir=None):
    evals_dir = Path(evals_dir) if evals_dir else DEFAULT_EVALS_DIR
    safe_version = version.replace(".", "_")
    pattern = f"eval_{prompt_id}_v{safe_version}_*_data.json"
    candidates = sorted(evals_dir.glob(pattern), key=lambda p: p.stat().st_mtime)
    if not candidates:
        return None
    path = candidates[-1]
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        data = {}
    model = data.get("model")
    return {
        "source_file": path.name,
        "model": model,
        "tokens": data.get("tokens"),
        "run_at": data.get("date") or data.get("run_at"),
        "content_hash": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "rerun": ("python3 scripts/evaluate_prompt.py --prompt <archived prompt file> "
                  f"--model {model or '<model>'} --output-dir registry/evals/"),
    }
```

- [ ] **Step 4: Run tests, confirm pass; run full suite**

Run: `python3 -m unittest tests.test_promotion_evidence -v` then `python3 -m unittest discover tests -v`

- [ ] **Step 5: Commit**

```bash
git add promotion_evidence.py tests/test_promotion_evidence.py
git commit -m "feat(threads-p4): pin latest eval run as promotion evidence"
```

---

### Task 3: Seal payload builder — `promotion_seal.py`

**Files:**
- Create: `promotion_seal.py`
- Test: `tests/test_promotion_seal.py`

**Interfaces:**
- Produces: `HONESTY_BOUNDARY` (str constant); `build_seal_payload(promotion, outcome, decided_by) -> dict` where `promotion` is a `promotion_store` dict, `outcome` is `"promoted" | "aborted"`, and the return value is a valid `seal.validate_payload` input; `build_demotion_payload(prompt_id, version, reason, decided_by, superseded_slug=None) -> dict`.
- Consumes: `seal.validate_payload` contract — `{title, question, decision, decidedBy, evidence: [{source, finding}], objections: [str]}`, evidence non-empty.

- [ ] **Step 1: Write failing tests**

```python
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


class TestDemotionPayload(unittest.TestCase):
    def test_validates_and_references_superseded_slug(self):
        p = psl.build_demotion_payload("p1", "1.0.0", "superseded by 1.1.0",
                                       "Troy", superseded_slug="promote-p1-1-0-0")
        seal.validate_payload(p)
        self.assertIn("promote-p1-1-0-0", p["decision"])
```

- [ ] **Step 2: Run tests, confirm ModuleNotFoundError**

Run: `python3 -m unittest tests.test_promotion_seal -v`

- [ ] **Step 3: Implement `promotion_seal.py`**

```python
"""Build Phase-2 decision-as-claim seal payloads for promotion outcomes.

Owner decision 2026-07-12: sealing stays on the validated decision-as-claim
sequence; formal DecisionRequested/Review/DecisionRecorded remains deferred.
FCP metadata rides inside the claim text as a trailing JSON object ("FCP: {...}")
so the sealed record carries the window facts without new event types.
"""
import json

HONESTY_BOUNDARY = (
    "Inputs and scores are pinned and hash-verifiable; LLM outputs are "
    "nondeterministic, so a re-run is fresh evidence, not a replay. The chain "
    "proves what was recorded and when — not that the prompt is good.")


def _fcp_meta(promotion):
    return {
        "opened_at": promotion["opened_at"],
        "closes_at": promotion["closes_at"],
        "resolved_at": promotion["resolved_at"],
        "state": promotion["state"],
        "window_hours": promotion["window_hours"],
        "fcp_waived": promotion["state"] == "waived",
        "waive_reason": promotion["waive_reason"],
        "objection_count": len(promotion["objections"]),
        "evidence_attached": promotion["evidence"] is not None,
    }


def _evidence_items(promotion):
    ev = promotion["evidence"]
    if ev is None:
        return [{
            "source": "none",
            "finding": ("evidence_attached: false — promotion proceeded without a "
                        "pinned eval run; absence disclosed. " + HONESTY_BOUNDARY),
        }]
    return [{
        "source": f"eval:{ev['source_file']}",
        "finding": (f"Pinned eval run — model={ev.get('model')}, "
                    f"tokens={json.dumps(ev.get('tokens'))}, run_at={ev.get('run_at')}, "
                    f"content_hash={ev['content_hash']}. Re-run: {ev.get('rerun')}. "
                    + HONESTY_BOUNDARY),
    }]


def _objection_texts(promotion):
    out = []
    for o in promotion["objections"]:
        text = o["body"]
        if o.get("resolution"):
            text += f" [resolution: {o['resolution']} — {o.get('resolution_body', '')}]"
        out.append(text)
    return out


def build_seal_payload(promotion, outcome, decided_by):
    pid, ver = promotion["prompt_id"], promotion["version"]
    if outcome == "promoted":
        decision = f"{pid} {ver} promoted to production. FCP: "
    else:
        decision = f"{pid} {ver} NOT promoted (promotion aborted). FCP: "
    decision += json.dumps(_fcp_meta(promotion), sort_keys=True)
    return {
        "title": f"Promote {pid} v{ver} to production",
        "question": f"Should {pid} {ver} be promoted to production?",
        "decision": decision,
        "decidedBy": decided_by,
        "evidence": _evidence_items(promotion),
        "objections": _objection_texts(promotion),
    }


def build_demotion_payload(prompt_id, version, reason, decided_by, superseded_slug=None):
    ref = (f" Supersedes promotion record thread '{superseded_slug}'."
           if superseded_slug else " No prior promotion record found; absence disclosed.")
    return {
        "title": f"Deprecate {prompt_id} v{version}",
        "question": f"Should {prompt_id} {version} be deprecated?",
        "decision": f"{prompt_id} {version} deprecated: {reason}.{ref}",
        "decidedBy": decided_by,
        "evidence": [{"source": "registry",
                      "finding": f"status transition production->deprecated for {prompt_id}@{version}"}],
        "objections": [],
    }
```

- [ ] **Step 4: Run tests, confirm pass; run full suite**

Run: `python3 -m unittest tests.test_promotion_seal -v` then `python3 -m unittest discover tests -v`

- [ ] **Step 5: Commit**

```bash
git add promotion_seal.py tests/test_promotion_seal.py
git commit -m "feat(threads-p4): decision-as-claim seal payloads for promotion outcomes"
```

---

### Task 4: API routes + production-flip guards in `server.py`

**Files:**
- Modify: `server.py` — `do_GET`, `do_POST`, `handle_post_prompt_validate`, `handle_put_prompt`, new handlers; add `import promotion_store`, `import promotion_evidence`, `import promotion_seal` beside the existing `import seal`
- Test: `tests/test_promotions_api.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3, plus existing `seal.seal_decision(payload) -> {"slug", "citationHash"}`, `self.get_db()`, `self.send_json(data, status)`, `self.read_json_body()`.
- Produces routes (spec §API): `POST /api/prompts/<id>/promote/<version>`, `GET /api/promotions`, `GET /api/promotions/<pid>`, `POST /api/promotions/<pid>/object|close|waive|abort|reseal`, `POST /api/promotions/<pid>/objections/<oid>/resolve`, `POST /api/prompts/<id>/demote/<version>`. Terminal responses include the promotion dict plus `sealed`/`seal_error`/`thread_slug`.

- [ ] **Step 1: Write failing tests**

`tests/test_promotions_api.py` — copy the `MockHandler` pattern from `tests/test_server.py` (same in-memory DB override, `_set_body`, captured `send_json`/`send_error` output; have `get_db()` return a connection to a shared in-memory DB seeded with `schema.sql` + one draft prompt `('p1','1.0.0','draft')`). Mock `seal.seal_decision` with `unittest.mock.patch`. Cover:

```python
# Test names + assertions (implement all with the MockHandler pattern):

def test_promote_opens_fcp_and_does_not_flip_status(self): ...
    # POST /api/prompts/p1/promote/1.0.0 body {"window_hours": 24}
    # -> 200, state=open; prompts.status still 'draft'

def test_promote_attaches_pinned_evidence_when_available(self): ...
    # patch promotion_evidence.pin_evidence to return a dict -> promotion["evidence"] carries it

def test_promote_conflict_when_already_open(self): ...          # second POST -> 409
def test_validate_route_now_409_pointing_at_promote(self): ...
    # POST /api/prompts/p1/1.0.0/validate -> 409, body mentions "promote"
    # NOTE dispatch order: parts == [id, version, 'validate']
def test_put_prompt_rejects_direct_production_flip(self): ...
    # PUT /api/prompts/p1 body {..., "status": "production", "version": "1.0.0"} -> 409
def test_put_prompt_allows_production_to_production_edit(self): ...
    # seed status='production' -> same PUT succeeds (editing other fields)
def test_object_and_resolve_roundtrip(self): ...
def test_close_seals_and_records_slug(self): ...
    # window_hours=0; patch seal.seal_decision -> {"slug": "s", "citationHash": "h"}
    # POST close -> 200, sealed=1, thread_slug="s"; prompts.status='production'
def test_close_seal_failure_reports_sealed_false_and_keeps_flip(self): ...
    # patch seal.seal_decision to raise seal.SealError("ThreadHub is not reachable", status=502)
    # -> response sealed=0 with seal_error; status still flipped; then POST reseal with
    # working mock -> sealed=1
def test_waive_requires_reason_and_seals_with_fcp_waived(self): ...
    # assert the payload passed to seal.seal_decision contains '"fcp_waived": true'
def test_upheld_resolution_aborts_and_seals_abort(self): ...
    # resolve upheld -> state=aborted, seal called with 'NOT promoted' decision
def test_demote_flips_to_deprecated_and_references_promotion_slug(self): ...
    # after a sealed close, POST /api/prompts/p1/demote/1.0.0 {"reason": "superseded"}
    # -> status='deprecated'; seal payload decision contains the promotion's slug
```

- [ ] **Step 2: Run tests, confirm failures (404s from missing routes)**

Run: `python3 -m unittest tests.test_promotions_api -v`

- [ ] **Step 3: Implement dispatch + handlers**

`do_POST` — replace the `/api/prompts/` branch and add `/api/promotions/`:

```python
        elif self.path.startswith('/api/prompts/'):
            parts = self.path.removeprefix('/api/prompts/').split('/')
            if len(parts) == 2 and parts[1] == 'draft':
                self.handle_post_prompt_draft(parts[0])
            elif len(parts) == 3 and parts[2] == 'validate':
                self.handle_post_prompt_validate(parts[0], parts[1])
            elif len(parts) == 3 and parts[1] == 'promote':
                self.handle_post_promote(parts[0], parts[2])
            elif len(parts) == 3 and parts[1] == 'demote':
                self.handle_post_demote(parts[0], parts[2])
            else:
                self.send_error(404)
        elif self.path.startswith('/api/promotions/'):
            parts = self.path.removeprefix('/api/promotions/').split('/')
            if len(parts) == 2 and parts[1] in ('object', 'close', 'waive', 'abort', 'reseal'):
                self.handle_promotion_action(parts[0], parts[1])
            elif len(parts) == 4 and parts[1] == 'objections' and parts[3] == 'resolve':
                self.handle_objection_resolve(parts[0], parts[2])
            else:
                self.send_error(404)
```

`do_GET` — add before the `/api/threads` branches:

```python
        elif self.path == '/api/promotions':
            self.handle_get_promotions()
        elif self.path.startswith('/api/promotions/'):
            self.handle_get_promotion(self.path.removeprefix('/api/promotions/'))
```

Handlers (all thin; `promotion_store` raises `PromotionError` with the right status):

```python
    def _promotion_error(self, e):
        self.send_json({"error": e.message}, status=e.status)

    def _decided_by(self, conn, prompt_id, version):
        row = conn.execute("SELECT owner FROM prompts WHERE id=? AND version=?",
                           (prompt_id, version)).fetchone()
        return (row["owner"] if row and row["owner"] else "Prompt Studio owner")

    def _seal_promotion(self, conn, promotion, outcome):
        """Seal a terminal promotion; never raises — failure is recorded, not fatal."""
        payload = promotion_seal.build_seal_payload(
            promotion, outcome,
            self._decided_by(conn, promotion["prompt_id"], promotion["version"]))
        try:
            result = seal.seal_decision(payload)
            return promotion_store.mark_seal_result(
                conn, promotion["id"], slug=result["slug"],
                citation_hash=result.get("citationHash"))
        except (seal.SealError, seal.SealValidationError) as e:
            msg = getattr(e, "message", None) or str(e)
            return promotion_store.mark_seal_result(conn, promotion["id"], error=msg)

    def handle_post_promote(self, prompt_id, version):
        data = self.read_json_body()
        if data is None:
            return
        evidence = data.get("evidence") or promotion_evidence.pin_evidence(prompt_id, version)
        conn = self.get_db()
        try:
            try:
                p = promotion_store.open_promotion(
                    conn, prompt_id, version,
                    window_hours=data.get("window_hours", 24), evidence=evidence)
            except promotion_store.PromotionError as e:
                self._promotion_error(e)
                return
        finally:
            conn.close()
        self.send_json(p, status=200)

    def handle_get_promotions(self):
        conn = self.get_db()
        try:
            self.send_json(promotion_store.list_promotions(conn))
        finally:
            conn.close()

    def handle_get_promotion(self, pid):
        conn = self.get_db()
        try:
            try:
                self.send_json(promotion_store.get_promotion(conn, pid))
            except promotion_store.PromotionError as e:
                self._promotion_error(e)
        finally:
            conn.close()

    def handle_promotion_action(self, pid, action):
        data = self.read_json_body() if action in ('object', 'waive') else {}
        if data is None:
            return
        conn = self.get_db()
        try:
            try:
                if action == 'object':
                    self.send_json(promotion_store.add_objection(conn, pid, data.get("body")))
                    return
                if action == 'close':
                    p = promotion_store.close_promotion(conn, pid)
                    self.send_json(self._seal_promotion(conn, p, "promoted"))
                    return
                if action == 'waive':
                    p = promotion_store.waive_promotion(conn, pid, data.get("reason"))
                    self.send_json(self._seal_promotion(conn, p, "promoted"))
                    return
                if action == 'abort':
                    p = promotion_store.abort_promotion(conn, pid)
                    self.send_json(self._seal_promotion(conn, p, "aborted"))
                    return
                if action == 'reseal':
                    p = promotion_store.get_promotion(conn, pid)
                    if p["state"] == "open":
                        self.send_json({"error": "promotion still open"}, status=409)
                        return
                    if p["sealed"]:
                        self.send_json(p)  # idempotent
                        return
                    outcome = "aborted" if p["state"] == "aborted" else "promoted"
                    self.send_json(self._seal_promotion(conn, p, outcome))
            except promotion_store.PromotionError as e:
                self._promotion_error(e)
        finally:
            conn.close()

    def handle_objection_resolve(self, pid, oid):
        data = self.read_json_body()
        if data is None:
            return
        conn = self.get_db()
        try:
            try:
                p = promotion_store.resolve_objection(
                    conn, pid, oid, data.get("resolution"), data.get("body"))
            except promotion_store.PromotionError as e:
                self._promotion_error(e)
                return
            if p["state"] == "aborted":  # upheld objection forced the abort — seal it
                p = self._seal_promotion(conn, p, "aborted")
            self.send_json(p)
        finally:
            conn.close()

    def handle_post_demote(self, prompt_id, version):
        data = self.read_json_body()
        if data is None:
            return
        reason = (data.get("reason") or "").strip()
        if not reason:
            self.send_json({"error": "reason required"}, status=422)
            return
        conn = self.get_db()
        try:
            row = conn.execute("SELECT status FROM prompts WHERE id=? AND version=?",
                               (prompt_id, version)).fetchone()
            if row is None:
                self.send_error(404, "Prompt not found")
                return
            slug_row = conn.execute(
                """SELECT thread_slug FROM promotions WHERE prompt_id=? AND version=?
                   AND thread_slug IS NOT NULL ORDER BY id DESC LIMIT 1""",
                (prompt_id, version)).fetchone()
            superseded = slug_row["thread_slug"] if slug_row else None
            conn.execute(
                """UPDATE prompts SET status='deprecated',
                   updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=? AND version=?""",
                (prompt_id, version))
            conn.commit()
            payload = promotion_seal.build_demotion_payload(
                prompt_id, version, reason,
                self._decided_by(conn, prompt_id, version), superseded_slug=superseded)
            try:
                result = seal.seal_decision(payload)
                self.send_json({"status": "deprecated", "sealed": True, **result})
            except (seal.SealError, seal.SealValidationError) as e:
                msg = getattr(e, "message", None) or str(e)
                self.send_json({"status": "deprecated", "sealed": False, "seal_error": msg})
        finally:
            conn.close()
```

Guards — replace the body of `handle_post_prompt_validate` and add the check at the top of `handle_put_prompt` (after the `version` check):

```python
    def handle_post_prompt_validate(self, prompt_id, version):
        # Phase 4: direct production flips are retired — promotion goes through the FCP flow.
        self.send_json(
            {"error": "direct validation retired",
             "use": f"POST /api/prompts/{prompt_id}/promote/{version}"},
            status=409)
```

```python
        # in handle_put_prompt, after the version-required check:
        if data.get('status') == 'production':
            conn = self.get_db()
            try:
                row = conn.execute("SELECT status FROM prompts WHERE id=? AND version=?",
                                   (prompt_id, version)).fetchone()
            finally:
                conn.close()
            if row is not None and row['status'] != 'production':
                self.send_json(
                    {"error": "status=production requires the promotion flow",
                     "use": f"POST /api/prompts/{prompt_id}/promote/{version}"},
                    status=409)
                return
```

- [ ] **Step 4: Run tests, confirm pass; run full suite**

Run: `python3 -m unittest tests.test_promotions_api -v` then `python3 -m unittest discover tests -v`
Expected: all pass. NOTE: `tests/test_server.py` may contain tests exercising the old `validate` behavior — if any fail, update those tests to expect the 409 contract (that behavior change is the spec, not a regression).

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_promotions_api.py tests/test_server.py
git commit -m "feat(threads-p4): promotion FCP routes + production-flip guards"
```

---

### Task 5: Registry widget UI — promote / object / countdown / deprecate

**Files:**
- Modify: `registry/interface/registry_widget.html` (all markup/JS/CSS inline, matching the file's existing single-file style)

**Interfaces:**
- Consumes: Task 4 routes. Row objects from `mapPrompt()` have `d.id`, `d.version`, `d.status`, `d.evalStatus`.
- Produces: no JS exports (iframe widget) — UI behavior only.

- [ ] **Step 1: Load promotions alongside the registry**

In `loadRegistry()` (line ~369), after the `/api/registry` fetch, add a second fetch and stash a lookup keyed by `id@version` of the newest promotion per prompt:

```js
let promotions = {};  // "id@version" -> newest promotion dict (module-level, near `let data`)

async function loadPromotions() {
  try {
    const res = await fetch("/api/promotions");
    const list = await res.json();
    promotions = {};
    for (const p of list) {
      const key = `${p.prompt_id}@${p.version}`;
      if (!(key in promotions)) promotions[key] = p; // list is newest-first
    }
  } catch (e) { promotions = {}; }
}
```

Call `await loadPromotions();` inside `loadRegistry()` before `render()`.

- [ ] **Step 2: Render promotion state + actions per row**

In `render()`'s actions cell (line ~438, beside the existing View body / Run / Eval history buttons), add:

```js
function promoCell(d) {
  const key = `${d.id}@${d.version}`;
  const p = promotions[key];
  if (p && p.state === "open") {
    const blocked = p.unresolved_objections > 0;
    const closesLabel = p.window_elapsed ? "window elapsed" : `closes ${esc(p.closes_at)}`;
    return `
      <span class="promo-badge">FCP open — ${closesLabel}${blocked ? ` · ${p.unresolved_objections} objection(s)` : ""}</span>
      <button onclick="event.stopPropagation(); objectTo(${p.id})">Object</button>
      ${blocked ? resolveButtons(p) : ""}
      <button onclick="event.stopPropagation(); promoAction(${p.id}, 'close')">Close</button>
      <button onclick="event.stopPropagation(); waive(${p.id})">Waive</button>
      <button onclick="event.stopPropagation(); promoAction(${p.id}, 'abort')">Abort</button>`;
  }
  if (p && !p.sealed && p.state !== "open") {
    return `<span class="promo-badge promo-warn">seal FAILED: ${esc(p.seal_error || "")}</span>
      <button onclick="event.stopPropagation(); promoAction(${p.id}, 'reseal')">Retry seal</button>`;
  }
  if (d.status === "production") {
    return `<button onclick="event.stopPropagation(); demote('${d.id}', '${d.version}')">Deprecate</button>`;
  }
  return `<button onclick="event.stopPropagation(); promote('${d.id}', '${d.version}')">Promote</button>`;
}

function resolveButtons(p) {
  return p.objections.filter(o => !o.resolution).map(o =>
    `<button onclick="event.stopPropagation(); resolveObjection(${p.id}, ${o.id})">Resolve #${o.id}</button>`
  ).join("");
}
```

Insert `${promoCell(d)}` into the actions markup in `render()` and add minimal CSS: `.promo-badge { font-size: 11px; opacity: .8; } .promo-warn { color: #c0392b; }`.

- [ ] **Step 3: Action functions (prompt()/confirm() based, matching the widget's existing alert() idiom)**

```js
async function api(path, body) {
  const res = await fetch(path, { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}) });
  const out = await res.json().catch(() => ({}));
  if (!res.ok) { alert(`Error ${res.status}: ${out.error || "request failed"}${out.use ? `\nUse: ${out.use}` : ""}`); return null; }
  return out;
}

async function promote(id, version) {
  const hours = prompt("FCP window hours (objections can be filed until it closes):", "24");
  if (hours === null) return;
  const out = await api(`/api/prompts/${id}/promote/${version}`, { window_hours: parseFloat(hours) || 24 });
  if (out) { await loadPromotions(); render(); }
}

async function objectTo(pid) {
  const body = prompt("Objection (will survive into the sealed record):");
  if (!body) return;
  if (await api(`/api/promotions/${pid}/object`, { body })) { await loadPromotions(); render(); }
}

async function resolveObjection(pid, oid) {
  const resolution = confirm("Uphold the objection? OK = uphold (aborts the promotion), Cancel = respond") ? "upheld" : "responded";
  const body = prompt(`Resolution text (${resolution}):`);
  if (!body) return;
  if (await api(`/api/promotions/${pid}/objections/${oid}/resolve`, { resolution, body })) { await loadRegistry(); }
}

async function waive(pid) {
  const reason = prompt("Waive reason (recorded as fcp_waived: true — disclosed, not hidden):");
  if (!reason) return;
  if (await api(`/api/promotions/${pid}/waive`, { reason })) { await loadRegistry(); }
}

async function promoAction(pid, action) {
  if (await api(`/api/promotions/${pid}/${action}`)) { await loadRegistry(); }
}

async function demote(id, version) {
  const reason = prompt("Deprecation reason (seals a superseding record):");
  if (!reason) return;
  if (await api(`/api/prompts/${id}/demote/${version}`, { reason })) { await loadRegistry(); }
}
```

(`loadRegistry()` re-fetches both registry and promotions, then renders — use it after any status-changing action.)

- [ ] **Step 4: Verify in a real browser (Phase 1–3 lesson: node/curl is not enough)**

Run: `python3 server.py` (port 8000), open `http://localhost:8000/registry/` in a browser. With ThreadHub NOT running: Promote a draft (24h window) → badge appears; Object → resolve(responded); Waive with reason → expect the row flips to production and the seal-FAILED badge with "Retry seal" appears (ThreadHub unreachable — this **proves** the fail-loudly path renders). No JS console errors. Then check `sqlite3 prompt_studio.db "SELECT id, state, sealed, seal_error FROM promotions"` shows the waived row with `sealed=0`.

- [ ] **Step 5: Commit**

```bash
git add registry/interface/registry_widget.html
git commit -m "feat(threads-p4): promotion FCP controls in registry widget"
```

---

### Task 6: Sandbox picker — production by default, drafts opt-in

**Files:**
- Modify: `sandbox/js/registry.js` (`listLoadablePrompts`, line ~51), `sandbox/index.html` (Setup drawer, near `#prompt-picker` line ~772), `sandbox/js/app.js` (picker population, line ~204)
- Test: `sandbox/js/registry.test.js` (extend)

**Interfaces:**
- Produces: `listLoadablePrompts(prompts, includeDrafts = false)` — pure, exported, filters to `status === "production"` unless `includeDrafts`.
- Consumes: prompt objects with `.file`, `.id`, `.version`, `.status`.

- [ ] **Step 1: Write failing tests** (append to `sandbox/js/registry.test.js`, same `node:test` style as the file's existing cases)

```js
test("listLoadablePrompts defaults to production only", () => {
  const prompts = [
    { id: "a", version: "1.0.0", file: "a.md", status: "production" },
    { id: "b", version: "1.0.0", file: "b.md", status: "draft" },
  ];
  const out = listLoadablePrompts(prompts);
  assert.deepEqual(out.map((p) => p.id), ["a"]);
});

test("listLoadablePrompts includes drafts when asked (nightly)", () => {
  const prompts = [
    { id: "a", version: "1.0.0", file: "a.md", status: "production" },
    { id: "b", version: "1.0.0", file: "b.md", status: "draft" },
  ];
  const out = listLoadablePrompts(prompts, true);
  assert.deepEqual(out.map((p) => p.id), ["a", "b"]);
});
```

- [ ] **Step 2: Run, confirm fail**

Run: `node --test sandbox/js/registry.test.js`
Expected: the two new cases FAIL (drafts currently included by default).

- [ ] **Step 3: Implement**

`sandbox/js/registry.js`:

```js
/** Prompts with archived .md files, newest version first per id.
 *  Production-only by default (Rust-channel model); includeDrafts = "nightly". */
export function listLoadablePrompts(prompts, includeDrafts = false) {
  const withFile = prompts.filter(
    (p) => p.file && (includeDrafts || p.status === "production"));
  return withFile.sort((a, b) => {
    const idCmp = a.id.localeCompare(b.id);
    if (idCmp !== 0) return idCmp;
    return b.version.localeCompare(a.version, undefined, { numeric: true });
  });
}
```

`sandbox/index.html` — directly under the `#prompt-picker` `<select>` (line ~772):

```html
    <label class="rail-drafts-toggle"><input type="checkbox" id="include-drafts"> include drafts (nightly)</label>
```

`sandbox/js/app.js` — where the picker is populated (line ~204, `listLoadablePrompts(index)` call site): keep the fetched index in a module-level `let promptIndex = []`, pass the checkbox state, and re-populate on toggle:

```js
const $includeDrafts = document.getElementById("include-drafts");
// at the call site:
promptIndex = index;
const prompts = listLoadablePrompts(promptIndex, $includeDrafts?.checked);
// listener, near the other picker listeners (~line 242):
$includeDrafts?.addEventListener("change", () => {
  populatePromptPicker(listLoadablePrompts(promptIndex, $includeDrafts.checked));
});
```

(Adapt to the exact local names at the call site — `populatePromptPicker` receives the filtered list.)

- [ ] **Step 4: Run all JS tests + browser sanity check**

Run: `node --test sandbox/js/`
Expected: all pass. Then `python3 server.py`, open `http://localhost:8000/`, Setup drawer → picker shows only production prompts; toggling "include drafts (nightly)" reveals drafts. No console errors.

- [ ] **Step 5: Commit**

```bash
git add sandbox/js/registry.js sandbox/js/registry.test.js sandbox/index.html sandbox/js/app.js
git commit -m "feat(threads-p4): picker defaults to production, drafts opt-in (nightly)"
```

---

### Task 7: Sidecar repoint + fail-loudly

**Files:**
- Modify: `sandbox/_run-threadhub.sh` (whole file — it is 5 lines)

**Interfaces:**
- Consumes: monorepo ThreadHub checkout at `~/Projects/clista/packages/threadhub` (canonical since the 2026-07-10 subtree merge).
- Produces: sidecar on :8110 as before.

- [ ] **Step 1: Replace the script**

```bash
#!/bin/bash
echo "[ThreadHub server — :8110]"
CANONICAL=~/Projects/clista/packages/threadhub
STALE=~/threadhub
if [ -d "$CANONICAL" ]; then
  cd "$CANONICAL"
elif [ -d "$STALE" ]; then
  echo "WARNING: canonical checkout $CANONICAL missing — falling back to STALE CHECKOUT $STALE"
  echo "         (ThreadHub moved to the lati-cooki/clista monorepo 2026-07-10; this copy will drift.)"
  cd "$STALE"
else
  echo "ERROR: no ThreadHub checkout found ($CANONICAL or $STALE). Seal/promotion flows will fail." >&2
  exit 1
fi
exec node bin/cli.js serve --port 8110
```

(Deliberate change: missing checkout now exits 1 loudly instead of the old silent `exit 0` skip — spec "Risks" section.)

- [ ] **Step 2: Verify the sidecar starts from the monorepo checkout**

Run: `bash sandbox/_run-threadhub.sh & sleep 2 && curl -sf http://localhost:8110/ && kill %1`
Expected: startup banner, no STALE warning, curl returns ThreadHub's root response. If `node bin/cli.js` fails in the monorepo checkout (deps not installed), run `npm install --omit=dev` in `~/Projects/clista/packages/threadhub` first and note it in the commit message.

- [ ] **Step 3: Commit**

```bash
git add sandbox/_run-threadhub.sh
git commit -m "fix(threads-p4): sidecar runs canonical monorepo ThreadHub, fails loudly"
```

---

### Task 8: End-to-end verification + docs

**Files:**
- Modify: `TODO.md` (mark Phase 4 shipped), `docs/superpowers/specs/2026-07-12-threads-phase4-promotion-decision-design.md` (status line only, `Approved by owner` → `Implemented`)

**Interfaces:**
- Consumes: everything above, live ThreadHub sidecar.

- [ ] **Step 1: Full-stack promotion round-trip**

With the sidecar running (Task 7 command) and `python3 server.py`:

```bash
# open with a zero-hour window so it can close immediately
curl -s -X POST localhost:8000/api/prompts/consensus_protocol/promote/1.1.0 \
  -H 'Content-Type: application/json' -d '{"window_hours": 0}'
# file + resolve an objection, then close (substitute the returned ids)
curl -s -X POST localhost:8000/api/promotions/<pid>/object -d '{"body": "e2e objection"}'
curl -s -X POST localhost:8000/api/promotions/<pid>/objections/<oid>/resolve \
  -d '{"resolution": "responded", "body": "e2e response"}'
curl -s -X POST localhost:8000/api/promotions/<pid>/close
```

Expected: close returns `sealed: 1` with a `thread_slug`. (Use whatever draft prompt exists in the DB — check with `sqlite3 prompt_studio.db "SELECT id, version, status FROM prompts"`; if none is draft, insert a throwaway one.)

- [ ] **Step 2: Verify the sealed thread through the proxy**

Run: `curl -s localhost:8000/api/threads/<thread_slug>/verify`
Expected: verification passes (chain valid). Also `curl -s localhost:8000/api/threads/<thread_slug>` shows the claim with `FCP: {...}` metadata, the pinned-eval (or disclosed-absence) evidence, and the surviving objection.

- [ ] **Step 3: Verify in the Threads tab UI**

Open `http://localhost:8000/`, Decisions view → the promotion thread is listed and renders via the Phase 1 read path. This closes the loop: promote in Registry → record in Decisions.

- [ ] **Step 4: Update docs + commit**

`TODO.md`: add/complete the line `Threads add-on Phase 4 — registry promotion recorded as ClisTa decision (FCP): SHIPPED`. Spec status line → `Implemented`.

```bash
git add TODO.md docs/superpowers/specs/2026-07-12-threads-phase4-promotion-decision-design.md
git commit -m "docs(threads-p4): mark Phase 4 shipped after e2e verification"
```

---

## Self-Review (performed at write time)

- **Spec coverage:** data model → Task 1; state machine → Task 1; all 9 routes + guards → Task 4 (demote included); evidence pinning + disclosed absence + honesty boundary → Tasks 2–3; sealing via Phase-2 machinery, seal-failure-keeps-flip, reseal → Tasks 3–4; widget UI → Task 5; picker default → Task 6; sidecar repoint + fail-loudly → Task 7; e2e + `verify` → Task 8. Spec's "plan-time decision" on eval integration resolved: attach-latest (no synchronous API call), documented in `promotion_evidence.py` docstring.
- **Type consistency:** `PromotionError(message, status)` used identically in store and handlers; promotion dict keys listed in Task 1 Interfaces match what Tasks 3–5 consume (`state`, `objections`, `unresolved_objections`, `window_elapsed`, `sealed`, `seal_error`, `thread_slug`); `seal.seal_decision` returns `{"slug", "citationHash"}` (verified against `seal.py:151`).
- **Placeholder scan:** clean — every code step contains runnable code; Task 4 Step 1 lists test names with behavior contracts and the MockHandler pattern to copy (pattern lives in `tests/test_server.py`, same repo).
