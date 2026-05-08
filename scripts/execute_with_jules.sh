#!/bin/bash

# scripts/execute_with_jules.sh <prompt_id> <task_description>
# Uses a registered prompt to solve a specific task using Jules.

PROMPT_ID=$1
TASK=$2

if [ -z "$PROMPT_ID" ] || [ -z "$TASK" ]; then
  echo "Usage: ./execute_with_jules.sh <prompt_id> <task_description>"
  exit 1
fi

# Ensure we're in the right directory or know where registry is
# Assuming run from prompt-studio root
if [ ! -d "registry" ]; then
  echo "Error: registry directory not found. Please run from prompt-studio root."
  exit 1
fi

# Find the latest version in INDEX.json
# Prioritizes status=production, then active, then draft
PROMPT_FILE=$(python3 -c "
import json, sys
try:
    with open('registry/INDEX.json', 'r') as f:
        index = json.load(f)
    
    # Define priority
    priority = {'production': 0, 'active': 1, 'draft': 2, 'deprecated': 3}
    
    matches = [p for p in index['prompts'] if p['id'] == '$PROMPT_ID']
    if not matches:
        sys.exit(0)
        
    # Sort by priority and then by version (naive semver sort)
    matches.sort(key=lambda x: (priority.get(x['status'], 99), x['version']), reverse=False)
    
    print(matches[0]['file'])
except Exception as e:
    sys.stderr.write(str(e) + '\n')
    sys.exit(1)
")

if [ -z "$PROMPT_FILE" ]; then
  echo "Error: Prompt ID '$PROMPT_ID' not found in registry."
  exit 1
fi

PROMPT_PATH="registry/$PROMPT_FILE"

if [ ! -f "$PROMPT_PATH" ]; then
  echo "Error: Prompt file '$PROMPT_PATH' not found."
  exit 1
fi

echo "[*] Using prompt: $PROMPT_ID (from $PROMPT_FILE)"
echo "[*] Task: $TASK"

# Prepare the context
# We use a temporary file to hold the combined system instruction and task
CONTEXT_FILE=$(mktemp /tmp/jules_context.XXXXXX)

cat <<EOF > "$CONTEXT_FILE"
You are acting as an autonomous executor using the following registered prompt as your core logic.

# REGISTERED PROTOCOL
$(cat "$PROMPT_PATH")

# YOUR TASK
$TASK

Execute the protocol faithfully and provide the output as specified.
EOF

# Check for Jules
if command -v jules &> /dev/null; then
  echo "[+] Handing off to Jules..."
  jules new "$(cat "$CONTEXT_FILE")"
else
  # Fallback: if we are Gemini CLI, we might be able to invoke ourselves or just output the context
  echo "[!] 'jules' command not found."
  echo "[?] To run this with Gemini CLI, you can copy the context below:"
  echo "--------------------------------------------------------------------------------"
  cat "$CONTEXT_FILE"
  echo "--------------------------------------------------------------------------------"
fi

rm "$CONTEXT_FILE"
