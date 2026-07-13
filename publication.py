"""Publication acts — the studio side of "the record is the interface"
(DR-2026-07-13-record-is-the-interface, rule 2; Task 15).

A thread becomes publicly readable only through an explicit ThreadPublished
event appended to that thread, and stops only through an appended
ThreadPublicationRevoked — publication is a witnessed per-thread act with an
actor, not a flag column. This module:

- reads a thread's EFFECTIVE publication state from the hub (the last
  publication event on the thread governs; effective_publication is the
  Python mirror of the hub's pure function,
  packages/threadhub/src/publication.js — same fail-closed rules: a
  malformed act or an unregistered scope publishes nothing);
- appends the publication act through the existing record-append path
  (seal._th POST /t/<slug>/records, kind 'clista.event'), authored by the
  writer the caller resolved — the server resolves the OPERATOR writer and
  refuses without it (an act with an actor, never the legacy shared studio
  author);
- is idempotent by construction: set_publication reads the effective state
  FIRST and appends nothing when the thread is already in the requested
  state (the response says so instead of minting a duplicate event).

The hub this module talks to is the LOCAL sidecar (seal.THREADHUB_PORT) in
default mode; public-facing links are built by callers from
THREADHUB_PUBLIC_BASE_URL (objections.py) — never from here.
"""
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import seal

PUBLISH_TYPE = "ThreadPublished"
REVOKE_TYPE = "ThreadPublicationRevoked"
SCOPE = "public-read"  # the only registered scope (DR-2026-07-13 rule 2)
_TS = "%Y-%m-%dT%H:%M:%SZ"


class PublicationError(Exception):
    def __init__(self, message, status=502, extra=None):
        self.message = message
        self.status = status
        self.extra = extra or {}
        super().__init__(message)


def _now_iso():
    return datetime.now(timezone.utc).strftime(_TS)


def _fetch_envelopes(slug):
    """GET the thread's full record chain (/t/<slug>.json) from the local
    hub — the list of record envelopes, in seq order.

    Timeout is SHORT (3s): this runs inline on the single-threaded studio
    server, including on the public objection-page render when a promotion
    is associated. Disclosed timing caveat (consistent with the D5
    no-oracle posture, which pins BYTES): during a hub outage an associated
    promotion's page stalls up to this timeout while an unassociated one
    does not — the served bytes stay identical (fail closed to 'render
    nothing'; the byte-equality is test-pinned), but the delay is
    observable. Kept, disclosed, and bounded."""
    url = f"{seal._hub_base()}/t/{urllib.parse.quote(slug)}.json"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise PublicationError("thread not found on the hub", 404,
                                   extra={"code": "thread_not_found"})
        raise PublicationError(f"ThreadHub GET /t/{slug}.json returned {e.code}",
                               502, extra={"code": "threadhub_http_error"})
    except urllib.error.URLError:
        raise PublicationError("ThreadHub is not reachable", 502,
                               extra={"code": "threadhub_unreachable"})
    try:
        envelopes = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        raise PublicationError("ThreadHub returned non-JSON for the thread",
                               502, extra={"code": "threadhub_bad_response"})
    if not isinstance(envelopes, list):
        raise PublicationError("unexpected thread export shape", 502,
                               extra={"code": "threadhub_bad_response"})
    return envelopes


def effective_publication(envelopes):
    """Publication state as a pure function of the records — the Python
    mirror of the hub's src/publication.js (keep the two in lockstep;
    tests/test_publication_api.py feeds the shared fixture
    tests/fixtures/publication_drift_cases.json to BOTH implementations,
    so drift fails the suite instead of shipping a dead doorstep link).
    Returns {"published": bool, "act": threadPublication-dict-or-None}.

    Fail closed: a publication event that is malformed, carries an action
    disagreeing with its event type, or names a scope other than the one
    registered scope publishes nothing — and, being the last publication
    event, it also masks any earlier publish."""
    last = None
    for env in envelopes:
        if not isinstance(env, dict) or env.get("kind") != "clista.event":
            continue
        payload = env.get("payload")
        etype = payload.get("event_type") if isinstance(payload, dict) else None
        if etype in (PUBLISH_TYPE, REVOKE_TYPE):
            last = env
    if last is None:
        return {"published": False, "act": None}
    inner = last["payload"].get("payload")
    act = inner.get("threadPublication") if isinstance(inner, dict) else None
    published = (last["payload"].get("event_type") == PUBLISH_TYPE
                 and isinstance(act, dict)
                 and act.get("action") == "publish"
                 and act.get("scope") == SCOPE)
    return {"published": published, "act": act}


def publication_state(slug):
    """The thread's effective publication state, read from the hub.
    Raises PublicationError (404 unknown thread, 502 hub trouble)."""
    envelopes = _fetch_envelopes(slug)
    state = effective_publication(envelopes)
    thread_id = envelopes[0].get("thread") if envelopes else None
    return {"slug": slug, "thread_id": thread_id, **state}


def is_published(slug):
    """True only when the hub says the thread is effectively published.
    False on ANY failure — fail closed: a surface deciding whether to render
    a public link must render nothing when it cannot know (no dead links,
    no slug leakage)."""
    try:
        return bool(publication_state(slug)["published"])
    except Exception:
        return False


def _publication_event(action, thread_id, actor_id):
    """The ClisTa publication event (registered vocabulary — payload shape
    per DR-2026-07-13: packages/protocol/src/event-types.js)."""
    now = _now_iso()
    return {
        "event_type": PUBLISH_TYPE if action == "publish" else REVOKE_TYPE,
        "actor_id": actor_id,
        "timestamp": now,
        "payload": {
            "threadPublication": {
                "id": "tpb_" + secrets.token_hex(8),
                "object": "threadPublication",
                "threadId": thread_id,
                "action": action,
                "scope": SCOPE,
                "publishedByParticipantId": actor_id,
                "publishedAt": now,
            }
        },
    }


def set_publication(slug, action, writer):
    """Publish ('publish') or unpublish ('revoke') the thread as a witnessed
    act authored by `writer` (a writers.py row — its threadhub_id signs the
    record). Reads the effective state FIRST: a no-op appends nothing and
    says so. Returns {slug, published, changed} plus the appended record's
    seq + record_hash when a record was appended.

    May raise PublicationError (state read) or seal.SealError (append)."""
    state = publication_state(slug)
    want = action == "publish"
    if state["published"] == want:
        return {
            "slug": slug,
            "published": want,
            "changed": False,
            "note": ("already effectively published — nothing appended"
                     if want else
                     "not effectively published — nothing appended"),
        }
    event = _publication_event(action, state["thread_id"],
                               writer["threadhub_id"])
    resp = seal._th("POST", f"/t/{slug}/records",
                    {"author": writer["threadhub_id"],
                     "kind": "clista.event",
                     "payload": event})
    return {
        "slug": slug,
        "published": want,
        "changed": True,
        "seq": resp.get("seq"),
        "record_hash": resp.get("record_hash"),
    }
