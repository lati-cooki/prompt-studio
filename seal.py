import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request

CLISTA_CLI = os.environ.get("CLISTA_CLI", os.path.expanduser("~/ClisTa-Protocol/src/cli.js"))
THREADHUB_PORT = int(os.environ.get("THREADHUB_PORT", "8110"))
# When THREADHUB_BASE_URL is set it SUPERSEDES the port entirely on the
# studio->hub path (the hub may be a remote host on Cloudflare, not the local
# sidecar); default is the unchanged localhost bind, so the fully-local path is
# byte-for-byte identical. THREADHUB_WRITE_TOKEN, when set, adds a bearer to
# every studio->hub request (the remote hub gates writes). This one seam also
# routes writers.ensure_writer and publication.set_publication (both go through
# _th) at the remote hub with no further edits.
THREADHUB_BASE_URL = (os.environ.get("THREADHUB_BASE_URL") or "").rstrip("/") or None
THREADHUB_WRITE_TOKEN = os.environ.get("THREADHUB_WRITE_TOKEN") or None
# Cloudflare's edge returns 403 to requests with the Python-urllib default
# User-Agent, so every studio->hub call must send a custom UA.
USER_AGENT = "clista-operator/1.0"
AUTHOR_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".seal_author_id")


def _hub_base():
    """Base URL for the studio->hub path. THREADHUB_BASE_URL supersedes the
    port; default stays the local sidecar bind (THREADHUB_PORT is read at call
    time so tests patching seal.THREADHUB_PORT keep working)."""
    return THREADHUB_BASE_URL or f"http://localhost:{THREADHUB_PORT}"


class SealValidationError(Exception):
    def __init__(self, fields):
        self.fields = fields
        super().__init__("invalid seal payload")


class SealError(Exception):
    def __init__(self, message, status=500, extra=None):
        self.message = message
        self.status = status
        self.extra = extra or {}
        super().__init__(message)


def _s(v):
    return v.strip() if isinstance(v, str) else ""


def _parse_json(stdout, ctx):
    try:
        return json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        raise SealError(f"clista {ctx} returned non-JSON output: {stdout[:200]}")


def _clista(args, cwd):
    try:
        proc = subprocess.run(["node", CLISTA_CLI] + args, cwd=cwd,
                              capture_output=True, text=True)
    except FileNotFoundError:
        raise SealError("node/clista CLI not found — check CLISTA_CLI",
                        status=500, extra={"code": "clista_unavailable"})
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise SealError(f"clista {' '.join(args[:2])} failed: {detail}")
    return _parse_json(proc.stdout, " ".join(args[:2]))


def _clista_validate(cwd):
    # validate exits 1 when invalid but still prints {valid, errors} JSON, so do NOT
    # gate on returncode; only a non-JSON stdout (a real crash) is an error.
    try:
        proc = subprocess.run(["node", CLISTA_CLI, "validate"], cwd=cwd,
                              capture_output=True, text=True)
    except FileNotFoundError:
        raise SealError("node/clista CLI not found — check CLISTA_CLI",
                        status=500, extra={"code": "clista_unavailable"})
    return _parse_json(proc.stdout, "validate")


def _capture(resp, *path):
    cur = resp
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            raise SealError("unexpected response (missing "
                            + ".".join(path) + ")", extra={"response": resp})
        cur = cur[key]
    return cur


def author_clista_log(data, cwd):
    """Author the decision-as-claim log in <cwd>/.clista; return the events.ndjson path."""
    tid = _capture(_clista(["thread", "create", "--title", data["title"],
                            "--question", data["question"]], cwd), "thread", "id")
    pid = _capture(_clista(["participant", "declare", "--name", data["decidedBy"],
                            "--thread", tid], cwd), "participant", "id")
    evidence_ids = []
    for e in data["evidence"]:
        ev = _clista(["evidence", "commit", "--thread", tid,
                      "--source", e["source"], "--finding", e["finding"]], cwd)
        evidence_ids.append(_capture(ev, "evidence", "id"))
    cid = _capture(_clista(["claim", "create", "--thread", tid, "--text", data["decision"],
                            "--evidence", ",".join(evidence_ids)], cwd), "claim", "id")
    for text in data["objections"]:
        _clista(["objection", "raise", "--thread", tid, "--participant", pid,
                 "--target", cid, "--text", text], cwd)
    result = _clista_validate(cwd)
    if not result.get("valid"):
        raise SealError("ClisTa validation failed", extra={"errors": result.get("errors")})
    return os.path.join(cwd, ".clista", "events.ndjson")


def _th(method, path, body=None):
    url = f"{_hub_base()}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if THREADHUB_WRITE_TOKEN:
        headers["Authorization"] = f"Bearer {THREADHUB_WRITE_TOKEN}"
    headers["User-Agent"] = USER_AGENT
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        status = 429 if e.code == 429 else 502
        raise SealError(f"ThreadHub {method} {path} returned {e.code}",
                        status=status, extra={"code": "threadhub_http_error"})
    except urllib.error.URLError:
        raise SealError("ThreadHub is not reachable", status=502,
                        extra={"code": "threadhub_unreachable"})
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        raise SealError(f"ThreadHub {method} {path} returned non-JSON: {raw[:200]}",
                        status=502, extra={"code": "threadhub_bad_response"})


def ensure_author():
    if os.path.exists(AUTHOR_CACHE):
        with open(AUTHOR_CACHE) as f:
            cached = f.read().strip()
        if cached:
            return cached
    author_id = _capture(_th("POST", "/identities",
                             {"display_name": "Prompt Studio", "kind": "agent"}), "id")
    with open(AUTHOR_CACHE, "w") as f:
        f.write(author_id)
    return author_id


def _author_for_event(event_type, writers, objection_index):
    """Envelope author per record by ClisTa event_type (DR-phase5-topology 5.2:
    semantic author = transport writer). Anything unmapped falls back to the
    default writer (the operator in the promotion flow)."""
    default = writers["default"]
    if event_type == "ClaimCreated":
        return writers.get("claim") or default
    if event_type == "EvidenceCommitted":
        return writers.get("evidence") or default  # grader, when known
    if event_type == "ObjectionRaised":
        objections = writers.get("objections") or []
        if objection_index < len(objections) and objections[objection_index]:
            return objections[objection_index]
        return default
    return default  # genesis / everything else


def write_to_threadhub(events_path, title, question, writers):
    """Write the authored ClisTa log to ThreadHub, one record per event line.

    `writers` is either a legacy single author id (str — every request body is
    byte-identical to the pre-slice-2 implementation) or a mapping:
      {"default": id, "claim": id, "evidence": id, "objections": [id, ...]}
    The n-th ObjectionRaised is authored by writers["objections"][n].

    Returns {"slug", "citationHash", "records": [{seq, record_hash, event_type}]}
    — the per-record shape is the Slice 6 (tokenized objections) receipt contract.
    """
    if isinstance(writers, str):
        writers = {"default": writers}
    default_author = writers["default"]
    slug = _capture(_th("POST", "/threads",
                        {"title": title, "question": question, "author": default_author}),
                    "slug")
    records = []
    objection_index = 0
    try:
        with open(events_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    raise SealError("authored ClisTa log contains a malformed line",
                                    status=500)
                event_type = payload.get("event_type") if isinstance(payload, dict) else None
                author = _author_for_event(event_type, writers, objection_index)
                if event_type == "ObjectionRaised":
                    objection_index += 1
                resp = _th("POST", f"/t/{slug}/records",
                           {"author": author, "kind": "clista.event", "payload": payload})
                records.append({"seq": resp.get("seq"),
                                "record_hash": resp.get("record_hash"),
                                "event_type": event_type})
    except SealError as e:
        e.extra["partialSlug"] = slug
        raise
    verify = _th("GET", f"/t/{slug}/verify")
    return {"slug": slug, "citationHash": verify.get("head"), "records": records}


def validate_payload(payload):
    if not isinstance(payload, dict):
        raise SealValidationError({"payload": "must be a JSON object"})
    fields = {}
    question = _s(payload.get("question"))
    decision = _s(payload.get("decision"))
    decided_by = _s(payload.get("decidedBy"))
    if not question:
        fields["question"] = "required"
    if not decision:
        fields["decision"] = "required"
    if not decided_by:
        fields["decidedBy"] = "required"

    evidence_in = payload.get("evidence")
    evidence = []
    for e in (evidence_in if isinstance(evidence_in, list) else []):
        if not isinstance(e, dict):
            continue
        source, finding = _s(e.get("source")), _s(e.get("finding"))
        if source and finding:
            evidence.append({"source": source, "finding": finding})
    if not evidence:
        fields["evidence"] = "at least one evidence item (source + finding) required"

    objections_in = payload.get("objections")
    objections = []
    for o in (objections_in if isinstance(objections_in, list) else []):
        text = _s(o.get("text")) if isinstance(o, dict) else _s(o)
        if text:
            objections.append(text)

    if fields:
        raise SealValidationError(fields)

    return {
        "title": _s(payload.get("title")) or question,
        "question": question,
        "decision": decision,
        "decidedBy": decided_by,
        "evidence": evidence,
        "objections": objections,
    }


def seal_decision(payload, writers=None):
    """Seal a decision. `writers` (optional mapping, see write_to_threadhub)
    assigns a distinct custodial writer per record; without it the legacy
    shared studio author is used, byte-identically to before."""
    data = validate_payload(payload)
    tmp = tempfile.mkdtemp(prefix="seal-")
    try:
        events_path = author_clista_log(data, tmp)
        if writers is None:
            writers = ensure_author()
        return write_to_threadhub(events_path, data["title"], data["question"], writers)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
