#!/usr/bin/env bash
# Backward-compatible clone wrapper.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/horc.sh" "$@"
