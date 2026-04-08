#!/usr/bin/env bash
# Backward-compatible shim.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/clone/horc.sh" "$@"
