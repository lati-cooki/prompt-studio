#!/bin/bash
if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Usage: ./execute_with_jules.sh <registry_id> <task>"
else
    REGISTRY_ID="$1"
    TASK="$2"

    echo "Extracting prompt $REGISTRY_ID from registry..."
    # Mock extraction
    echo "Feeding prompt to Jules for task: $TASK"
    # jules new "$TASK"
fi
