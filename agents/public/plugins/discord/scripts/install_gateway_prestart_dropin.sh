#!/usr/bin/env bash
set -euo pipefail

DROPIN_DIR="/etc/systemd/system/hermes-gateway.service.d"
DROPIN_FILE="$DROPIN_DIR/10-colmeio-prestart.conf"
PRESTART_SCRIPT="/local/plugins/hermes-core/scripts/prestart_reapply.sh"
if [[ ! -x "$PRESTART_SCRIPT" && -x "/local/plugins/discord/scripts/prestart_reapply.sh" ]]; then
  PRESTART_SCRIPT="/local/plugins/discord/scripts/prestart_reapply.sh"
fi
if [[ ! -x "$PRESTART_SCRIPT" && -x "/local/workspace/discord/scripts/prestart_reapply.sh" ]]; then
  PRESTART_SCRIPT="/local/workspace/discord/scripts/prestart_reapply.sh"
fi

if [[ ! -x "$PRESTART_SCRIPT" ]]; then
  echo "[error] prestart script missing or not executable: $PRESTART_SCRIPT" >&2
  exit 1
fi

sudo mkdir -p "$DROPIN_DIR"
sudo tee "$DROPIN_FILE" >/dev/null <<EOF
[Service]
ExecStartPre=/bin/bash -lc '${PRESTART_SCRIPT}'
EOF

sudo systemctl daemon-reload
sudo systemctl restart hermes-gateway.service

echo "[ok] Installed systemd drop-in: $DROPIN_FILE"
echo "[ok] Gateway restarted with deterministic prestart patching."
