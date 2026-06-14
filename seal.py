import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request

CLISTA_CLI = os.environ.get("CLISTA_CLI", os.path.expanduser("~/ClisTa-Protocol/src/cli.js"))
THREADHUB_PORT = int(os.environ.get("THREADHUB_PORT", "8110"))
AUTHOR_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".seal_author_id")


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


def _clista(args, cwd):
    proc = subprocess.run(["node", CLISTA_CLI] + args, cwd=cwd,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise SealError(f"clista {' '.join(args[:2])} failed: {detail}")
    return json.loads(proc.stdout)


def _clista_validate(cwd):
    proc = subprocess.run(["node", CLISTA_CLI, "validate"], cwd=cwd,
                          capture_output=True, text=True)
    return json.loads(proc.stdout)


def author_clista_log(data, cwd):
    """Author the decision-as-claim log in <cwd>/.clista; return the events.ndjson path."""
    tid = _clista(["thread", "create", "--title", data["title"],
                   "--question", data["question"]], cwd)["thread"]["id"]
    pid = _clista(["participant", "declare", "--name", data["decidedBy"],
                   "--thread", tid], cwd)["participant"]["id"]
    evidence_ids = []
    for e in data["evidence"]:
        ev = _clista(["evidence", "commit", "--thread", tid,
                      "--source", e["source"], "--finding", e["finding"]], cwd)
        evidence_ids.append(ev["evidence"]["id"])
    cid = _clista(["claim", "create", "--thread", tid, "--text", data["decision"],
                   "--evidence", ",".join(evidence_ids)], cwd)["claim"]["id"]
    for text in data["objections"]:
        _clista(["objection", "raise", "--thread", tid, "--participant", pid,
                 "--target", cid, "--text", text], cwd)
    result = _clista_validate(cwd)
    if not result.get("valid"):
        raise SealError("ClisTa validation failed", extra={"errors": result.get("errors")})
    return os.path.join(cwd, ".clista", "events.ndjson")


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
