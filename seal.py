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


def validate_payload(payload):
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

    evidence = []
    for e in (payload.get("evidence") or []):
        source, finding = _s(e.get("source")), _s(e.get("finding"))
        if source and finding:
            evidence.append({"source": source, "finding": finding})
    if not evidence:
        fields["evidence"] = "at least one evidence item (source + finding) required"

    objections = []
    for o in (payload.get("objections") or []):
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
