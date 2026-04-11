#!/usr/bin/env bash
set -euo pipefail

# Backward-compatible shim.
# Canonical path: /local/scripts/backup/backup_nodes_to_gdrive.sh
exec /local/scripts/backup/backup_nodes_to_gdrive.sh "$@"
