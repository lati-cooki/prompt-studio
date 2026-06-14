#!/bin/bash
echo "[ThreadHub server — :8110]"
[ -d ~/threadhub ] || { echo "ThreadHub not found at ~/threadhub — skipping."; exit 0; }
cd ~/threadhub
exec node bin/cli.js serve --port 8110
