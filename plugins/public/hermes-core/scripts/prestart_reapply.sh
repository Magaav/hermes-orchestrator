#!/usr/bin/env bash
set -euo pipefail

# Deprecated compatibility shim.
# Canonical prestart pipeline moved to:
#   /local/plugins/public/native/scripts/prestart_reapply.sh
TARGET="/local/plugins/public/native/scripts/prestart_reapply.sh"
if [[ -x "$TARGET" ]]; then
  exec "$TARGET" "$@"
fi

echo "[error] prestart script not found: $TARGET" >&2
exit 1
