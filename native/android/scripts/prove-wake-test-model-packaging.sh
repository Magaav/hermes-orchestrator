#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$repo_root"

generated_model="native/android/build/generated/voice/hermes-test-only.onnx"
asset_model="native/android/app/src/main/assets/voice/hermes.onnx"
backup_model=""

if [[ -f "$asset_model" ]]; then
  backup_model="$(mktemp)"
  cp "$asset_model" "$backup_model"
fi

cleanup() {
  if [[ -n "$backup_model" && -f "$backup_model" ]]; then
    cp "$backup_model" "$asset_model"
    rm -f "$backup_model"
  else
    rm -f "$asset_model"
  fi
}
trap cleanup EXIT

native/android/scripts/generate-wake-test-onnx.py --output "$generated_model"
native/android/scripts/verify-wake-test-onnx.py --model "$generated_model"
native/android/scripts/install-wake-model.sh --model "$generated_model" --allow-test-model

ANDROID_HOME="${ANDROID_HOME:-$repo_root/native/android/.android-sdk}" \
GRADLE_USER_HOME="${GRADLE_USER_HOME:-$repo_root/native/android/.gradle-home}" \
QEMU_LD_PREFIX="${QEMU_LD_PREFIX:-$repo_root/native/android/.android-sdk-qemu-root}" \
"$repo_root/native/android/.gradle-dist/gradle-8.9/bin/gradle" \
  -p "$repo_root/native/android" :app:assembleDebug --info --stacktrace --no-daemon

native/android/scripts/inspect-wake-apk.sh native/android/app/build/outputs/apk/debug/app-debug.apk --expect-model

echo "Explicit test-model packaging proof passed. Restoring asset tree to prior state."
