#!/bin/sh
set -eu

mode="${1:-shell}"
if [ "$mode" = "seed" ]; then
  if [ ! -f /lab-seed/local-seed.tar ]; then
    echo "safe_lab_seed_missing" >&2
    exit 20
  fi
  if [ "$(find /local -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    echo "safe_lab_local_not_empty" >&2
    exit 21
  fi
  tar -xf /lab-seed/local-seed.tar -C /local
  git -C /local init --initial-branch=lab-baseline >/dev/null
  git -C /local config user.name "WASM Agent Safe Lab"
  git -C /local config user.email "safe-lab@invalid.local"
  git -C /local add -A
  git -C /local commit -m "safe-lab baseline" >/dev/null
  git -C /local remote remove origin 2>/dev/null || true
  printf '%s\n' "safe_lab_seed_complete"
  exit 0
fi
if [ "$mode" = "canary" ]; then
  exec /usr/local/bin/containment-canary
fi
if [ "$mode" = "frontier" ]; then
  test -f /local/plugins/wasm-agent/server/static_server.py || {
    echo "safe_lab_not_seeded" >&2
    exit 22
  }
  exec python3 /local/plugins/wasm-agent/server/static_server.py --host 127.0.0.1 --port 8877
fi
shift || true
exec "$mode" "$@"
