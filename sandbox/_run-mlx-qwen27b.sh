#!/bin/bash
echo "[MLX server — Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2-4bit]"
source ~/mlx-env/bin/activate
exec mlx_lm.server \
  --model ~/.lmstudio/models/Jackrong/MLX-Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2-4bit \
  --port 8092 \
  --allowed-origins "*"
