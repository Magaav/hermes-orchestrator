#!/usr/bin/env bash
set -euo pipefail

DOCTOR="${OPENVIKING_DOCTOR_SCRIPT:-/local/scripts/tests/openviking_doctor.py}"
if [[ ! -x "$DOCTOR" ]]; then
  echo "doctor script not executable: $DOCTOR" >&2
  exit 1
fi

python3 "$DOCTOR" "$@"
