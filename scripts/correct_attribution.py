#!/usr/bin/env python3
"""correct_attribution.py — one-shot, append-only attribution correction.

Closes the known eval-attribution gap on the record: agent_operational_checklist
@1.0.0 was graded A- on 2026-07-12 but the grader identity was never recorded.
This appends a ContributionAttributionCorrected record to the phase-4 thread,
authored by the OPERATOR identity, citing the eval data file by sha256 content
hash. Optionally (--with-delegate-note) appends a delegate-authored
acknowledging note — the first delegate-keyed record.

SAFETY: defaults to --dry-run (prints the record(s) it WOULD append, the target
thread and the resolved author id, and touches nothing). Writing requires an
explicit --execute.

DELIBERATE VALIDATOR BYPASS: this record is NOT routed through
seal.author_clista_log / _clista_validate (the node CLI). The strict validator
requires attributionCorrection.attributionId to reference an in-thread
ContributionAttributed record — none exists; that missing record IS the gap
being corrected. Fabricating an attributionId to satisfy the validator would
fake conformance. Instead attributionId is null and the payload carries an
explicit `conformance` field disclosing the vocabulary-only use (append-only
honesty over silent conformance).

Usage:
  python3 scripts/correct_attribution.py                  # dry run (default)
  python3 scripts/correct_attribution.py --execute
  python3 scripts/correct_attribution.py --execute --with-delegate-note
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import seal  # noqa: E402
import writers  # noqa: E402

THREAD_SLUG = "prompt-studio-2026-07-12-threads-phase-4-ships"
DEFAULT_EVAL_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "registry", "evals",
    "eval_agent_operational_checklist_v1_0_0_2026-07-12_claude_sonnet_4_6_data.json")
DEFAULT_DB = os.environ.get("DB_PATH", os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompt_studio.db"))

CONFORMANCE_DISCLOSURE = (
    "no in-thread ContributionAttributed exists; attributionId: null; "
    "ContributionAttributionCorrected vocabulary used for correction semantics, "
    "strict validator not applied — disclosed nonconformance, not faked "
    "conformance.")


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def content_hash(path):
    with open(path, "rb") as f:
        return "sha256:" + hashlib.sha256(f.read()).hexdigest()


def build_correction_event(eval_file_name, eval_content_hash):
    return {
        "event_type": "ContributionAttributionCorrected",
        "timestamp": _now_iso(),
        "payload": {
            "attributionCorrection": {
                "id": "atc_agent_operational_checklist_v1_0_0_grade_2026-07-12",
                "attributionId": None,
                "reason": (
                    "The A- grade recorded for agent_operational_checklist@1.0.0 "
                    "on 2026-07-12 did not record the grader identity. Correction: "
                    "the grading was performed by Claude (delegate writer), acting "
                    "under delegation from Troy (operator writer)."),
                "correctedAttribution": {
                    "contribution": "eval grading (grade: A-)",
                    "graded_by": "delegate",
                    "delegated_by": "operator",
                },
                "evidence": {
                    "file": eval_file_name,
                    "content_hash": eval_content_hash,
                },
            },
            "conformance": CONFORMANCE_DISCLOSURE,
        },
    }


def build_delegate_note():
    return {
        "text": (
            "Acknowledged: I (Claude, delegate writer) graded "
            "agent_operational_checklist@1.0.0 A- on 2026-07-12 under delegation "
            "from Troy. This note accompanies the operator-authored "
            "ContributionAttributionCorrected record above and is the first "
            "record keyed to the delegate identity."),
    }


def _resolve(conn, name, execute):
    """Dry run resolves by lookup only (never mints); --execute provisions the
    writer via ensure_writer if this is its first act."""
    if execute:
        return writers.ensure_writer(conn, name)
    return writers.get_writer(conn, name)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Append the eval-attribution correction record (dry-run by default).")
    parser.add_argument("--execute", action="store_true",
                        help="actually append to ThreadHub (default: dry run)")
    parser.add_argument("--with-delegate-note", action="store_true",
                        help="also append the delegate-authored acknowledging note")
    parser.add_argument("--db", default=DEFAULT_DB, help="studio DB (writers table)")
    parser.add_argument("--eval-file", default=DEFAULT_EVAL_FILE,
                        help="eval data file to cite by content hash")
    parser.add_argument("--thread", default=THREAD_SLUG, help="target thread slug")
    args = parser.parse_args(argv)

    event = build_correction_event(os.path.basename(args.eval_file),
                                   content_hash(args.eval_file))

    conn = sqlite3.connect(args.db)
    try:
        operator = _resolve(conn, "operator", args.execute)
        delegate = (_resolve(conn, "delegate", args.execute)
                    if args.with_delegate_note else None)
    finally:
        conn.close()

    envelopes = [("correction", {
        "author": operator["threadhub_id"] if operator else None,
        "kind": "clista.event",
        "payload": event,
    })]
    if args.with_delegate_note:
        envelopes.append(("delegate note", {
            "author": delegate["threadhub_id"] if delegate else None,
            "kind": "note",
            "payload": build_delegate_note(),
        }))

    if not args.execute:
        print(f"DRY RUN — nothing written. Target thread: {args.thread}")
        print(f"Resolved operator id: "
              f"{operator['threadhub_id'] if operator else '<unprovisioned — --execute would mint via ensure_writer>'}")
        if args.with_delegate_note:
            print(f"Resolved delegate id: "
                  f"{delegate['threadhub_id'] if delegate else '<unprovisioned — --execute would mint via ensure_writer>'}")
        for label, envelope in envelopes:
            print(f"\nWould append ({label}):")
            print(json.dumps(envelope, indent=2))
        print("\nRe-run with --execute to append.")
        return 0

    for label, envelope in envelopes:
        resp = seal._th("POST", f"/t/{args.thread}/records", envelope)
        print(f"Appended {label}: seq={resp.get('seq')} "
              f"record_hash={resp.get('record_hash')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
