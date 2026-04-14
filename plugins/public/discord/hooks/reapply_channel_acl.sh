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
#   Copy public hook code from:
#     /local/plugins/public/discord/hooks/channel_acl/
#   and private runtime config from:
#     /local/plugins/private/discord/hooks/channel_acl/config.yaml
#   to:
#     ~/.hermes/hooks/channel_acl/
#
# USAGE:
#   bash /local/plugins/public/discord/hooks/reapply_channel_acl.sh
#
# AUTORUN:
#   - Via BOOT.md (LLM agent, not shell; use reapply_channel_acl.py for that)
#   - Via cron: add @reboot or run manually after agent updates
# ============================================================

set -e

PUBLIC_SOURCE="/local/plugins/public/discord/hooks/channel_acl"
PRIVATE_CONFIG="/local/plugins/private/discord/hooks/channel_acl/config.yaml"
DEST="$HOME/.hermes/hooks/channel_acl"

echo "[reapply] Channel ACL Hook"
echo "[reapply] Public source:  $PUBLIC_SOURCE"
echo "[reapply] Private config: $PRIVATE_CONFIG"
echo "[reapply] Destination: $DEST"

if [ ! -d "$PUBLIC_SOURCE" ]; then
    echo "[ERROR] Public source directory not found: $PUBLIC_SOURCE"
    exit 1
fi

if [ ! -f "$PRIVATE_CONFIG" ]; then
    echo "[ERROR] Private config not found: $PRIVATE_CONFIG"
    exit 1
fi

mkdir -p "$DEST"

for file in handler.py HOOK.yaml; do
    src="$PUBLIC_SOURCE/$file"
    dst="$DEST/$file"
    if [ -f "$src" ]; then
        cp "$src" "$dst"
        echo "  [OK] $file"
    else
        echo "  [ERROR] required file not found in public source: $src"
        exit 1
    fi
done

cp "$PRIVATE_CONFIG" "$DEST/config.yaml"
echo "  [OK] config.yaml"

echo "[reapply] Done. Hook applied successfully."
