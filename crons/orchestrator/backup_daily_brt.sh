#!/usr/bin/env bash
set -euo pipefail

# Daily backup policy (00:00 America/Sao_Paulo):
# - Keep only the latest 3 archives under /local/backups
# - Prune old request_dump_* files before archiving
export NODE_TIME_ZONE="${NODE_TIME_ZONE:-America/Sao_Paulo}"
export HERMES_TIMEZONE="${HERMES_TIMEZONE:-${NODE_TIME_ZONE}}"
export TZ="${TZ:-${HERMES_TIMEZONE}}"
export HERMES_BACKUP_KEEP_LAST="${HERMES_BACKUP_KEEP_LAST:-3}"
export HERMES_REQUEST_DUMP_KEEP_DAYS="${HERMES_REQUEST_DUMP_KEEP_DAYS:-14}"
export HERMES_REQUEST_DUMP_KEEP_LAST="${HERMES_REQUEST_DUMP_KEEP_LAST:-200}"

/local/scripts/public/clone/horc.sh backup all
