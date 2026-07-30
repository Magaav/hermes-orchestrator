#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$ROOT/backend/bin/visao"

if [ ! -x "$BIN" ]; then
  echo "start: missing backend/bin/visao; run make build first" >&2
  exit 1
fi
exec "$BIN" -env "$ROOT/app.env"
