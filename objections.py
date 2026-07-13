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


# ---------------------------------------------------------------------------
# token validation — one exception, one generic 404, no oracle

class TokenInvalid(Exception):
    """Raised for EVERY token-check failure on /object/* paths. Routes map
    this to one byte-identical generic 404 — deliberately no detail: an
    outsider probing tokens must not learn whether one exists, is revoked,
    is exhausted, is expired, or belongs to a closed promotion."""


def validate_token(conn, raw):
    """Full validation for the page and filing paths. Returns
    (token_row_dict, promotion_dict) or raises TokenInvalid."""
    ensure_tokens_table(conn)
    row = conn.execute("SELECT * FROM fcp_tokens WHERE token_hash=?",
                       (hash_token(raw or ""),)).fetchone()
    if row is None:
        raise TokenInvalid()
    token = dict(row)
    if token["revoked"]:
        raise TokenInvalid()
    if token["uses"] >= token["use_limit"]:
        raise TokenInvalid()
    if _iso(_now()) >= token["expires_at"]:  # window-close snapshot
        raise TokenInvalid()
    try:
        promotion = promotion_store.get_promotion(conn, token["promotion_id"])
    except promotion_store.PromotionError:
        raise TokenInvalid()
    if promotion["state"] != promotion_store.OPEN:
        raise TokenInvalid()
    return token, promotion


# ---------------------------------------------------------------------------
# per-IP rate limit — /api/object/* only

RATE_LIMIT = 10          # requests
RATE_WINDOW = 60.0       # per this many seconds, per IP


def allow_request(ip, now=None):
    """Sliding-window in-memory counter (RATE_LIMIT per RATE_WINDOW per IP),
    applied by the server to /api/object/* ONLY. In-memory means it resets
    on restart — acceptable for the localhost deployment posture; a public
    deployment needs a real limiter (part of the pre-Sept-7 follow-up)."""
    now = time.time() if now is None else now
    bucket = _rate_buckets.setdefault(ip, [])
    cutoff = now - RATE_WINDOW
    bucket[:] = [t for t in bucket if t > cutoff]
    if len(bucket) >= RATE_LIMIT:
        return False
    bucket.append(now)
    return True


# ---------------------------------------------------------------------------
# objection filing

def _display_name_for(conn, token, label, contact_norm):
    """invitee_label (operator-chosen at mint) or label (objector-chosen) or
    objector-<n>. Any candidate CONTAINING the contact string is discarded:
    display_name reaches the hub, and the contact never does — that
    invariant is unconditional, not advisory."""
    for candidate in (token.get("invitee_label"), label):
        candidate = (candidate or "").strip()
        if candidate and contact_norm not in candidate.lower():
            return candidate
    n = conn.execute(
        "SELECT COUNT(*) FROM writers WHERE name LIKE 'objector:%'"
    ).fetchone()[0]
    return f"objector-{n + 1}"


def file_objection(conn, raw, body, contact, label=None):
    """POST /api/object/<token> — validate the token, provision the objector
    writer (BEFORE the objection exists, so the seal path can attribute it;
    the 5ab35b3 fail-closed guard is the backstop, not the plan), insert the
    objection (channel='token'), burn a use, and return the immediate
    receipt {objection_id, body_hash, status_url}.

    Privacy: the contact string is normalized (trim/lowercase) and lives in
    the local writer NAME only ("objector:<contact>"); the hub sees the
    display_name and the minted identity id, never the contact."""
    token, promotion = validate_token(conn, raw)
    body = (body or "").strip()
    if not body:
        raise promotion_store.PromotionError("objection body required", 422)
    contact_norm = (contact or "").strip().lower()
    if not contact_norm:
        raise promotion_store.PromotionError(
            "contact required (kept local — never sent to the hub)", 422)
    writer_name = f"objector:{contact_norm}"
    display_name = _display_name_for(conn, token, label, contact_norm)
    # Mint-first (idempotent): may raise WriterError/SealError — nothing has
    # been written locally yet, so a hub failure files nothing.
    writers.ensure_writer(conn, writer_name, display_name=display_name,
                          kind="human")
    cur = conn.execute(
        """INSERT INTO promotion_objections
           (promotion_id, raised_at, body, author_writer, channel, token_id)
           VALUES (?,?,?,?,?,?)""",
        (promotion["id"], _iso(_now()), body, writer_name, "token",
         token["id"]))
    conn.execute("UPDATE fcp_tokens SET uses = uses + 1 WHERE id=?",
                 (token["id"],))
    conn.commit()
    oid = cur.lastrowid
    return {
        "objection_id": oid,
        "body_hash": "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "status_url": f"/object/{raw}/status/{oid}",
    }


# ---------------------------------------------------------------------------
# status / receipt — phase two of the two-phase receipt

def _validate_token_for_status(conn, raw, oid):
    """Weaker validation for the receipt route: the token must exist, be
    unrevoked, and OWN the objection — but exhaustion and window close do
    NOT block it. The receipt must outlive the window that produced it
    (post-seal is exactly when it matters). Failures are still the one
    generic TokenInvalid."""
    ensure_tokens_table(conn)
    row = conn.execute("SELECT * FROM fcp_tokens WHERE token_hash=?",
                       (hash_token(raw or ""),)).fetchone()
    if row is None:
        raise TokenInvalid()
    token = dict(row)
    if token["revoked"]:
        raise TokenInvalid()
    try:
        oid = int(oid)
    except (TypeError, ValueError):
        raise TokenInvalid()
    obj = conn.execute("SELECT * FROM promotion_objections WHERE id=?",
                       (oid,)).fetchone()
    if obj is None:
        raise TokenInvalid()
    obj = dict(obj)
    if obj.get("token_id") is None or int(obj["token_id"]) != token["id"]:
        raise TokenInvalid()  # a token reads only its own objections
    return token, obj


def _receipt_instructions(hub, slug, citation_hash, record_hash):
    return (
        "Verify this objection yourself, from any machine with Node:\n"
        f"  1. Save the checker:  curl -o verify.mjs {hub}/verify.mjs\n"
        f"  2. Save the thread:   curl -o thread.json {hub}/t/{slug}.json\n"
        "  3. Run the checker:   node verify.mjs thread.json\n"
        "It prints 'PASS: <n> records, head <hash>, signatures verified "
        "k/n'. Compare that head to this receipt's citation_hash "
        f"({citation_hash}) — they must match, and your objection is the "
        f"record {record_hash} inside that chain ({hub}/r/{record_hash}). "
        "A PASS proves chain integrity — your objection was recorded, "
        "unaltered, in sequence, with how many records were signed "
        "disclosed (signatures verified k/n). It proves recording, NOT "
        "truth. Run it on your own machine against a saved copy: a verdict "
        "produced by the hub's own host is not independent.")


def objection_status(conn, raw, oid):
    """GET /object/<token>/status/<oid> — pre-seal: {status: 'filed'};
    post-seal: the full receipt (record_hash + thread_slug + citation_hash
    + record_url + verify_url + checker_url + DR 5.6 custody disclosure +
    runnable checker instructions). This is the conversion moment: the
    receipt lets the objector verify their own objection with no account
    and no trust in this server."""
    token, obj = _validate_token_for_status(conn, raw, oid)
    try:
        promotion = promotion_store.get_promotion(conn, obj["promotion_id"])
    except promotion_store.PromotionError:
        raise TokenInvalid()
    base = {
        "objection_id": obj["id"],
        "body_hash": "sha256:"
                     + hashlib.sha256(obj["body"].encode("utf-8")).hexdigest(),
        "promotion_state": promotion["state"],
    }
    record_hash = obj.get("sealed_record_hash")
    if record_hash and promotion.get("thread_slug"):
        hub = f"http://localhost:{seal.THREADHUB_PORT}"
        slug = promotion["thread_slug"]
        citation = promotion.get("citation_hash")
        writer = (writers.get_writer(conn, obj["author_writer"])
                  if obj.get("author_writer") else None)
        custody = (_custody_disclosure_for(writer) if writer
                   else CUSTODY_DISCLOSURE_MINT)
        return {
            **base,
            "status": "sealed",
            "record_hash": record_hash,
            "thread_slug": slug,
            "citation_hash": citation,
            "record_url": f"{hub}/r/{record_hash}",
            "verify_url": f"{hub}/t/{slug}/verify",
            "checker_url": f"{hub}/verify.mjs",
            "custody": custody,
            "instructions": _receipt_instructions(hub, slug, citation,
                                                  record_hash),
        }
    return {**base, "status": "filed", "sealed": bool(promotion.get("sealed"))}


# ---------------------------------------------------------------------------
# seal back-fill — sealed_record_hash from the extended seal return

class BackfillMismatch(Exception):
    """Stored objections and ObjectionRaised records disagree in count.
    The seal path records this as seal_error; NOTHING is back-filled."""


def backfill_sealed_records(conn, promotion, records, slug=None):
    """Match the promotion's objections (ordered by id — the SAME ordering
    _author_for_event uses for the n-th ObjectionRaised writer mapping, same
    source of truth: promotion['objections']) to the ObjectionRaised records
    of write_to_threadhub's extended return, in order, and write each
    sealed_record_hash.

    The count assertion runs BEFORE any UPDATE: on mismatch nothing is
    back-filled and BackfillMismatch propagates — _seal_promotion records it
    as seal_error. The hub thread exists regardless (the seal already
    happened); the error message says so instead of pretending otherwise."""
    objs = promotion.get("objections") or []
    obj_records = [r for r in (records or [])
                   if r.get("event_type") == "ObjectionRaised"]
    if len(obj_records) != len(objs):
        raise BackfillMismatch(
            f"objection back-fill count mismatch: {len(objs)} stored "
            f"objection(s) vs {len(obj_records)} ObjectionRaised record(s) "
            f"in thread '{slug}' — refusing partial back-fill (the hub "
            "thread exists; recorded as seal_error for reseal)")
    for o, r in zip(objs, obj_records):
        conn.execute(
            "UPDATE promotion_objections SET sealed_record_hash=? WHERE id=?",
            (r.get("record_hash"), o["id"]))
    conn.commit()


# ---------------------------------------------------------------------------
# standalone page — server-rendered string template, no studio shell

def _e(v):
    return html.escape(str(v), quote=True)


def _js(v):
    # JSON-encode for inline <script> embedding; make it </script>-proof.
    return json.dumps(v).replace("<", "\\u003c").replace(">", "\\u003e")


def render_object_page(promotion, token, raw):
    """The outside skeptic's page: prompt id/version, window countdown,
    pinned-evidence hash or its disclosed absence, textarea + contact.
    EVERYTHING user-derived is escaped (_e for HTML, _js for the inline
    script). No studio shell, no JS dependencies beyond the countdown and
    the fetch that files the objection."""
    ev = promotion.get("evidence")
    if isinstance(ev, dict):
        evidence_html = (
            "<p>Pinned evidence content_hash: "
            f"<code>{_e(ev.get('content_hash', 'unknown'))}</code> "
            f"(source: <code>{_e(ev.get('source_file', 'unknown'))}</code>)</p>")
    else:
        evidence_html = (
            "<p>No pinned eval evidence is attached to this promotion — it "
            "proceeded with that absence disclosed.</p>")
    greeting = ""
    if token.get("invitee_label"):
        greeting = f"<p>Invitation for: <b>{_e(token['invitee_label'])}</b></p>"
    pid_v = f"{_e(promotion['prompt_id'])} {_e(promotion['version'])}"
    closes = _e(promotion["closes_at"])
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Objection — {pid_v}</title>
<style>
body{{font:16px/1.5 system-ui,sans-serif;max-width:42rem;margin:2rem auto;padding:0 1rem;color:#222}}
textarea,input{{width:100%;box-sizing:border-box;font:inherit;padding:.4rem;margin:.2rem 0 .8rem}}
textarea{{min-height:8rem}}
button{{font:inherit;padding:.5rem 1.2rem}}
code{{background:#f4f4f4;padding:0 .2rem}}
#receipt{{white-space:pre-wrap;background:#f4f4f4;padding:1rem;display:none}}
small{{color:#555}}
</style></head><body>
<h1>File an objection</h1>
<p>Promotion under final comment: <b>{pid_v}</b></p>
{greeting}
<p>Window closes at <code>{closes}</code> — <span id="countdown">…</span></p>
{evidence_html}
<form id="f">
<label>Your objection<br><textarea name="body" required></textarea></label>
<label>Contact (stays with the studio operator; never published to the hub)<br>
<input name="contact" required></label>
<label>Display name (optional — how the public record names you)<br>
<input name="label"></label>
<button type="submit">File objection</button>
</form>
<p id="receipt"></p>
<small>Filing records your objection under a custodial hub identity; your
receipt will disclose custody and show you how to verify the sealed record
yourself.</small>
<script>
var closesAt = new Date({_js(promotion["closes_at"])});
function tick() {{
  var ms = closesAt - Date.now();
  document.getElementById("countdown").textContent =
    ms <= 0 ? "window elapsed" :
    Math.floor(ms/3600000) + "h " + Math.floor(ms/60000)%60 + "m " +
    Math.floor(ms/1000)%60 + "s remaining";
}}
tick(); setInterval(tick, 1000);
document.getElementById("f").addEventListener("submit", function (ev) {{
  ev.preventDefault();
  var f = ev.target;
  fetch("/api/object/" + {_js(raw)}, {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{body: f.body.value, contact: f.contact.value,
                          label: f.label.value || undefined}})
  }}).then(function (r) {{ return r.json(); }}).then(function (j) {{
    var el = document.getElementById("receipt");
    el.style.display = "block";
    el.textContent = j.error ? ("Error: " + j.error)
      : ("Objection filed.\\nobjection_id: " + j.objection_id
         + "\\nbody_hash: " + j.body_hash
         + "\\nreceipt/status: " + j.status_url
         + "\\nKeep this URL — after the window seals it becomes your "
         + "verifiable receipt.");
  }});
}});
</script>
</body></html>"""
