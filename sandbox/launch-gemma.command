#!/bin/bash
# Launches: Gemma 26B (8080) + web (7777) + vault (8100)

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

free_port() {
  local port=$1
  local pids
  pids=$(lsof -ti :"$port" 2>/dev/null) || true
  [ -z "$pids" ] && return 0
  echo "Freeing port $port (killing $pids)"
  kill $pids 2>/dev/null || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    sleep 0.3
    pids=$(lsof -ti :"$port" 2>/dev/null) || true
    [ -z "$pids" ] && return 0
  done
  echo "Port $port still held, SIGKILL"
  kill -9 $pids 2>/dev/null || true
  sleep 0.5
}
free_port 7777
free_port 8080
free_port 8100

osascript <<EOF
tell application "Terminal"
    activate
    do script "bash '$DIR/_run-mlx.sh'"
    do script "bash '$DIR/_run-web.sh'"
    do script "bash '$DIR/_run-vault.sh'"
end tell
EOF

echo "Waiting for web server..."
for i in {1..30}; do
  curl -sf http://localhost:7777/ >/dev/null 2>&1 && break
  sleep 0.5
done

echo "Waiting for MLX Gemma (model may need to load)..."
for i in {1..180}; do
  curl -sf http://localhost:8080/v1/models >/dev/null 2>&1 && break
  sleep 1
done

echo "Waiting for vault search (embedder loading)..."
for i in {1..120}; do
  curl -sf http://localhost:8100/health >/dev/null 2>&1 && break
  sleep 1
done

open "http://localhost:7777"
echo "Launched. You can close this window."
