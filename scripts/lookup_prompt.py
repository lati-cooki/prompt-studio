#!/usr/bin/env python3
"""
lookup_prompt.py — Find a prompt entry in INDEX.json and return its file path.

Used by execute_with_jules.sh. Also callable directly:
  python3 scripts/lookup_prompt.py consensus_protocol
  python3 scripts/lookup_prompt.py consensus_protocol --version 1.0.0
"""
import argparse
import json
import sys
from typing import Dict, List, Optional


STATUS_RANK = {"production": 0, "active": 1, "draft": 2, "deprecated": 3}


def find_prompt(prompts: List[dict], registry_id: str, version: Optional[str] = None) -> Optional[Dict]:
    matches = [p for p in prompts if p.get("id") == registry_id]
    if not matches:
        return None
    if version:
        matches = [p for p in matches if p.get("version") == version]
        if not matches:
            return None
        return matches[0]
    # Prefer production > active > draft > deprecated; then highest version string
    matches.sort(key=lambda p: (STATUS_RANK.get(p.get("status", ""), 99), p.get("version", "")))
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description="Look up a prompt file path from INDEX.json.")
    parser.add_argument("registry_id", help="Prompt ID (e.g. consensus_protocol)")
    parser.add_argument("--version", default=None)
    parser.add_argument("--index", default="registry/INDEX.json")
    args = parser.parse_args()

    with open(args.index) as f:
        data = json.load(f)

    prompt = find_prompt(data.get("prompts", []), args.registry_id, args.version)

    if prompt is None:
        print(f"ERROR: No prompt found with id '{args.registry_id}'" +
              (f" version '{args.version}'" if args.version else ""), file=sys.stderr)
        sys.exit(1)

    file_path = prompt.get("file")
    if not file_path:
        print(f"ERROR: Prompt '{prompt['id']}@{prompt['version']}' has no file path (null).", file=sys.stderr)
        sys.exit(1)

    # Print the full path relative to registry/
    print(f"registry/{file_path}")


if __name__ == "__main__":
    main()
