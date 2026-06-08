#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:-all}"
image="${WASM_AGENT_ANDROID_DOCKER_IMAGE:-cimg/android:2024.11}"
platform="${WASM_AGENT_ANDROID_DOCKER_PLATFORM:-linux/amd64}"
cache_mode="${WASM_AGENT_ANDROID_DOCKER_GRADLE_CACHE:-clean}"
gradle_home="/tmp/wasm-agent-gradle-home"

usage() {
  cat <<'USAGE'
Usage: tools/android-build-docker.sh [debug|test|all]

Modes:
  debug  process resources, compile Kotlin, assemble debug APK
  test   run debug unit tests
  all    run clean, resources, Kotlin compile, unit tests, assemble debug APK

Environment:
  WASM_AGENT_ANDROID_DOCKER_IMAGE=cimg/android:2024.11
  WASM_AGENT_ANDROID_DOCKER_PLATFORM=linux/amd64
  WASM_AGENT_ANDROID_DOCKER_GRADLE_CACHE=clean|volume

The default cache mode is clean to avoid reusing host-architecture Gradle native
state. Set WASM_AGENT_ANDROID_DOCKER_GRADLE_CACHE=volume to reuse the Docker
volume wasm-agent-android-gradle-cache.
USAGE
}

case "$mode" in
  debug|test|all) ;;
  -h|--help|help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

if ! command -v docker >/dev/null 2>&1; then
  echo "error: Docker is not installed or not on PATH" >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "error: Docker is not available to this user/session" >&2
  exit 1
fi

docker_args=(
  run
  --rm
  --platform "$platform"
  -v "$repo_root:/work"
  -w /work/native/android
)

if [[ "$cache_mode" == "volume" ]]; then
  docker_args+=(-v wasm-agent-android-gradle-cache:/tmp/wasm-agent-gradle-home)
elif [[ "$cache_mode" != "clean" ]]; then
  echo "error: unsupported WASM_AGENT_ANDROID_DOCKER_GRADLE_CACHE=$cache_mode" >&2
  exit 2
fi

case "$mode" in
  debug)
    gradle_tasks=(
      ":app:processDebugResources"
      ":app:compileDebugKotlin"
      ":app:assembleDebug"
    )
    ;;
  test)
    gradle_tasks=(
      ":app:testDebugUnitTest"
    )
    ;;
  all)
    gradle_tasks=(
      "clean"
      ":app:processDebugResources"
      ":app:compileDebugKotlin"
      ":app:testDebugUnitTest"
      ":app:assembleDebug"
    )
    ;;
esac

printf 'Android Docker image: %s\n' "$image"
printf 'Android Docker platform: %s\n' "$platform"
printf 'Android Gradle cache mode: %s\n' "$cache_mode"
printf 'Gradle tasks:'
printf ' %q' "${gradle_tasks[@]}"
printf '\n'

docker "${docker_args[@]}" "$image" bash -lc '
  set -euo pipefail
  export GRADLE_USER_HOME='"$gradle_home"'
  export GRADLE_OPTS="-Dorg.gradle.daemon=false -Dkotlin.compiler.execution.strategy=in-process"

  echo "Container architecture: $(uname -m)"
  java -version
  echo "ANDROID_HOME=${ANDROID_HOME:-}"
  echo "ANDROID_SDK_ROOT=${ANDROID_SDK_ROOT:-}"
  gradle --no-daemon --version
  gradle --no-daemon --stacktrace -Dkotlin.compiler.execution.strategy=in-process "$@"
' bash "${gradle_tasks[@]}"

echo "APK outputs:"
find "$repo_root/native/android/app/build/outputs/apk" -type f -name "*.apk" -print 2>/dev/null | sort || true
