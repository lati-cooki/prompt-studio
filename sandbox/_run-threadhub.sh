#!/bin/bash
echo "[ThreadHub server — :8110]"
CANONICAL=~/Projects/clista/packages/threadhub
STALE=~/threadhub
if [ -d "$CANONICAL" ]; then
  cd "$CANONICAL"
elif [ -d "$STALE" ]; then
  echo "WARNING: canonical checkout $CANONICAL missing — falling back to STALE CHECKOUT $STALE"
  echo "         (ThreadHub moved to the lati-cooki/clista monorepo 2026-07-10; this copy will drift.)"
  cd "$STALE"
else
  echo "ERROR: no ThreadHub checkout found ($CANONICAL or $STALE). Seal/promotion flows will fail." >&2
  exit 1
fi
exec node bin/cli.js serve --port 8110
