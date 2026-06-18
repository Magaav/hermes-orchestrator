#!/usr/bin/env bash
set -euo pipefail

package_name="${HERMES_ANDROID_PACKAGE:-com.colmeio.wasmagent}"
adb_bin="${ADB:-adb}"
serial="${ANDROID_SERIAL:-}"

adb_args=()
if [[ -n "$serial" ]]; then
  adb_args=(-s "$serial")
fi

run_adb() {
  "$adb_bin" "${adb_args[@]}" "$@"
}

if ! command -v "$adb_bin" >/dev/null 2>&1; then
  echo "adb not found. Set ADB=/path/to/adb or install Android platform-tools." >&2
  exit 127
fi

devices="$(run_adb devices | awk 'NR > 1 && $2 == "device" { print $1 }')"
if [[ -z "$serial" ]]; then
  device_count="$(printf '%s\n' "$devices" | sed '/^$/d' | wc -l | tr -d ' ')"
  if [[ "$device_count" == "0" ]]; then
    echo "No authorized Android device is connected." >&2
    exit 1
  fi
  if [[ "$device_count" != "1" ]]; then
    echo "Multiple Android devices are connected. Set ANDROID_SERIAL to choose one:" >&2
    printf '%s\n' "$devices" >&2
    exit 1
  fi
fi

run_adb shell "run-as $package_name sh -c 'rm -rf files/voice/hermes-dataset files/voice/exports/hermes-dataset.zip files/voice/exports && mkdir -p files/voice/hermes-dataset/positive files/voice/hermes-dataset/negative/noise files/voice/hermes-dataset/negative/silence files/voice/hermes-dataset/negative/speech files/voice/hermes-dataset/validation files/voice/exports'"

remaining="$(run_adb shell "run-as $package_name sh -c 'find files/voice/hermes-dataset files/voice/exports -type f 2>/dev/null | wc -l'" | tr -d '\r[:space:]')"
echo "Cleared Android Hermes wake cache for $package_name."
echo "Remaining cached dataset/export files: ${remaining:-unknown}"
