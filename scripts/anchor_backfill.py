#!/usr/bin/env python3
"""anchor_backfill.py — retroactive anchor rows for ALL current hub threads.

This script is BOTH the one-time Phase 5 backfill AND the standing recovery
path for seals whose live anchor failed (the seal hook reports anchored:false
and moves on; re-running this script sweeps the missed head into ANCHORS.md).
Re-running stays honest BY CONSTRUCTION because a row's custody clause is
DERIVED, never asserted: it enumerates every hub thread (GET /threads),
verifies each (GET /t/<slug>/verify), and reads each new thread's actual
records (GET /t/<slug>.json) to compute the distinct set of record author
ids — so a thread sealed after per-writer provisioning testifies to its
per-record authors and can never be mislabeled with the legacy
single-custodial-author clause, and vice versa.

Anchoring is testimony about the past, and the past includes the
string-writer/custodial era: heads are captured AS THEY ARE, and
`anchored_at` is the time this testimony was given — the head hash is what
the testimony pins. No seal-time timestamps are fabricated (the two-timestamp
honesty; both invariant clauses appear in every backfilled note).

Idempotent by (slug, head): a slug already anchored at the same head is
skipped; a slug whose head has MOVED (threads grow) gets a NEW row appended.
Existing rows are never edited — the file only ever grows.

SAFETY: dry-run by default (read-only GETs; prints the rows it would add).
Writing ANCHORS.md requires an explicit --execute; rows are gathered before
anything is written, so a hub failure mid-run writes nothing. The script
never git-commits — the controller runs it and makes the retroactive commit.

Usage:
  python3 scripts/anchor_backfill.py             # dry run (default)
  python3 scripts/anchor_backfill.py --execute
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import anchors  # noqa: E402

DEFAULT_HUB = f"http://localhost:{os.environ.get('THREADHUB_PORT', '8110')}"
DEFAULT_ANCHORS = os.path.join(anchors.REPO_ROOT, anchors.ANCHORS_FILE)

# The invariant parts of every backfilled note — the two-timestamp honesty.
# The custody clause between them is DERIVED per thread (custody_clause).
NOTE_PREFIX = "retroactive backfill"
NOTE_SUFFIX = "anchored_at is the backfill time, not the seal time"


class BackfillError(Exception):
    pass


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch(url, what):
    """fetch_json with clean failure reporting: which step, what failed."""
    try:
        return fetch_json(url)
    except Exception as e:
        reason = getattr(e, "reason", None) or e
        raise BackfillError(f"GET {url} failed while fetching {what}: {reason}")


def custody_clause(envelopes):
    """Derive the custody clause from the thread's actual record authors.

    Rows testify to the past AS IT WAS, and the whole clause is observed
    fact — no era is asserted, since a post-provisioning thread can
    legitimately have one distinct author (e.g. an operator-only waived
    promotion). More than one author means per-record writers exist and the
    row must not imply single-author custody (DR 5.3)."""
    authors = {e.get("author") for e in envelopes
               if isinstance(e, dict) and e.get("author")}
    if len(authors) == 1:
        only = next(iter(authors))
        return (f"sealed under single custodial author {only} "
                "(one distinct record author)")
    return (f"per-record authors ({len(authors)} distinct); "
            "custody regime legible per record (DR 5.3)")


def existing_keys(anchors_path):
    """(slug, head) pairs already anchored. Rows are append-only and never
    edited, so a set of keys is all the idempotency state there is."""
    keys = set()
    with open(anchors_path) as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 5:
                continue
            if cells[0].startswith("anchored_at"):  # table header
                continue
            if set(cells[0]) <= set("-: "):  # separator row
                continue
            keys.add((cells[1], cells[2]))
    return keys


def gather_rows(hub, anchors_path):
    """Collect the rows to append (plus skip counts) WITHOUT writing anything —
    a fetch failure mid-run therefore never leaves a partial append."""
    existing = existing_keys(anchors_path)
    anchored_at = anchors.now_iso()  # one testimony time for the whole run
    rows, skipped_anchored, skipped_headless = [], 0, []
    for thread in _fetch(hub + "/threads", "the thread list"):
        slug = thread.get("slug")
        verify = _fetch(f"{hub}/t/{slug}/verify", f"verify for thread '{slug}'")
        head = verify.get("head")
        if not head:
            skipped_headless.append(slug)
            continue
        if (slug, head) in existing:
            skipped_anchored += 1
            continue
        envelopes = _fetch(f"{hub}/t/{slug}.json",
                           f"records for thread '{slug}'")
        note = f"{NOTE_PREFIX}; {custody_clause(envelopes)}; {NOTE_SUFFIX}"
        rows.append(anchors.format_row(anchored_at, slug, head,
                                       verify.get("records"),
                                       verify.get("thread"), note))
    return rows, skipped_anchored, skipped_headless


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Backfill retroactive anchor rows for all hub threads "
                    "(dry-run by default; never git-commits). Also the "
                    "recovery path for seals whose live anchor failed.")
    parser.add_argument("--execute", action="store_true",
                        help="append the rows to ANCHORS.md (default: dry run)")
    parser.add_argument("--hub", default=DEFAULT_HUB,
                        help=f"hub base URL (default {DEFAULT_HUB})")
    parser.add_argument("--anchors", default=DEFAULT_ANCHORS,
                        help="ANCHORS.md path (default: repo root)")
    args = parser.parse_args(argv)

    if not os.path.exists(args.anchors):
        # never create a headerless anchors file — the header IS the honesty
        print(f"ERROR: {args.anchors} not found; refusing to create it "
              "(the seeded header carries the weak-proof disclosure)",
              file=sys.stderr)
        return 1

    try:
        rows, skipped_anchored, skipped_headless = gather_rows(
            args.hub, args.anchors)
    except BackfillError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Nothing was written; re-run once the hub is reachable.",
              file=sys.stderr)
        return 1

    for slug in skipped_headless:
        print(f"skipping {slug}: no head (0 records) — nothing to anchor")

    if not args.execute:
        print(f"DRY RUN — nothing written. Hub: {args.hub}; "
              f"anchors file: {args.anchors}")
        print(f"Would add {len(rows)} row(s); {skipped_anchored} already "
              f"anchored (skipped); {len(skipped_headless)} headless (skipped).")
        for row in rows:
            print(row)
        print("Re-run with --execute to append. No git commit either way — "
              "the controller makes the one retroactive commit.")
        return 0

    with open(args.anchors, "a") as f:
        for row in rows:
            f.write(row + "\n")
    print(f"Appended {len(rows)} row(s) to {args.anchors}; {skipped_anchored} "
          f"already anchored (skipped); {len(skipped_headless)} headless (skipped).")
    print("No git commit was made — the controller makes the one retroactive commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
