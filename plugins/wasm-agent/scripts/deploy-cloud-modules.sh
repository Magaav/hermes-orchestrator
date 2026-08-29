#!/usr/bin/env bash
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PLUGIN_ROOT}"

node scripts/generate-module-release.mjs
node scripts/generate-module-release.mjs --check
systemctl --user restart wasm-agent-production.service
systemctl --user is-active --quiet wasm-agent-production.service
