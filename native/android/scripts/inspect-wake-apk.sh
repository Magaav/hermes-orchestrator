#!/usr/bin/env bash
set -euo pipefail

apk="${1:-native/android/app/build/outputs/apk/debug/app-debug.apk}"
expect_model="${2:---expect-no-model}"
expect_vosk="${3:---expect-no-vosk-model}"

if [[ ! -f "$apk" ]]; then
  echo "APK not found: $apk" >&2
  exit 2
fi

if [[ "$expect_model" != "--expect-model" && "$expect_model" != "--expect-base-model" && "$expect_model" != "--expect-no-model" ]]; then
  echo "Usage: $0 <apk> [--expect-model|--expect-base-model|--expect-no-model] [--expect-vosk-model|--expect-no-vosk-model]" >&2
  exit 2
fi

if [[ "$expect_vosk" != "--expect-vosk-model" && "$expect_vosk" != "--expect-no-vosk-model" ]]; then
  echo "Usage: $0 <apk> [--expect-model|--expect-base-model|--expect-no-model] [--expect-vosk-model|--expect-no-vosk-model]" >&2
  exit 2
fi

entries="$(zipinfo -1 "$apk")"

require_entry() {
  local pattern="$1"
  local label="$2"
  if ! grep -Eq "$pattern" <<<"$entries"; then
    echo "Missing required APK entry: $label" >&2
    exit 1
  fi
}

forbid_entry() {
  local pattern="$1"
  local label="$2"
  if grep -Eq "$pattern" <<<"$entries"; then
    echo "Forbidden APK entry present: $label" >&2
    exit 1
  fi
}

require_entry '^lib/arm64-v8a/libonnxruntime\.so$' 'ONNX Runtime arm64-v8a native lib'
require_entry '^lib/armeabi-v7a/libonnxruntime\.so$' 'ONNX Runtime armeabi-v7a native lib'
require_entry '^lib/x86/libonnxruntime\.so$' 'ONNX Runtime x86 native lib'
require_entry '^lib/x86_64/libonnxruntime\.so$' 'ONNX Runtime x86_64 native lib'
require_entry '^lib/arm64-v8a/libvosk\.so$' 'Vosk arm64-v8a native lib'
require_entry '^lib/armeabi-v7a/libvosk\.so$' 'Vosk armeabi-v7a native lib'
require_entry '^lib/x86/libvosk\.so$' 'Vosk x86 native lib'
require_entry '^lib/x86_64/libvosk\.so$' 'Vosk x86_64 native lib'
require_entry '^assets/voice/README\.md$' 'assets/voice/README.md model contract'

if [[ "$expect_model" == "--expect-model" ]]; then
  require_entry '^assets/voice/hermes\.onnx$' 'assets/voice/hermes.onnx'
  if unzip -p "$apk" assets/voice/hermes.onnx | strings | grep -Eq 'NON_PRODUCTION|hermes-test-only|hermes-dev-fixture'; then
    echo "Forbidden non-production wake fixture marker present inside assets/voice/hermes.onnx" >&2
    exit 1
  fi
elif [[ "$expect_model" == "--expect-base-model" ]]; then
  require_entry '^assets/voice/base_hermes\.onnx$' 'assets/voice/base_hermes.onnx'
  forbid_entry '^assets/voice/hermes\.onnx$' 'assets/voice/hermes.onnx when expecting base_hermes.onnx'
else
  forbid_entry '^assets/voice/hermes\.onnx$' 'assets/voice/hermes.onnx in dev/no-model build'
  forbid_entry '^assets/voice/base_hermes\.onnx$' 'assets/voice/base_hermes.onnx in dev/no-model build'
fi

if [[ "$expect_vosk" == "--expect-vosk-model" ]]; then
  require_entry '^assets/asr/vosk-model/.+' 'assets/asr/vosk-model'
else
  forbid_entry '^assets/asr/vosk-model/.+' 'assets/asr/vosk-model in no-vosk-model build'
fi

echo "Wake APK inspection passed: $apk ($expect_model, $expect_vosk)"
