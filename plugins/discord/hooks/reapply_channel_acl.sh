#!/bin/bash
# ============================================================
# Reapply Channel ACL Hook - survives hermes-agent updates
# ============================================================
#
# PROBLEM:
#   hermes-agent (/home/ubuntu/.hermes/hermes-agent/) is updated via
#   git pull / pip install and can overwrite run.py.
#   run.py imports channel_acl from ~/.hermes/hooks/channel_acl/.
#   That directory is outside the agent source tree, so it survives updates.
#
#   WARNING: if ~/.hermes/hooks/channel_acl/ is deleted, or if run.py changes
#   the import path, the hook stops working.
#
# SOLUTION:
#   Copy custom hook files from:
#     /local/workspace/discord/hooks/channel_acl/
#   to:
#     ~/.hermes/hooks/channel_acl/
#
# USAGE:
#   bash /local/workspace/discord/hooks/reapply_channel_acl.sh
#
# AUTORUN:
#   - Via BOOT.md (LLM agent, not shell; use reapply_channel_acl.py for that)
#   - Via cron: add @reboot or run manually after agent updates
# ============================================================

set -e

SOURCE="/local/workspace/discord/hooks/channel_acl"
DEST="$HOME/.hermes/hooks/channel_acl"

echo "[reapply] Channel ACL Hook"
echo "[reapply] Source:      $SOURCE"
echo "[reapply] Destination: $DEST"

if [ ! -d "$SOURCE" ]; then
    echo "[ERROR] Source directory not found: $SOURCE"
    exit 1
fi

mkdir -p "$DEST"

for file in handler.py config.yaml HOOK.yaml; do
    src="$SOURCE/$file"
    dst="$DEST/$file"
    if [ -f "$src" ]; then
        cp "$src" "$dst"
        echo "  [OK] $file"
    else
        echo "  [WARN] $file not found in source, skipping"
    fi
done

echo "[reapply] Done. Hook applied successfully."
