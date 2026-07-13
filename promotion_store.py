"""Promotion FCP state machine over SQLite. No HTTP, no sealing — pure storage + rules.

States: open -> closed | waived | aborted. Window elapse is evaluated lazily on read;
there is no scheduler. An unresolved objection blocks close even past the window; an
upheld objection forces abort. Seal outcome is bookkeeping only (sealed/seal_error) —
a failed seal never un-flips prompts.status.
"""
import json
from datetime import datetime, timedelta, timezone

OPEN, CLOSED, WAIVED, ABORTED = "open", "closed", "waived", "aborted"
# Terminal FCP outcomes — every state a promotion can end in. OPEN is the
# only non-terminal state; there is no other. Sealed immutable by
# DR-2026-07-12-fcp-metrics: changing this tuple's meaning requires a NEW
# metric name by DR amendment, never a redefinition.
TERMINAL_STATES = (CLOSED, WAIVED, ABORTED)
# Disclosure strings for externally_contested_ratio (DR-2026-07-12-fcp-metrics):
# before Slice 6 the fcp_tokens table does not exist, so the contested count
# is an absence of measurement, not a measured zero — say so.
CONTESTED_DATA_ABSENT = "no token table yet (pre-Slice-6); 0 invitations recorded"
CONTESTED_DATA_MEASURED = "fcp_tokens table present; invitations measured"
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


def _has_fcp_tokens_table(conn):
    # Same guarded pragma-table_info pattern as server.migrate_actor_columns:
    # a table with no columns is a table that does not exist.
    return bool({r[1] for r in conn.execute("PRAGMA table_info(fcp_tokens)")})


def metrics(conn, window_days=None):
    """Waive-ratio metrics per DR-2026-07-12-fcp-metrics. Definitions are
    sealed immutable in that DR — the formulas below must match it verbatim:

    - fcp_waive_ratio(window_days) = count(terminal outcomes in window where
      state == 'waived') / count(terminal outcomes in window)
    - externally_contested_ratio(window_days) = count(terminal outcomes in
      window whose FCP window had >= 1 token invitation) / count(terminal
      outcomes in window)
    - terminal outcomes: promotions.state in TERMINAL_STATES
      ('closed', 'waived', 'aborted'); resolved_at is the outcome timestamp
    - window: resolved_at >= now - window_days; window_days None = all-time
    - denominator 0 -> both ratios None (JSON null) with counts, never a
      fabricated 0.0

    Slice 6 query contract (pinned by tests/test_promotion_metrics.py before
    the table exists): fcp_tokens carries one row per token invitation with
    at least promotion_id (INTEGER, references promotions.id) and minted_at
    (TEXT, UTC %Y-%m-%dT%H:%M:%SZ). A terminal outcome counts as externally
    contested when >= 1 fcp_tokens row has promotion_id = promotions.id AND
    minted_at < resolved_at (invitation minted strictly before the outcome).
    Until the table exists, invited = 0 and contested_data discloses the
    absence of measurement instead of pretending a measured zero.
    """
    where = f"p.state IN ({','.join('?' * len(TERMINAL_STATES))})"
    params = list(TERMINAL_STATES)
    if window_days is not None:
        where += " AND p.resolved_at >= ?"
        params.append(_iso(_now() - timedelta(days=float(window_days))))
    total = conn.execute(
        f"SELECT COUNT(*) FROM promotions p WHERE {where}", params).fetchone()[0]
    waived = conn.execute(
        f"SELECT COUNT(*) FROM promotions p WHERE {where} AND p.state=?",
        params + [WAIVED]).fetchone()[0]
    if _has_fcp_tokens_table(conn):
        invited = conn.execute(
            f"""SELECT COUNT(*) FROM promotions p WHERE {where}
                AND EXISTS (SELECT 1 FROM fcp_tokens t
                            WHERE t.promotion_id = p.id
                              AND t.minted_at < p.resolved_at)""",
            params).fetchone()[0]
        contested_data = CONTESTED_DATA_MEASURED
    else:
        invited = 0
        contested_data = CONTESTED_DATA_ABSENT
    return {
        "window_days": window_days,
        "terminal_total": total,
        "waived": waived,
        "fcp_waive_ratio": (waived / total) if total else None,
        "invited": invited,
        "externally_contested_ratio": (invited / total) if total else None,
        "contested_data": contested_data,
        "computed_at": _iso(_now()),
    }


def open_promotion(conn, prompt_id, version, window_hours=24.0, evidence=None,
                   actor="operator"):
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
           (prompt_id, version, state, opened_at, window_hours, closes_at,
            evidence_json, opened_by)
           VALUES (?,?,?,?,?,?,?,?)""",
        (prompt_id, version, OPEN, _iso(opened), float(window_hours), _iso(closes),
         json.dumps(evidence) if evidence is not None else None, actor))
    conn.commit()
    return get_promotion(conn, cur.lastrowid)


def _require_open(conn, pid):
    p = get_promotion(conn, pid)
    if p["state"] != OPEN:
        raise PromotionError(f"promotion is {p['state']}, not open", 409)
    return p


def add_objection(conn, pid, body, actor="operator"):
    _require_open(conn, pid)
    body = (body or "").strip()
    if not body:
        raise PromotionError("objection body required", 422)
    cur = conn.execute(
        """INSERT INTO promotion_objections (promotion_id, raised_at, body, author_writer)
           VALUES (?,?,?,?)""",
        (pid, _iso(_now()), body, actor))
    conn.commit()
    return dict(conn.execute("SELECT * FROM promotion_objections WHERE id=?",
                             (cur.lastrowid,)).fetchone())


def resolve_objection(conn, pid, oid, resolution, body, actor="operator"):
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
        """UPDATE promotion_objections SET resolution=?, resolution_body=?, resolved_by=?
           WHERE id=?""",
        (resolution, body, actor, oid))
    conn.commit()
    if resolution == "upheld":
        # upheld objection forces abort; the resolver is the terminating actor
        return _terminate(conn, pid, ABORTED, actor=actor)
    return get_promotion(conn, pid)


def _flip_to_production(conn, prompt_id, version, validated):
    """Flip to production; stamp eval_status='validated' only when the
    promotion carried pinned evidence — an evidence-absent (disclosed)
    promotion must not overstate its eval state in the DB."""
    if validated:
        conn.execute(
            """UPDATE prompts SET status='production', eval_status='validated',
               updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=? AND version=?""",
            (prompt_id, version))
    else:
        conn.execute(
            """UPDATE prompts SET status='production',
               updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=? AND version=?""",
            (prompt_id, version))


def _terminate(conn, pid, state, waive_reason=None, flip=False, actor="operator"):
    p = _require_open(conn, pid)
    if flip:
        _flip_to_production(conn, p["prompt_id"], p["version"],
                            validated=p["evidence"] is not None)
    conn.execute(
        """UPDATE promotions SET state=?, resolved_at=?, waive_reason=?, resolved_by=?
           WHERE id=?""",
        (state, _iso(_now()), waive_reason, actor, pid))
    conn.commit()
    return get_promotion(conn, pid)


def close_promotion(conn, pid, actor="operator"):
    p = _require_open(conn, pid)
    if not p["window_elapsed"]:
        raise PromotionError(
            f"window open until {p['closes_at']} — close later or waive", 409)
    if p["unresolved_objections"]:
        raise PromotionError(
            f"{p['unresolved_objections']} unresolved objection(s) block close", 409)
    return _terminate(conn, pid, CLOSED, flip=True, actor=actor)


def waive_promotion(conn, pid, reason, actor="operator"):
    reason = (reason or "").strip()
    if not reason:
        raise PromotionError("waive reason required", 422)
    return _terminate(conn, pid, WAIVED, waive_reason=reason, flip=True, actor=actor)


def abort_promotion(conn, pid, actor="operator"):
    return _terminate(conn, pid, ABORTED, actor=actor)


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
