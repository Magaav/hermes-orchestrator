#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  npm install
fi
npm run build

cd "$ROOT/backend"
mkdir -p bin
go build -ldflags "-X main.buildID=mvp-v1" -o "$ROOT/backend/bin/visao" ./cmd/server
echo "build: ok"
