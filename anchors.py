"""anchors.py — external anchoring of studio seals (DR-phase5-topology, Decision 4).

After a successful seal, one row is appended to ANCHORS.md pinning the sealed
hub thread's head, then committed and pushed in this repo. What that anchor
proves is a weak external timestamp: the anchored head existed no later than
the anchor commit's push, as witnessed by the hosting provider's git history
(rule 4.2). It is not cryptographic notarization (rule 4.3), and it never
changes canonicality (rule 2.1): the hub records remain the canonical
artifacts, and a seal that fails to anchor is still a seal.

Contract of anchor_seal(): it NEVER raises to the caller. Every failure branch
returns {"anchored": False, "anchor_error": <specific message>} and leaves the
git index and ANCHORS.md exactly as they were. A push failure after a
successful local commit returns {"anchored": True, "anchor_pushed": False,
"anchor_push_error": ...} — the local commit is the anchor's first witness;
the push is what makes it external, and the two are reported separately.
"""
import os
import subprocess
from datetime import datetime, timezone

import seal

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
ANCHORS_FILE = "ANCHORS.md"
GIT_TIMEOUT = 60  # seconds per git command


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_row(anchored_at, slug, head, records, thread_id, note=""):
    """One ANCHORS.md table row. Columns match the header seeded in ANCHORS.md:
    | anchored_at (ISO, UTC) | slug | head hash | records | hub thread id | note |

    An unknown records count renders as "?" — the row (head testimony) is
    still worth appending; "None" would read as a recorded value.
    """
    records = "?" if records is None else records
    return f"| {anchored_at} | {slug} | {head} | {records} | {thread_id} | {note} |"


def _git(args, repo_root):
    """Run one git command in repo_root; return (ok, specific message)."""
    try:
        proc = subprocess.run(["git"] + args, cwd=repo_root,
                              capture_output=True, text=True,
                              timeout=GIT_TIMEOUT)
    except FileNotFoundError:
        return False, "git executable not found"
    except subprocess.TimeoutExpired:
        return False, f"git {args[0]} timed out after {GIT_TIMEOUT}s"
    if proc.returncode != 0:
        detail = (proc.stderr.strip() or proc.stdout.strip())[:300]
        return False, f"git {args[0]} failed: {detail}"
    return True, ""


def anchor_seal(slug, repo_root=None, note=""):
    """Anchor a sealed thread's head into this repo's git history.

    Returns a dict of API response fields (anchored / anchor_error /
    anchor_pushed / anchor_push_error). Never raises: anchoring failure is
    loudly reported, never fatal — the seal already exists in the hub.
    """
    repo_root = repo_root or REPO_ROOT
    try:
        return _anchor(slug, repo_root, note)
    except Exception as e:  # catch-all keeps the no-raise contract absolute
        msg = getattr(e, "message", None) or str(e)
        return {"anchored": False,
                "anchor_error": f"unexpected anchoring failure: {msg}"}


def _anchor(slug, repo_root, note):
    try:
        verify = seal._th("GET", f"/t/{slug}/verify")
    except seal.SealError as e:
        return {"anchored": False,
                "anchor_error": f"hub verify failed: {e.message}"}
    head = verify.get("head")
    if not head:
        return {"anchored": False,
                "anchor_error": f"hub verify for '{slug}' returned no head"}

    path = os.path.join(repo_root, ANCHORS_FILE)
    if not os.path.exists(path):
        return {"anchored": False,
                "anchor_error": f"{ANCHORS_FILE} not found in {repo_root}"}

    row = format_row(now_iso(), slug, head, verify.get("records"),
                     verify.get("thread"), note)
    prior_size = os.path.getsize(path)

    def _rollback():
        # Restore ANCHORS.md to its pre-append content so a failed anchor
        # leaves no stray row (one row per anchor commit, always).
        with open(path, "a") as f:
            f.truncate(prior_size)

    try:
        with open(path, "a") as f:
            f.write(row + "\n")
    except OSError as e:
        return {"anchored": False,
                "anchor_error": f"could not append to {ANCHORS_FILE}: {e}"}

    ok, msg = _git(["add", ANCHORS_FILE], repo_root)
    if not ok:
        _rollback()
        return {"anchored": False, "anchor_error": msg}

    head_short = head.split(":", 1)[-1][:12]
    ok, msg = _git(["commit", "-m", f"anchor: {slug} head {head_short}"],
                   repo_root)
    if not ok:
        # never leave a dirty index: unstage the add, then restore the file
        _git(["reset", "--", ANCHORS_FILE], repo_root)
        _rollback()
        return {"anchored": False, "anchor_error": msg}

    ok, msg = _git(["push"], repo_root)
    if not ok:
        return {"anchored": True, "anchor_pushed": False,
                "anchor_push_error": msg}
    return {"anchored": True, "anchor_pushed": True}
