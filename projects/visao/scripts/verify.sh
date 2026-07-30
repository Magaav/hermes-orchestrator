#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT/frontend"
npm run typecheck
npm run test

cd "$ROOT/backend"
go test ./...

cd "$ROOT"
python3 -m unittest backend/studio_codex_test.py backend/studio_master_frontier_test.py backend/studio_worker_test.py

test -f "$ROOT/frontend/dist/index.html"
test -f "$ROOT/frontend/dist/ui-build.json"
grep -q 'mvp-v1' "$ROOT/frontend/dist/ui-build.json"
echo "verify: static and unit checks passed"
