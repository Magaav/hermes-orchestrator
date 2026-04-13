#!/usr/bin/env bash
set -euo pipefail

# Compatibility shim.
# Canonical prestart pipeline moved to:
#   /local/plugins/hermes-core/scripts/prestart_reapply.sh
TARGET="/local/plugins/hermes-core/scripts/prestart_reapply.sh"
if [[ -x "$TARGET" ]]; then
  exec "$TARGET" "$@"
fi

# Legacy fallback for older clone/workspace layouts.
LEGACY="/local/workspace/discord/scripts/prestart_reapply.sh"
if [[ -x "$LEGACY" ]]; then
  exec "$LEGACY" "$@"
fi

echo "[error] prestart script not found: $TARGET" >&2
exit 1
