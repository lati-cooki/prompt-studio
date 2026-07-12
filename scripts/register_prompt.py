#!/usr/bin/env python3
"""
register_prompt.py — Append a prompt draft + eval result to registry/INDEX.json.

Usage:
  python3 scripts/register_prompt.py \
    --draft /path/to/draft.json \
    --eval-data registry/evals/eval_my_prompt_v0_1_0_2026-05-10_data.json \
    --index registry/INDEX.json
"""
import argparse
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone


def check_duplicate(index: dict, prompt_id: str, version: str) -> bool:
    for entry in index.get("prompts", []):
        if entry.get("id") == prompt_id and entry.get("version") == version:
            return True
    return False


def merge_eval_into_draft(draft: dict, eval_data: dict) -> dict:
    """Produce a registry entry from draft + eval data. Removes the body field."""
    grade = eval_data.get("grade")
    if grade is None:
        eval_status = "pending"
    elif grade in ("F",):
        eval_status = "failed"
    else:
        eval_status = "passed"

    entry = {k: v for k, v in draft.items() if k != "body"}

    entry["eval_status"] = eval_status
    entry["eval_batch"]  = eval_data["id"]

    if eval_data.get("cost_usd_estimated") is not None:
        entry["cost_per_run_usd"] = eval_data["cost_usd_estimated"]

    model = eval_data.get("model")
    if model and model not in entry.get("tested_on", []):
        entry.setdefault("tested_on", []).append(model)

    return entry


def append_to_index(index_path: str, entry: dict) -> None:
    """Read INDEX.json, append entry, write back atomically."""
    with open(index_path) as f:
        index = json.load(f)

    index["prompts"].append(entry)
    index["generated_at"] = datetime.now(timezone.utc).isoformat()

    dir_name = os.path.dirname(os.path.abspath(index_path))
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(index, f, indent=2)
        os.replace(tmp_path, index_path)
    except Exception:
        os.unlink(tmp_path)
        raise


def insert_into_db(db_path: str, entry: dict, body: str = ""):
    """Record the prompt in the live SQLite DB so /api/registry shows it
    without waiting for a server restart.

    INSERT OR IGNORE on (id, version): an existing row keeps its live state
    (promotion-flow status flips are never clobbered). Returns a
    (status, detail) tuple — "inserted" | "exists" | "skipped". Missing DB
    or missing table is a skip, not an error: the server's boot-time
    backfill picks the prompt up from INDEX.json instead."""
    if not os.path.exists(db_path):
        return ("skipped", f"{db_path} not found — server backfill will pick it up on next boot")
    conn = sqlite3.connect(db_path)
    try:
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='prompts'").fetchone()
        if not has_table:
            return ("skipped", "no prompts table — server backfill will pick it up on next boot")
        cur = conn.execute(
            """INSERT OR IGNORE INTO prompts
               (id, version, status, tier, owner, body, use_case,
                cost_per_run_usd, tokens_prompt_body, default_model,
                eval_status, file, notes, composes, tested_on)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                entry.get("id"), entry.get("version"), entry.get("status"),
                entry.get("tier"), entry.get("owner"), body, entry.get("use_case"),
                entry.get("cost_per_run_usd"), entry.get("tokens_prompt_body"),
                entry.get("default_model"), entry.get("eval_status"),
                entry.get("file"), entry.get("notes"),
                json.dumps(entry.get("composes", [])),
                json.dumps(entry.get("tested_on", [])),
            ),
        )
        conn.commit()
        if cur.rowcount:
            return ("inserted", f"{entry.get('id')}@{entry.get('version')} added to {db_path}")
        return ("exists", f"{entry.get('id')}@{entry.get('version')} already in {db_path}; live row kept")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Register a prompt draft into INDEX.json.")
    parser.add_argument("--draft",     required=True, help="Draft JSON file (from exportToRegistryDraft)")
    parser.add_argument("--eval-data", required=True, help="Eval data JSON file (from evaluate_prompt.py)")
    parser.add_argument("--index",     default="registry/INDEX.json")
    parser.add_argument("--db",        default=os.environ.get("DB_PATH", "prompt_studio.db"),
                        help="Live studio DB to record the prompt in (skipped if absent)")
    parser.add_argument("--no-db",     action="store_true", help="Skip the DB write")
    args = parser.parse_args()

    with open(args.draft) as f:
        draft = json.load(f)

    with open(args.eval_data) as f:
        eval_data = json.load(f)

    with open(args.index) as f:
        index = json.load(f)

    prompt_id = draft["id"]
    version   = draft["version"]

    if check_duplicate(index, prompt_id, version):
        print(f"ERROR: {prompt_id}@{version} already exists in {args.index}. Aborting.", file=sys.stderr)
        sys.exit(1)

    entry = merge_eval_into_draft(draft, eval_data)
    append_to_index(args.index, entry)

    print(f"Registered {prompt_id}@{version} → {args.index}")

    if not args.no_db:
        try:
            status, detail = insert_into_db(args.db, entry, body=draft.get("body", ""))
            print(f"DB: {status} — {detail}")
        except sqlite3.Error as e:
            # INDEX.json is the canonical artifact and was written; the boot
            # backfill heals the DB, so a DB hiccup is a warning, not a failure.
            print(f"WARNING: DB write failed ({e}); server backfill will pick it up on next boot",
                  file=sys.stderr)


if __name__ == "__main__":
    main()
