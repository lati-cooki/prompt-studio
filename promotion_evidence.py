"""Eval artifacts: pin the latest eval run as promotion evidence, and grade
eval runs as an act with an actor (Phase 5 slice 2).

Attach-latest strategy (decided at plan time): promotion does NOT invoke the
Claude API synchronously; it pins the newest existing
registry/evals/eval_<id>_v<ver>_*_data.json written by scripts/evaluate_prompt.py.
The content_hash is sha256 over the file bytes — the whole eval record is pinned,
not a summary of it.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_EVALS_DIR = Path(__file__).resolve().parent / "registry" / "evals"

_GRADE_RE = re.compile(r"[A-F][+-]?")


class GradeError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status = status
        super().__init__(message)


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
        "grade": data.get("grade"),
        "graded_by": data.get("graded_by"),
        "rerun": ("python3 scripts/evaluate_prompt.py --prompt <archived prompt file> "
                  f"--model {model or '<model>'} --output-dir registry/evals/"),
    }


def grade_eval(eval_id, grade, notes, graded_by, evals_dir=None):
    """Grade an eval run, stamping the acting writer. Append-only discipline:
    keys are added and md lines appended; a recorded grade value is never
    rewritten (a conflicting re-grade is a 409, not an overwrite)."""
    evals_dir = Path(evals_dir) if evals_dir else DEFAULT_EVALS_DIR
    if not _GRADE_RE.fullmatch(grade or ""):
        raise GradeError(f"invalid grade {grade!r} — expected A/A-/B+/B/C/F style", 422)
    data_path = evals_dir / f"{eval_id}_data.json"
    if not data_path.exists():
        raise GradeError(f"eval {eval_id} not found", 404)
    data = json.loads(data_path.read_text())
    if data.get("graded_by"):
        raise GradeError(
            f"already graded by {data['graded_by']} — grading is append-only", 409)
    prior = data.get("grade")
    if prior is not None and prior != grade:
        raise GradeError(
            f"grade already recorded as {prior!r} — a recorded value is never "
            "rewritten (append a correction instead)", 409)
    graded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["grade"] = grade
    data["graded_by"] = graded_by
    data["graded_at"] = graded_at
    notes = (notes or "").strip()
    if notes:
        existing = (data.get("notes") or "").strip()
        data["notes"] = f"{existing}\n{notes}" if existing else notes
    data_path.write_text(json.dumps(data, indent=2))
    md_path = evals_dir / f"{eval_id}.md"
    if md_path.exists():
        with open(md_path, "a") as f:
            f.write(f"\nGraded {grade} by {graded_by} at {graded_at}."
                    + (f" Notes: {notes}\n" if notes else "\n"))
    return {"id": eval_id, "grade": grade, "graded_by": graded_by,
            "graded_at": graded_at, "notes": data.get("notes", "")}
