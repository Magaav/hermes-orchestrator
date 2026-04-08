#!/usr/bin/env bash
# Compatibility alias: hord -> horc
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/horc.sh" "$@"
