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
