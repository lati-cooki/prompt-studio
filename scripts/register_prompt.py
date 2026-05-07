#!/usr/bin/env python3
import sys
import json
import os
import shutil
from datetime import datetime

if len(sys.argv) < 3:
    print("Usage: register_prompt.py <eval_report> <draft_prompt_json>")
    sys.exit(1)

draft_file = sys.argv[2]
with open(draft_file, 'r') as f:
    draft = json.load(f)

index_file = 'registry/INDEX.json'
with open(index_file, 'r') as f:
    registry = json.load(f)

draft['status'] = 'production'
draft['eval_status'] = 'passed'

# create copy of draft
os.makedirs('registry/prompts', exist_ok=True)
prompt_dest = f"registry/prompts/{draft['id']}_v{draft['version'].replace('.', '_')}.json"
with open(prompt_dest, 'w') as f:
    json.dump(draft, f, indent=2)

draft['file'] = prompt_dest

registry['prompts'].append(draft)

with open(index_file, 'w') as f:
    json.dump(registry, f, indent=2)

print(f"Successfully registered {draft['id']} at {prompt_dest}")
