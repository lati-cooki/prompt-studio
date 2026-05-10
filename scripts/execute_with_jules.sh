#!/usr/bin/env bash
# execute_with_jules.sh — Look up a registered prompt and run a task via jules new.
#
# Usage:
#   ./scripts/execute_with_jules.sh <registry-id> "<task>" [--version <ver>] [--index <path>] [--dry-run]
#
# Examples:
#   ./scripts/execute_with_jules.sh consensus_protocol "Evaluate the StrategiAI seed round plan"
#   ./scripts/execute_with_jules.sh consensus_protocol "Evaluate path B" --version 1.1.0
#   ./scripts/execute_with_jules.sh consensus_protocol "Evaluate X" --dry-run
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
  echo "Usage: $(basename "$0") <registry-id> <task> [--version <ver>] [--index <path>] [--dry-run]"
  echo ""
  echo "  registry-id   Prompt ID in INDEX.json (e.g. consensus_protocol)"
  echo "  task          Task to execute with the prompt as context"
  echo "  --version     Specific version (default: latest active/production)"
  echo "  --index       Path to INDEX.json (default: registry/INDEX.json)"
  echo "  --dry-run     Print the jules command without running it"
  exit 1
}

REGISTRY_ID=""
TASK=""
VERSION_ARG=""
INDEX="$REPO_ROOT/registry/INDEX.json"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)  VERSION_ARG="--version $2"; shift 2 ;;
    --index)    INDEX="$2";                 shift 2 ;;
    --dry-run)  DRY_RUN=1;                  shift   ;;
    --help|-h)  usage ;;
    *)
      if   [[ -z "$REGISTRY_ID" ]]; then REGISTRY_ID="$1"
      elif [[ -z "$TASK" ]];         then TASK="$1"
      else echo "Unexpected argument: $1"; usage
      fi
      shift ;;
  esac
done

[[ -z "$REGISTRY_ID" || -z "$TASK" ]] && usage

# Resolve prompt file via the Python helper
PROMPT_FILE=$(cd "$REPO_ROOT" && python3 scripts/lookup_prompt.py "$REGISTRY_ID" $VERSION_ARG --index "$INDEX" 2>&1)
if [[ "$PROMPT_FILE" == ERROR:* ]]; then
  echo "$PROMPT_FILE" >&2
  exit 1
fi

PROMPT_FILE="$REPO_ROOT/$PROMPT_FILE"
if [[ ! -f "$PROMPT_FILE" ]]; then
  echo "ERROR: Prompt file not found: $PROMPT_FILE" >&2
  exit 1
fi

PROMPT_BODY="$(cat "$PROMPT_FILE")"
FULL_CONTEXT="$(printf '%s\n\n---\n\nTask: %s' "$PROMPT_BODY" "$TASK")"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Registry ID : $REGISTRY_ID"
echo "Prompt file : $PROMPT_FILE"
echo "Task        : $TASK"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ $DRY_RUN -eq 1 ]]; then
  echo "[dry-run] Would execute:"
  echo "  jules new \"<prompt body + task>\""
  echo ""
  echo "=== Context preview (first 400 chars) ==="
  echo "${FULL_CONTEXT:0:400}"
  exit 0
fi

jules new "$FULL_CONTEXT"
