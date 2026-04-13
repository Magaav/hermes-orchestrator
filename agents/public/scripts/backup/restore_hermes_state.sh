#!/usr/bin/env bash
set -euo pipefail

# Compatibility wrapper.
# Canonical path: /local/agents/private/scripts/backup/restore_hermes_state.sh
exec /local/agents/private/scripts/backup/restore_hermes_state.sh "$@"
