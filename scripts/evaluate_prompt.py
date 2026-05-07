#!/usr/bin/env python3
import sys
import json
import os

if len(sys.argv) < 2:
    print("Usage: evaluate_prompt.py <draft_prompt_file>")
    sys.exit(1)

draft_file = sys.argv[1]
with open(draft_file, 'r') as f:
    if draft_file.endswith('.json'):
        draft = json.load(f)
        prompt_text = draft.get('body', '')
        prompt_name = draft.get('id', 'unknown')
        prompt_version = draft.get('version', '0.1.0')
    else:
        prompt_text = f.read()
        prompt_name = os.path.basename(draft_file)
        prompt_version = "0.1.0"

print(f"# Evaluation Report for {prompt_name}@{prompt_version}\n")
print("## Setup\n- **Directive:** strategiai_directive.md\n- **Models Tested:** Simulated run\n")
print("## Results\nSimulated eval completed successfully.\n")
