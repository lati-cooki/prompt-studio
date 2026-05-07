#!/bin/bash
echo "[MLX server]"
source ~/mlx-env/bin/activate
exec mlx_lm.server \
  --model mlx-community/gemma-4-26B-A4B-it-4bit \
  --port 8080 \
  --allowed-origins "*"
