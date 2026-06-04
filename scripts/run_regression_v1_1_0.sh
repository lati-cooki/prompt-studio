#!/usr/bin/env bash
# Regression batch for consensus_protocol@1.1.0 vs strategiai_directive.md
# Requires: ANTHROPIC_API_KEY, pip install anthropic
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "ERROR: ANTHROPIC_API_KEY is not set." >&2
  echo "Export your key, then re-run: ./scripts/run_regression_v1_1_0.sh" >&2
  exit 1
fi

PROMPT="registry/prompts/consensus_protocol_v1_1_0.md"
DIRECTIVE="registry/evals/strategiai_directive.md"
OUT="registry/evals/"

MODELS=(
  "claude-opus-4-7"
  "claude-sonnet-4-6"
)

echo "Running consensus_protocol v1.1.0 regression (${#MODELS[@]} Anthropic models)…"
for model in "${MODELS[@]}"; do
  echo "--- $model ---"
  python3 scripts/evaluate_prompt.py \
    --prompt "$PROMPT" \
    --directive "$DIRECTIVE" \
    --model "$model" \
    --output-dir "$OUT"
done

echo ""
echo "Done. Review each eval_*.md Step 0 section for arithmetic inconsistency detection."
echo "Grade in markdown + *_data.json, then register with register_prompt.py if passing."