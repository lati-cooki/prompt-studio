#!/usr/bin/env python3
"""anchor_backfill.py — retroactive anchor rows for ALL current hub threads.

Enumerates every hub thread (GET /threads), verifies each (GET /t/<slug>/verify),
and appends one ANCHORS.md row per (slug, head) pair not already anchored.
Anchoring is testimony about the past, and the past includes the
string-writer/custodial era: heads are captured AS THEY ARE, every backfilled
row's note discloses the pre-Phase-5 custody regime, and `anchored_at` is the
time this testimony was given — the head hash is what the testimony pins. No
seal-time timestamps are fabricated (the two-timestamp honesty).

Idempotent by (slug, head): a slug already anchored at the same head is
skipped; a slug whose head has MOVED (threads grow) gets a NEW row appended.
Existing rows are never edited — the file only ever grows.

SAFETY: dry-run by default (read-only GETs; prints the rows it would add).
Writing ANCHORS.md requires an explicit --execute. The script never
git-commits — the controller runs it and makes the one retroactive commit.

Usage:
  python3 scripts/anchor_backfill.py             # dry run (default)
  python3 scripts/anchor_backfill.py --execute
"""
import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import anchors  # noqa: E402

DEFAULT_HUB = f"http://localhost:{os.environ.get('THREADHUB_PORT', '8110')}"
DEFAULT_ANCHORS = os.path.join(anchors.REPO_ROOT, anchors.ANCHORS_FILE)

BACKFILL_NOTE = ("retroactive backfill; sealed under pre-Phase-5 custody "
                 "(single custodial studio author); anchored_at is the "
                 "backfill time, not the seal time")


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


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


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Backfill retroactive anchor rows for all hub threads "
                    "(dry-run by default; never git-commits).")
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

    existing = existing_keys(args.anchors)
    anchored_at = anchors.now_iso()  # one testimony time for the whole run

    rows, skipped_anchored, skipped_headless = [], 0, []
    for thread in fetch_json(args.hub + "/threads"):
        slug = thread.get("slug")
        verify = fetch_json(f"{args.hub}/t/{slug}/verify")
        head = verify.get("head")
        if not head:
            skipped_headless.append(slug)
            continue
        if (slug, head) in existing:
            skipped_anchored += 1
            continue
        rows.append(anchors.format_row(anchored_at, slug, head,
                                       verify.get("records"),
                                       verify.get("thread"), BACKFILL_NOTE))

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
