#!/usr/bin/env bash
set -euo pipefail

# Compatibility wrapper.
# Canonical path: /local/scripts/private/backup/restore_hermes_state.sh
exec /local/scripts/private/backup/restore_hermes_state.sh "$@"
