#!/bin/bash
echo "[MLX server — Qwen3-4B-Instruct-2507]"
source ~/mlx-env/bin/activate
exec mlx_lm.server \
  --model mlx-community/Qwen3-4B-Instruct-2507-4bit \
  --port 8091 \
  --allowed-origins "*"
