#!/usr/bin/env bash
set -euo pipefail

# Compatibility wrapper.
# Canonical path: /local/agents/private/scripts/backup/backup_nodes_to_gdrive.sh
exec /local/agents/private/scripts/backup/backup_nodes_to_gdrive.sh "$@"
