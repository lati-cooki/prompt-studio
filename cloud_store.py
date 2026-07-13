"""Cloud client for the studio operator plane (Task 19).

A drop-in replacement for the operator-facing functions of promotion_store.py
and objections.py that speaks HTTP to the studio Worker's bearer-gated
operator API (workers/studio) instead of touching a local SQLite DB. server.py
selects this module in place of promotion_store/objections for the operator
FCP/promotion/token/objection state when STUDIO_CLOUD_BASE_URL is configured;
everything else (sealing, challenge runs, evals, git anchoring, the local
skeptic surface) STAYS local.

Design invariants:
- Every function mirrors its promotion_store / objections counterpart's
  SIGNATURE, INCLUDING a leading `conn` argument that is ACCEPTED AND IGNORED
  — the call sites in server.py do not restructure. `conn` is the laptop DB
  handle; the cloud store never reads it (the FCP/token/objection state lives
  in the Worker's Durable Object now).
- Non-2xx responses (bodies `{"error": msg}` or `{"error": msg, "code": ...}`)
  are raised as promotion_store.PromotionError(msg, status) — the SAME class
  the handlers already catch, so no handler restructuring is needed. A network
  failure raises PromotionError with a clear message and status 502 (a hub/
  gateway-shaped status the handlers already know how to render).
- Return shapes equal what the local functions return so the handlers and
  _seal_promotion consume them unchanged. The Worker's GET /api/promotions/:pid
  returns promotion_store.get_promotion's exact dict shape PLUS, on each
  objection row, author_threadhub_id + author_display_name (additive — the
  objector writers were minted on the Worker, so the laptop seal path reads
  their hub ids from here). server.py._writers_for_promotion prefers those.

stdlib only (urllib.request, json) — no new dependencies.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

import promotion_store

# Config is read at CALL time (not import time) so tests can set the env vars
# per-case and so an operator can point the laptop at the cloud without a
# restart-order dependency. STUDIO_CLOUD_BASE_URL unset is a misconfiguration
# here (server.py only routes to this module when it IS set), surfaced loudly.

# mint_token's deliberation_slug sentinel: absent (leave the association
# alone) is distinct from an explicit null (clear it). Mirrors
# objections._UNSET so server.py's mint_kwargs pass-through works unchanged.
_UNSET = object()

# Cloudflare's edge returns 403 to requests with the Python-urllib default
# User-Agent, so every operator->Worker call must send a custom UA. Duplicated
# from seal.USER_AGENT (not imported) to keep this module stdlib-only.
USER_AGENT = "clista-operator/1.0"


def _base():
    return (os.environ.get("STUDIO_CLOUD_BASE_URL") or "").rstrip("/")


def _token():
    return os.environ.get("STUDIO_CLOUD_TOKEN") or ""


def _timeout():
    return float(os.environ.get("STUDIO_CLOUD_TIMEOUT", "15"))


def _error_message(raw):
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw.strip() or "studio cloud API error"
    if isinstance(parsed, dict) and parsed.get("error"):
        return parsed["error"]
    return raw.strip() or "studio cloud API error"


def _request(method, path, body=None):
    """One HTTP round-trip to the operator API. Returns the parsed JSON body
    (or None for an empty 2xx). Raises promotion_store.PromotionError on any
    non-2xx (parsing {"error": msg}) or transport failure (status 502)."""
    base = _base()
    if not base:
        # server.py never routes here without the base set; if it happens,
        # fail loud rather than hit a bare/relative URL.
        raise promotion_store.PromotionError(
            "STUDIO_CLOUD_BASE_URL is not configured", 500)
    url = base + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {}
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/json"
    headers["User-Agent"] = USER_AGENT
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_timeout()) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise promotion_store.PromotionError(_error_message(detail), e.code)
    except urllib.error.URLError as e:
        raise promotion_store.PromotionError(
            f"studio cloud API unreachable at {base}: {e.reason}", 502)
    if raw == "":
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        raise promotion_store.PromotionError(
            f"studio cloud API returned non-JSON from {method} {path}", 502)


def _pid_path(pid, *suffix):
    seg = urllib.parse.quote(str(pid), safe="")
    return "/api/promotions/" + seg + "".join(suffix)


# ---------------------------------------------------------------------------
# promotion_store mirror


def get_promotion(conn, pid):
    return _request("GET", _pid_path(pid))


def list_promotions(conn):
    return _request("GET", "/api/promotions")


def open_promotion(conn, prompt_id, version, window_hours=24.0, evidence=None,
                   actor="operator", deliberation_slug=None):
    return _request("POST", "/api/promotions", {
        "prompt_id": prompt_id,
        "version": version,
        "window_hours": window_hours,
        "evidence": evidence,
        "deliberation_slug": deliberation_slug,
        "opened_by": actor,
    })


def add_objection(conn, pid, body, actor="operator"):
    # Operator-channel objection. The Worker authors it as 'operator' (the
    # objector-writer join leaves author_threadhub_id null; the laptop seal
    # path falls back to the local operator writer for these).
    return _request("POST", _pid_path(pid, "/objections"), {"body": body})


def resolve_objection(conn, pid, oid, resolution, body, actor="operator"):
    return _request(
        "POST",
        _pid_path(pid, "/objections/", urllib.parse.quote(str(oid), safe=""),
                  "/resolve"),
        {"resolution": resolution, "body": body})


def close_promotion(conn, pid, actor="operator"):
    return _request("POST", _pid_path(pid, "/close"))


def waive_promotion(conn, pid, reason, actor="operator"):
    return _request("POST", _pid_path(pid, "/waive"), {"reason": reason})


def abort_promotion(conn, pid, actor="operator"):
    return _request("POST", _pid_path(pid, "/abort"))


def mark_seal_result(conn, pid, slug=None, citation_hash=None, error=None):
    if error is None:
        body = {"slug": slug, "citation_hash": citation_hash}
    else:
        body = {"error": str(error)}
    return _request("POST", _pid_path(pid, "/seal-result"), body)


def metrics(conn, window_days=None):
    path = "/api/promotions/metrics"
    if window_days is not None:
        path += "?" + urllib.parse.urlencode({"window": window_days})
    return _request("GET", path)


# ---------------------------------------------------------------------------
# objections operator-surface mirror


def mint_token(conn, pid, invitee_label=None, use_limit=1,
               created_by="operator", deliberation_slug=_UNSET):
    body = {"invitee_label": invitee_label, "use_limit": use_limit}
    if deliberation_slug is not _UNSET:
        # Key presence carries the UNSET-vs-explicit-null distinction, exactly
        # as the Worker's mintToken reads it (`'deliberation_slug' in data`).
        body["deliberation_slug"] = deliberation_slug
    # The Worker's mint response already carries an absolute `url` (built from
    # its own PUBLIC_BASE_URL) and, when applicable, `deliberation_url` — the
    # handler passes it through as-is in cloud mode (no url_path assembly).
    return _request("POST", _pid_path(pid, "/tokens"), body)


def revoke_token(conn, pid, token_id):
    return _request(
        "POST",
        _pid_path(pid, "/tokens/", urllib.parse.quote(str(token_id), safe=""),
                  "/revoke"))


def backfill_sealed_records(conn, promotion, records, slug=None):
    # Mirrors objections.backfill_sealed_records: the Worker asserts the
    # objection/ObjectionRaised count BEFORE any write and answers 409 on a
    # mismatch (zero writes) — raised here as PromotionError, which
    # _seal_promotion's broad except records as seal_error just like the local
    # BackfillMismatch. The promotion id names the DO row to back-fill.
    return _request("POST", _pid_path(promotion["id"], "/sealed-records"),
                    {"records": records, "slug": slug})


def refusal_summary(conn, window_days=None):
    path = "/api/object-refusals"
    if window_days is not None:
        path += "?" + urllib.parse.urlencode({"window": window_days})
    return _request("GET", path)


def admin_import(payload):
    """One-shot state migration into a fresh Worker store (POST
    /api/admin/import). No conn — this is a whole-DB push, not a per-promotion
    op. Refused 409 by the Worker unless every table is empty."""
    return _request("POST", "/api/admin/import", payload)
