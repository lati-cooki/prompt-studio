"""Tokenized objection path — Slice 6 of Phase 5 (DR-phase5-topology).

An outside skeptic gets a link (/object/<token>), files an objection without
an account, and walks away with a receipt whose instructions let them verify
their own objection against the hub with a checker they can run anywhere
(GET <hub>/verify.mjs).

HONEST POSTURE NOTE (owner decision, locked): the token mint/revoke routes
are "operator-only" as DEPLOYMENT POSTURE — this server binds localhost and
only the operator can reach it. That is NOT enforced auth: there is no
credential check on these routes. Anyone who can reach the server can mint.
Public hosting is a named pre-Sept-7 follow-up; do not expose this server
until that lands.

Token rules:
- raw token: >= 32 bytes urlsafe from `secrets`, shown exactly ONCE in the
  mint response; only sha256(raw) is stored (fcp_tokens.token_hash).
- expires_at is the promotion's closes_at at mint time (window snapshot).
- validation on /object/* paths checks: hash exists, not revoked,
  uses < use_limit, window still open, promotion still in an open FCP state.
  EVERY failure raises the same TokenInvalid and every route answers with
  one byte-identical generic 404 — no oracle for which check failed.

Privacy: the objector's contact string stays in the studio DB. It reaches
the hub in NO payload — the writer name "objector:<contact>" is local-only
(only threadhub ids and display_name travel), and any candidate display
name containing the contact is discarded unconditionally.

Metrics contract (DR-2026-07-12-fcp-metrics rule 3, sealed): fcp_tokens
carries one row per token invitation with promotion_id (INTEGER, references
promotions.id) and minted_at (TEXT, UTC %Y-%m-%dT%H:%M:%SZ). The Phase 5
plan sketched this column as "created_at"; the sealed DR contract names it
minted_at, and promotion_store.metrics queries it by that name — the DR
wins. minted_at IS the creation timestamp; there is no second one.

Objection resolutions: when a promotion with token objections seals, the
resolution still rides the Phase 4 inline form ("[resolution: ...]"
appended to the ObjectionRaised text — the mapping table's disclosed form).
Emitting ObjectionResolved as a first-class event requires the ClisTa CLI
to support `objection resolve`, which it does not yet; that is a filed
follow-up, not this slice. Do NOT hand-roll validator-bypassing events.
"""
import hashlib
import html
import json
import secrets
import time
from datetime import datetime, timezone

import promotion_store
import seal
import writers

_TS = "%Y-%m-%dT%H:%M:%SZ"

# ---------------------------------------------------------------------------
# generic 404 — one body per surface, byte-identical for every failure mode

GENERIC_404_JSON = {"error": "not found"}
GENERIC_404_HTML = (
    "<!doctype html><meta charset='utf-8'><title>Not found</title>"
    "<p>Not found.</p>")

# ---------------------------------------------------------------------------
# DR 5.6 custody disclosure — travels ON the receipt (and the mint response,
# so the operator can forward it with the link), visible without querying
# the hub. Mint-time text is prospective (no objector identity exists yet);
# receipt-time text names the actual custodial identity.

POSTURE_NOTE = (
    '"operator-only" is deployment posture (this server is expected to bind '
    "localhost), not enforced auth — there is no credential check on this "
    "route. Do not expose this server publicly; public hosting is a named "
    "pre-Sept-7 follow-up.")

CUSTODY_DISCLOSURE_MINT = (
    "Custody disclosure (DR-phase5-topology 5.6): objections filed through "
    "this link are recorded under a CUSTODIAL identity minted for the "
    "objector — the hub operator holds the signing keys, not the objector "
    "(DR 5.5). Independence is therefore DOWNGRADED (DR 5.3): the sealed "
    "record proves the studio recorded the objection and when — not that a "
    "key only the objector controls signed it. Upgrade path: a "
    "self-custodial identity (objector-held keys) is available on request "
    "to the operator and replaces the custodial one for future objections.")


def _custody_disclosure_for(writer):
    """Receipt-time DR 5.6 disclosure naming the actual custodial identity.
    Uses display_name + threadhub id only — never the internal
    objector:<contact> writer name (the contact stays local)."""
    return (
        "Custody disclosure (DR-phase5-topology 5.6): this objection is "
        f"recorded under the CUSTODIAL identity '{writer['display_name']}' "
        f"(hub identity {writer['threadhub_id']}) — the hub operator holds "
        "the signing keys, not you (DR 5.5). Independence is therefore "
        "DOWNGRADED (DR 5.3): the record proves the studio recorded your "
        "objection and when — not that a key only you control signed it. "
        "Upgrade path: a self-custodial identity (keys you hold) is "
        "available on request to the operator and replaces this custodial "
        "one for future objections.")


# ---------------------------------------------------------------------------
# per-IP rate limit state (Slice 6 files it on /api/object/* only) —
# in-memory by design: resets on restart, which is fine for the localhost
# deployment posture. See allow_request below.
_rate_buckets = {}

# ---------------------------------------------------------------------------
# storage

def ensure_tokens_table(conn):
    """Create fcp_tokens if absent (guarded, idempotent). Deliberately NOT in
    schema.sql: the metrics endpoint discloses table ABSENCE as absence of
    measurement (DR-2026-07-12-fcp-metrics rule 6), and that behaviour is
    pinned by tests that seed schema.sql without this table. Creation is
    owned here and runs at server boot (init_db) and on the token paths."""
    conn.execute("""CREATE TABLE IF NOT EXISTS fcp_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        promotion_id INTEGER NOT NULL REFERENCES promotions(id),
        token_hash TEXT NOT NULL UNIQUE,
        invitee_label TEXT,
        minted_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        use_limit INTEGER NOT NULL DEFAULT 1,
        uses INTEGER NOT NULL DEFAULT 0,
        revoked INTEGER NOT NULL DEFAULT 0,
        created_by TEXT
    )""")
    conn.commit()


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.strftime(_TS)


def hash_token(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# mint / revoke (operator surface)

def mint_token(conn, pid, invitee_label=None, use_limit=1,
               created_by="operator"):
    """Mint a promotion-scoped objection token. Returns the mint response
    dict — the ONLY place the raw token ever appears; the DB keeps the hash.

    HARD PRECONDITION (Slice 2 review): refuses 409 when the operator writer
    is not provisioned. Without it, the empty-table legacy fallback in the
    seal path would attribute a NAMED objector to the shared studio author —
    the exact misattribution DR 5.2 forbids. Provisioning objector writers
    at filing time (file_objection) is the plan; the 5ab35b3 fail-closed
    seal guard is the backstop, and this refusal keeps both reachable."""
    ensure_tokens_table(conn)
    writers.ensure_table(conn)
    p = promotion_store.get_promotion(conn, pid)
    if writers.get_writer(conn, "operator") is None:
        raise promotion_store.PromotionError(
            "operator writer is not provisioned — tokenized objections would "
            "seal under the shared studio author (DR 5.2 misattribution). "
            "Provision it first: writers.ensure_writer(conn, 'operator')",
            409)
    if p["state"] != promotion_store.OPEN:
        raise promotion_store.PromotionError(
            f"promotion is {p['state']}, not open — tokens are minted only "
            "for an open FCP window", 409)
    if p["window_elapsed"]:
        raise promotion_store.PromotionError(
            "FCP window already elapsed — a token minted now would expire at "
            "birth (expires_at is the closes_at snapshot)", 409)
    if isinstance(use_limit, bool) or not isinstance(use_limit, int) \
            or use_limit < 1:
        raise promotion_store.PromotionError(
            "use_limit must be an integer >= 1", 422)
    invitee_label = (invitee_label or "").strip() or None
    raw = secrets.token_urlsafe(32)
    cur = conn.execute(
        """INSERT INTO fcp_tokens
           (promotion_id, token_hash, invitee_label, minted_at, expires_at,
            use_limit, created_by)
           VALUES (?,?,?,?,?,?,?)""",
        (p["id"], hash_token(raw), invitee_label, _iso(_now()),
         p["closes_at"], use_limit, created_by))
    conn.commit()
    return {
        "token": raw,  # shown once; never stored, never logged
        "token_id": cur.lastrowid,
        "promotion_id": p["id"],
        "url_path": f"/object/{raw}",
        "expires_at": p["closes_at"],
        "use_limit": use_limit,
        "invitee_label": invitee_label,
        "custody": CUSTODY_DISCLOSURE_MINT,
        "posture": POSTURE_NOTE,
    }


def revoke_token(conn, pid, token_id):
    ensure_tokens_table(conn)
    row = conn.execute(
        "SELECT id FROM fcp_tokens WHERE id=? AND promotion_id=?",
        (token_id, pid)).fetchone()
    if row is None:
        raise promotion_store.PromotionError("token not found", 404)
    conn.execute("UPDATE fcp_tokens SET revoked=1 WHERE id=?", (token_id,))
    conn.commit()
    return {"revoked": True, "token_id": token_id, "promotion_id": int(pid)}
