#!/bin/bash
echo "[ThreadHub server — :8110]"
cd ~/threadhub
exec node bin/cli.js serve --port 8110
