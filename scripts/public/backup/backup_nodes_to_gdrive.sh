#!/usr/bin/env bash
set -euo pipefail

# Compatibility wrapper.
# Canonical path: /local/scripts/private/backup/backup_nodes_to_gdrive.sh
exec /local/scripts/private/backup/backup_nodes_to_gdrive.sh "$@"
