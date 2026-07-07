#!/usr/bin/env bash
# horc — Hermes Orchestrator CLI wrapper

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_MANAGER="${SCRIPT_DIR}/clone_manager.py"
HERMES_CLONE_MANAGER_SCRIPT="${HERMES_CLONE_MANAGER_SCRIPT:-${DEFAULT_MANAGER}}"
DEFAULT_NODE="${HERMES_DEFAULT_NODE:-orchestrator}"

if [[ ! -f "${HERMES_CLONE_MANAGER_SCRIPT}" ]]; then
  for path in \
    "/local/scripts/public/clone/clone_manager.py" \
    "/local/hermes-orchestrator/scripts/clone/clone_manager.py" \
    "$HOME/.hermes/hermes-agent/scripts/clone/clone_manager.py"; do
    if [[ -f "${path}" ]]; then
      HERMES_CLONE_MANAGER_SCRIPT="${path}"
      break
    fi
  done
fi

if [[ ! -f "${HERMES_CLONE_MANAGER_SCRIPT}" ]]; then
  echo "horc: clone_manager.py not found" >&2
  echo "set HERMES_CLONE_MANAGER_SCRIPT to override" >&2
  exit 1
fi

if [[ -n "${HERMES_CLONE_PYTHON_BIN:-}" && -x "${HERMES_CLONE_PYTHON_BIN}" ]]; then
  PYTHON_BIN="${HERMES_CLONE_PYTHON_BIN}"
elif [[ -x "/local/hermes-agent/.venv/bin/python3" ]]; then
  PYTHON_BIN="/local/hermes-agent/.venv/bin/python3"
else
  PYTHON_BIN="$(command -v python3 || command -v python || true)"
fi

if [[ -z "${PYTHON_BIN:-}" ]]; then
  echo "horc: python runtime not found" >&2
  exit 1
fi

manager() {
  "${PYTHON_BIN}" "${HERMES_CLONE_MANAGER_SCRIPT}" "$@"
}

exec_manager() {
  exec "${PYTHON_BIN}" "${HERMES_CLONE_MANAGER_SCRIPT}" "$@"
}

usage() {
  cat <<'TXT'
horc — Hermes Orchestrator CLI

Usage:
  horc start [name] [--image IMAGE]
  horc status [name]
  horc stop [name]
  horc restart [all|name] [--image IMAGE]
  horc delete [name] [--yes]
  horc purge-node <name>
  horc purge-node confirm <request-id> --token TOKEN
  horc logs [name] [--lines N]
  horc logs clean [name|all]
  horc backup all
  horc backup node <name>
  horc backup <name>
  horc restore <path>
  horc update [help]
  horc update all [--force]
  horc update node <name> [--force]
  horc build win
  horc build win-fast
  horc build android
  horc build android-fast
  horc build all
  horc simulate web [--avatar-quest]
  horc simulate android [--device|--emulator|--local-report PATH|--voice-wake FIXTURE]
  horc simulate windows
  horc simulate all
  horc space start
  horc space stop
  horc space restart
  horc space status
  horc space backup

Examples:
  horc start
  horc restart
  horc restart orchestrator
  horc start node1
  horc logs node1 --lines 120
  horc logs clean
  horc logs clean node1
  horc purge-node node1
  horc purge-node confirm purge-node1-20260418T150000Z-abc123 --token deadbeefcafebabe
  horc backup all
  horc backup node node1
  horc restore /local/backups/horc-backup-node-node1-20260101T000000Z.tar.gz
  horc update help
  horc update all
  horc update all --force
  horc update node orchestrator
  horc update node colmeio --force
  horc build win
  horc build win-fast
  horc simulate web
  horc simulate web --avatar-quest
  horc simulate all
  horc space start
  horc space stop
  horc space restart
  horc space backup

Notes:
  - For start/status/stop/delete/logs, if name is omitted, 'orchestrator' is used.
  - 'delete' removes the container plus /local/agents/envs/<name>.env and /local/agents/nodes/<name>/ after confirmation.
  - 'purge-node' is destructive and always requires an explicit second confirmation step.
  - For restart, omitted name means "restart all nodes".
  - `horc update all` refreshes /local/hermes-agent and reseeds every node.
  - `horc update node <name>` refreshes /local/hermes-agent and reseeds only that node.
  - Add `--force` to discard local `/local/hermes-agent` checkout changes during the refresh.
  - `horc build win` creates the Windows wasm-agent native installer and writes a trust manifest.
  - `horc build win-fast` runs Windows native source/package checks without
    creating a trusted installer or release feed.
  - `horc build android` creates Android APK artifacts for Go Native.
  - `horc simulate web` runs Playwright browser/PWA runtime evidence and writes reports/sim/web/latest/.
  - `horc simulate web --avatar-quest` submits a real avatar-chat quest through the UI and writes reports/sim/avatar-quest/latest/.
  - `horc simulate android --device` installs and drives the real APK on a connected USB/ADB device.
  - `horc simulate android --emulator` attempts cloud host/Docker emulator setup and reports exact blockers.
  - `horc simulate android --local-report PATH` validates a copied real-device report from another machine.
  - `horc simulate all` runs web, runs Android when adb has a usable device, and leaves Windows pending until implemented.
  - Backups are written under /local/backups.
  - Restore accepts either an absolute path or a filename under /local/backups.
  - `horc space start` starts wasm-agent on localhost:8877 and its Hermes bridge on localhost:8790.
  - `horc space restart` stops then starts the wasm-agent workspace.
  - `horc space backup` archives wasm-agent private app state without source/caches/logs.
  - Compatibility alias: 'hord' runs the same commands as 'horc'.
TXT
}

update_usage() {
  cat <<'TXT'
horc update — Simplified Hermes fleet update

Usage:
  horc update [help]
  horc update all [--force]
  horc update node <name> [--force]

Examples:
  horc update help
  horc update all
  horc update all --force
  horc update node orchestrator
  horc update node colmeio --force

Behavior:
  - Refreshes /local/hermes-agent from the configured upstream repo/branch.
  - `all` forces a safe reseed on every node.
  - `node <name>` forces a safe reseed only on the named node.
  - `--force` discards local `/local/hermes-agent` checkout changes before mirroring upstream.
  - Registry metadata is reconciled at /local/agents/registry.json.
TXT
}

simulate_usage() {
  cat <<'TXT'
horc simulate — WASM Agent runtime simulators

Usage:
  horc simulate web
  horc simulate android [--device|--emulator|--local-report PATH|--voice-wake FIXTURE]
  horc simulate windows
  horc simulate all

Behavior:
  - `web` uses Playwright to verify PWA/browser behavior only.
  - `web` defaults to http://127.0.0.1:8877/home when reachable.
  - Set WASM_AGENT_SIM_URL to override the web target.
  - Web simulation adds native=android&shell=android-webview&buildId=playwright-sim.
  - `android --device` installs and drives the real APK with ADB + UIAutomator on a physical device.
  - `android --emulator` tries host emulator support, Android SDK/AVD setup, then Docker emulator viability.
  - `android --local-report PATH` validates a copied/uploaded report from a local USB phone.
  - `android --voice-wake fixture-hermes-command.wav` verifies Hermes native voice wake fixture evidence.
  - `windows` is a pending skeleton for Playwright Electron + Windows smoke/PowerShell scripts.
  - `all` runs implemented simulators and reports pending ones.
  - Build success is not runtime verification.
  - Full Android OAuth proof requires post-authorization native return plus authenticated WebView evidence.

Reports:
  reports/sim/<platform>/latest/result.json
  reports/sim/<platform>/latest/summary.md
TXT
}

build_usage() {
  cat <<'TXT'
horc build — Release artifacts

Usage:
  horc build win
  horc build win-fast
  horc build android
  horc build android-fast
  horc build all
  horc build prepare-docker
  horc build doctor
  horc build --doctor

Behavior:
  - `horc build win` builds the Windows 11 x64 wasm-agent Electron/NSIS installer.
  - `horc build win-fast` runs Windows native source/package checks for the
    inner loop. It does not build or verify the final NSIS installer, does not
    publish a native release feed, and is not installed-app proof.
  - `horc build android` builds the Android sideload APK lane only.
  - `horc build android-fast` builds a debug APK for fast iteration only; it
    does not sign, promote, verify, or publish native release feed artifacts.
  - `horc build all` builds Windows and Android in parallel, then publishes the combined feed.
  - Native Windows builds are production-trusted.
  - Android release builds are cloud-only, signed for sideload install, and
    promoted to native/android/release/WASM-Agent-{arm64,universal}.apk.
  - Linux x86_64 builds use Wine/NSIS directly and require a Windows smoke test.
  - Linux aarch64 builds use a Docker linux/amd64 Wine builder by default and
    require a Windows smoke test.

Environment:
  HORC_WIN_BUILD_MODE=auto|native|wine|docker|arm64-fast  default: auto
  HORC_ALLOW_CROSS_WIN_BUILD=1                 allow Linux aarch64 direct Wine
  HORC_WIN_BUILD_MODE=arm64-fast               Linux ARM64 direct NSIS/no-rcedit proof lane
  HORC_TARGET_WIN_ARCH=x64                     default: x64
  HORC_REQUIRE_VERIFIED_INSTALLER=1            default: 1
  HORC_DOCKER_IMAGE=electronuserland/builder:wine
  HORC_PREPARED_DOCKER_IMAGE=horc/electron-builder-wine-nsis:jammy
  HORC_DOCKER_AMD64_PROBE_IMAGE=alpine:3.20
  HORC_FORCE_NPM_CI=1                          force Windows Docker npm reinstall
  HORC_WIN_FAST_TASKS="test:windows-hot-ops test:android-connection-parser pack:win:x64"
                                                 override Windows fast npm tasks
  HORC_WIN_FAST_PACK=0                         skip electron-builder dir package in win-fast
  HORC_WIN_FAST_RESOURCE_EDIT=1                opt into Wine rcedit during Linux ARM64 win-fast
  HORC_WIN_BUILD_BENCHMARK_LOG=/path.jsonl     override Windows build benchmark log
  HORC_AUTO_INSTALL_BINFMT=1                   default on Linux aarch64 auto/docker
  HORC_NO_AUTO_INSTALL_BINFMT=1                disable binfmt self-healing
  HORC_ANDROID_BUILD_MODE=auto|local|docker    default: auto
  HORC_ANDROID_DOCKER_IMAGE=ghcr.io/cirruslabs/android-sdk:35
  HORC_ANDROID_GRADLE_VERSION=8.9
  HORC_ANDROID_RUN_UNIT_TESTS=1                 run Android JVM tests before release assembly
  HORC_ANDROID_PRESERVE_BUILD_ID=1              keep caller-provided Android buildId/versionCode
  HORC_ANDROID_FAST_TASKS=":app:assembleDebug"  override fast-lane Gradle tasks
  HORC_ANDROID_GRADLE_DAEMON=1                  allow daemon in Android lanes
  HORC_ANDROID_CONFIGURATION_CACHE=1            enable Gradle configuration cache in Android lanes
  HORC_ANDROID_FAST_INSPECT_APK=0               skip fast APK wake asset inspection
  HORC_ANDROID_BUILD_BENCHMARK_LOG=/path.jsonl  override Android build benchmark log
  HORC_GENERATE_NATIVE_RELEASE_FEED=0           skip per-target feed generation
  WASM_AGENT_ANDROID_VOSK_MODEL_DIR=/path       optional Vosk model assets directory
  WASM_AGENT_ANDROID_APKSIGNER_TIMEOUT_MS=600000
  HERMES_WASM_AGENT_ANDROID_ROOT=/local/native/android
  GRADLE_BIN=/path/to/gradle                   optional Android Gradle override
  WASM_AGENT_ANDROID_KEYSTORE=/path/to/key.jks optional Android signing key
TXT
}

repo_root() {
  local root="${HERMES_ORCHESTRATOR_ROOT:-}"
  if [[ -n "${root}" ]]; then
    printf '%s\n' "${root}"
    return
  fi

  if [[ -d "${SCRIPT_DIR}/../../../native/windows/src" ]]; then
    (cd "${SCRIPT_DIR}/../../.." && pwd)
    return
  fi

  printf '%s\n' "/local"
}

host_kernel() {
  if [[ -n "${HORC_TEST_HOST_KERNEL:-}" ]]; then
    printf '%s\n' "${HORC_TEST_HOST_KERNEL}"
    return
  fi
  uname -s 2>/dev/null || printf 'unknown\n'
}

host_machine() {
  if [[ -n "${HORC_TEST_HOST_MACHINE:-}" ]]; then
    printf '%s\n' "${HORC_TEST_HOST_MACHINE}"
    return
  fi
  uname -m 2>/dev/null || printf 'unknown\n'
}

canonical_host_arch() {
  local arch
  arch="$(host_machine)"
  case "${arch}" in
    x86_64|amd64)
      printf '%s\n' "x86_64"
      ;;
    aarch64|arm64)
      printf '%s\n' "aarch64"
      ;;
    *)
      printf '%s\n' "${arch}"
      ;;
  esac
}

is_native_windows_shell() {
  if [[ "${OS:-}" == "Windows_NT" ]]; then
    return 0
  fi

  local kernel
  kernel="$(uname -s 2>/dev/null || true)"
  case "${kernel}" in
    CYGWIN*|MINGW*|MSYS*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

is_linux_shell() {
  [[ "$(host_kernel)" == "Linux" ]]
}

is_truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

is_falsey() {
  case "${1:-}" in
    0|false|FALSE|no|NO|off|OFF)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

build_fail() {
  echo "horc build: $*" >&2
  exit 2
}

release_build_lock() {
  if [[ -z "${HORC_BUILD_LOCK_DIR:-}" || ! -d "${HORC_BUILD_LOCK_DIR}" ]]; then
    return
  fi
  local pid_file="${HORC_BUILD_LOCK_DIR}/pid"
  local owner_pid="${HORC_BUILD_LOCK_OWNER_PID:-${BASHPID:-$$}}"
  if [[ -f "${pid_file}" && "$(cat "${pid_file}" 2>/dev/null || true)" == "${owner_pid}" ]]; then
    rm -rf "${HORC_BUILD_LOCK_DIR}"
  fi
  HORC_BUILD_LOCK_DIR=""
  HORC_BUILD_LOCK_OWNER_PID=""
}

build_lock_pid_alive() {
  local pid="$1"
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  kill -0 "${pid}" 2>/dev/null
}

acquire_build_lock() {
  local native_src="$1"
  local build_label="${2:-Windows}"
  local windows_root
  local lock_dir
  local pid_file
  local owner_pid=""

  windows_root="$(cd "${native_src}/.." && pwd)"
  lock_dir="${windows_root}/.horc-build.lock"
  pid_file="${lock_dir}/pid"

  if mkdir "${lock_dir}" 2>/dev/null; then
    HORC_BUILD_LOCK_OWNER_PID="${BASHPID:-$$}"
    printf '%s\n' "${HORC_BUILD_LOCK_OWNER_PID}" > "${pid_file}"
    HORC_BUILD_LOCK_DIR="${lock_dir}"
    trap release_build_lock EXIT
    echo "horc build: acquired build lock ${lock_dir}"
    return
  fi

  if [[ -f "${pid_file}" ]]; then
    owner_pid="$(cat "${pid_file}" 2>/dev/null || true)"
  fi
  if build_lock_pid_alive "${owner_pid}"; then
    echo "horc build: another ${build_label} build is already running with pid ${owner_pid}." >&2
    echo "horc build: wait for it to finish, or remove stale lock ${lock_dir} only after confirming that process is gone." >&2
    exit 2
  fi

  echo "horc build: removing stale build lock ${lock_dir}"
  rm -rf "${lock_dir}"
  if ! mkdir "${lock_dir}" 2>/dev/null; then
    echo "horc build: could not acquire build lock ${lock_dir}; another build may have started." >&2
    exit 2
  fi
  HORC_BUILD_LOCK_OWNER_PID="${BASHPID:-$$}"
  printf '%s\n' "${HORC_BUILD_LOCK_OWNER_PID}" > "${pid_file}"
  HORC_BUILD_LOCK_DIR="${lock_dir}"
  trap release_build_lock EXIT
  echo "horc build: acquired build lock ${lock_dir}"
}

require_command() {
  local command_name="$1"
  local install_hint="${2:-}"
  if command -v "${command_name}" >/dev/null 2>&1; then
    return
  fi

  echo "horc build: missing prerequisite: ${command_name}" >&2
  if [[ -n "${install_hint}" ]]; then
    echo "horc build: ${install_hint}" >&2
  fi
  exit 2
}

simulate_fail() {
  echo "horc simulate: $*" >&2
  exit 2
}

app_simulator_dir() {
  local root
  root="$(repo_root)"
  printf '%s\n' "${HORC_APP_SIMULATOR_DIR:-${root}/tools/app-simulator}"
}

ensure_app_simulator_deps() {
  local sim_dir="$1"
  if [[ ! -f "${sim_dir}/simulate.js" || ! -f "${sim_dir}/package.json" ]]; then
    simulate_fail "app simulator not found under ${sim_dir}"
  fi
  if ! command -v node >/dev/null 2>&1; then
    simulate_fail "missing prerequisite: node"
  fi
  if (cd "${sim_dir}" && node -e "require.resolve('playwright-core')" >/dev/null 2>&1); then
    return
  fi
  if ! command -v npm >/dev/null 2>&1; then
    simulate_fail "missing prerequisite: npm; run 'cd ${sim_dir} && npm install --ignore-scripts' manually"
  fi
  echo "horc simulate: installing app simulator Node dependencies in ${sim_dir}"
  if [[ -f "${sim_dir}/package-lock.json" ]]; then
    (cd "${sim_dir}" && npm ci --ignore-scripts --no-audit --no-fund)
  else
    (cd "${sim_dir}" && npm install --ignore-scripts --no-audit --no-fund)
  fi
}

ensure_app_simulator_ffmpeg() {
  local sim_dir="$1"
  if (cd "${sim_dir}" && node -e "const { playwrightFfmpegExecutablePath } = require('./web'); process.exit(playwrightFfmpegExecutablePath() ? 0 : 1)" >/dev/null 2>&1); then
    return
  fi
  if is_truthy "${HORC_SIM_SKIP_FFMPEG_INSTALL:-}"; then
    echo "horc simulate: Playwright ffmpeg is not installed; failure video artifacts will be skipped." >&2
    return
  fi
  echo "horc simulate: installing Playwright ffmpeg helper for failure video artifacts"
  if ! (cd "${sim_dir}" && npx playwright-core install ffmpeg); then
    echo "horc simulate: warning: could not install Playwright ffmpeg; failure video artifacts will be skipped." >&2
  fi
}

run_app_simulator() {
  local target="$1"
  shift
  local sim_dir
  sim_dir="$(app_simulator_dir)"
  ensure_app_simulator_deps "${sim_dir}"
  case "${target}" in
    web|all)
      ensure_app_simulator_ffmpeg "${sim_dir}"
      ;;
  esac
  (cd "$(repo_root)" && node "${sim_dir}/simulate.js" "${target}" "$@")
}

require_local_node_bin() {
  local native_src="$1"
  local bin_name="$2"
  local bin_root="${native_src}/node_modules/.bin"
  if [[ -x "${bin_root}/${bin_name}" || -x "${bin_root}/${bin_name}.cmd" || -x "${bin_root}/${bin_name}.ps1" ]]; then
    return
  fi

  echo "horc build: missing local Node build tool: ${bin_name}" >&2
  echo "horc build: run 'cd ${native_src} && npm ci' before direct native/Wine builds." >&2
  exit 2
}

require_npm_prereqs() {
  local native_src="$1"
  require_command node "Install Node.js for the build host."
  require_command npm "Install npm for the build host."
  require_command npx "Install npm/npx for app.asar inspection."
  require_local_node_bin "${native_src}" "electron-builder"
  require_local_node_bin "${native_src}" "asar"
}

require_wine_prereqs() {
  require_command makensis "Install NSIS/makensis, or use HORC_WIN_BUILD_MODE=docker."
  if command -v wine >/dev/null 2>&1 || command -v wine64 >/dev/null 2>&1; then
    return
  fi
  echo "horc build: missing prerequisite: wine" >&2
  echo "horc build: Install Wine for direct Linux Windows builds, or use HORC_WIN_BUILD_MODE=docker." >&2
  exit 2
}

docker_permission_hint() {
  cat >&2 <<'TXT'
horc build: remediation commands:
  sudo docker info
  sudo usermod -aG docker "$USER"
  newgrp docker
TXT
}

binfmt_remediation_hint() {
  cat >&2 <<'TXT'
horc build: remediation commands:
  sudo docker run --privileged --rm tonistiigi/binfmt --install amd64
  docker run --rm --platform linux/amd64 alpine:3.20 uname -m
TXT
}

select_windows_build_mode() {
  local requested_mode="$1"
  local arch="$2"
  case "${requested_mode}" in
    auto|native|wine|docker|arm64-fast|linux-arm64-fast|fast-arm64)
      ;;
    *)
      build_fail "HORC_WIN_BUILD_MODE must be auto, native, wine, docker, or arm64-fast; got '${requested_mode}'."
      ;;
  esac

  if is_native_windows_shell; then
    case "${requested_mode}" in
      auto|native)
        printf '%s\n' "native"
        return
        ;;
      *)
        build_fail "HORC_WIN_BUILD_MODE=${requested_mode} is for Linux hosts; use auto or native on Windows."
        ;;
    esac
  fi

  if ! is_linux_shell; then
    build_fail "unsupported build host: $(host_kernel) $(host_machine). Use native Windows or Linux x86_64/aarch64."
  fi

  case "${requested_mode}" in
    native)
      build_fail "HORC_WIN_BUILD_MODE=native requires a Windows shell; current host is $(host_kernel) $(host_machine)."
      ;;
    docker)
      printf '%s\n' "docker"
      return
      ;;
    wine)
      if [[ "${arch}" == "aarch64" ]] && ! is_truthy "${HORC_ALLOW_CROSS_WIN_BUILD:-}"; then
        echo "horc build: Linux aarch64 direct Wine is debug-only and may hang in rcedit." >&2
        echo "horc build: use HORC_WIN_BUILD_MODE=docker, or set HORC_ALLOW_CROSS_WIN_BUILD=1 to force direct Wine." >&2
        exit 2
      fi
      printf '%s\n' "wine"
      return
      ;;
    arm64-fast|linux-arm64-fast|fast-arm64)
      if [[ "${arch}" != "aarch64" ]]; then
        build_fail "HORC_WIN_BUILD_MODE=${requested_mode} is only for Linux aarch64 hosts; current arch is ${arch}."
      fi
      printf '%s\n' "linux-arm64-native-nsis-no-rcedit"
      return
      ;;
    auto)
      case "${arch}" in
        x86_64)
          printf '%s\n' "wine"
          return
          ;;
        aarch64)
          printf '%s\n' "docker"
          return
          ;;
        *)
          build_fail "auto mode does not know how to cross-build from Linux ${arch}; use HORC_WIN_BUILD_MODE=docker if Docker supports linux/amd64."
          ;;
      esac
      ;;
  esac
}

docker_amd64_probe() {
  local probe_image="${1:-alpine:3.20}"
  local output
  if ! output="$(docker run --rm --platform linux/amd64 "${probe_image}" uname -m 2>&1)"; then
    printf '%s\n' "${output}"
    return 1
  fi
  output="$(printf '%s\n' "${output}" | tail -n 1 | tr -d '\r')"
  printf '%s\n' "${output}"
  [[ "${output}" == "x86_64" ]]
}

auto_install_binfmt_enabled() {
  local requested_mode="$1"
  local host_arch="$2"
  if is_truthy "${HORC_NO_AUTO_INSTALL_BINFMT:-}"; then
    return 1
  fi
  if [[ -n "${HORC_AUTO_INSTALL_BINFMT:-}" ]]; then
    is_truthy "${HORC_AUTO_INSTALL_BINFMT:-}"
    return
  fi
  [[ "${host_arch}" == "aarch64" && ( "${requested_mode}" == "auto" || "${requested_mode}" == "docker" ) ]]
}

install_docker_binfmt() {
  echo "horc build: amd64 emulation missing; attempting QEMU binfmt registration..."
  if docker run --privileged --rm tonistiigi/binfmt --install amd64; then
    echo "horc build: QEMU binfmt registered successfully"
    return 0
  fi

  echo "horc build: automatic QEMU binfmt registration failed." >&2
  echo "horc build: Docker may require sudo, rootless Docker may block privileged containers, or this host may forbid privileged containers." >&2
  binfmt_remediation_hint
  return 1
}

ensure_docker_available() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "horc build: missing prerequisite: docker" >&2
    echo "horc build: Install Docker, start the daemon, and enable linux/amd64 emulation for ARM hosts." >&2
    return 1
  fi

  if ! docker info >/tmp/horc-docker-info.log 2>&1; then
    echo "horc build: Docker is installed, but the daemon is not reachable." >&2
    cat /tmp/horc-docker-info.log >&2 || true
    echo "horc build: start Docker or add this user to the docker group, then retry." >&2
    docker_permission_hint
    return 1
  fi
}

ensure_docker_amd64_emulation() {
  local requested_mode="$1"
  local host_arch="$2"
  local probe_image="${HORC_DOCKER_AMD64_PROBE_IMAGE:-alpine:3.20}"
  local probe_output

  echo "horc build: checking Docker linux/amd64 emulation..."
  if probe_output="$(docker_amd64_probe "${probe_image}")"; then
    echo "horc build: linux/amd64 check returned ${probe_output}"
    return 0
  fi

  printf '%s\n' "${probe_output}" >&2
  echo "horc build: Docker is running, but linux/amd64 containers cannot execute on this host." >&2
  if ! auto_install_binfmt_enabled "${requested_mode}" "${host_arch}"; then
    echo "horc build: automatic QEMU binfmt registration is disabled." >&2
    binfmt_remediation_hint
    return 1
  fi

  install_docker_binfmt || return 1

  echo "horc build: re-checking Docker linux/amd64 emulation..."
  if probe_output="$(docker_amd64_probe "${probe_image}")"; then
    echo "horc build: linux/amd64 check returned ${probe_output}"
    return 0
  fi

  printf '%s\n' "${probe_output}" >&2
  echo "horc build: linux/amd64 emulation still does not execute after QEMU binfmt registration." >&2
  binfmt_remediation_hint
  return 1
}

docker_image_pullable() {
  local image="$1"
  if docker_image_exists_locally "${image}"; then
    return 0
  fi
  docker manifest inspect "${image}" >/tmp/horc-docker-image.log 2>&1
}

docker_image_exists_locally() {
  local image="$1"
  docker image inspect "${image}" >/dev/null 2>&1
}

prepared_docker_image_name() {
  printf '%s\n' "${HORC_PREPARED_DOCKER_IMAGE:-horc/electron-builder-wine-nsis:jammy}"
}

select_docker_builder_image() {
  local requested="${HORC_DOCKER_IMAGE:-}"
  local prepared
  if [[ -n "${requested}" ]]; then
    printf '%s\n' "${requested}"
    return
  fi
  prepared="$(prepared_docker_image_name)"
  if command -v docker >/dev/null 2>&1 && docker_image_exists_locally "${prepared}"; then
    printf '%s\n' "${prepared}"
    return
  fi
  printf '%s\n' "electronuserland/builder:wine"
}

prepare_docker_builder_image() {
  local root
  local dockerfile
  local image
  root="$(repo_root)"
  dockerfile="${root}/native/windows/docker/builder-wine-nsis.Dockerfile"
  image="$(prepared_docker_image_name)"
  ensure_docker_available || exit 2
  [[ -f "${dockerfile}" ]] || build_fail "prepared Dockerfile not found: ${dockerfile}"
  echo "horc build: preparing Docker builder image ${image}"
  echo "horc build: this pays the nsis/unar apt cost once so future builds can skip it"
  docker build --platform linux/amd64 -t "${image}" -f "${dockerfile}" "${root}/native/windows"
  echo "horc build: prepared ${image}"
  echo "horc build: future runs will auto-use it, or set HORC_DOCKER_IMAGE=${image}"
}

docker_builder_bootstrap_script() {
  cat <<'TXT'
ensure_makensis() {
  if command -v makensis >/dev/null 2>&1; then
    return 0
  fi
  echo "horc build: makensis missing in Docker builder; attempting apt-get install nsis"
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "horc build: Docker builder image lacks makensis and apt-get; use HORC_DOCKER_IMAGE with NSIS installed." >&2
    return 2
  fi
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends nsis
}

ensure_makensis
TXT
}

docker_builder_preflight_script() {
  cat <<'TXT'
set -e
printf "builder arch=%s\n" "$(uname -m)"
command -v npm
command -v npx
command -v wine || command -v wine64
if command -v makensis >/dev/null 2>&1; then
  command -v makensis
else
  echo "horc build: makensis is not preinstalled in Docker builder; the build step will install nsis if Docker remains selected."
fi
TXT
}

native_electron_version() {
  local native_src="$1"
  node -e "const fs=require('fs'); const path=require('path'); const modulePkg=path.join('${native_src}', 'node_modules/electron/package.json'); if (fs.existsSync(modulePkg)) { process.stdout.write(require(modulePkg).version); } else { const pkg=require(path.join('${native_src}', 'package.json')); process.stdout.write(String((pkg.devDependencies && pkg.devDependencies.electron) || (pkg.dependencies && pkg.dependencies.electron) || '').replace(/^[^0-9]*/, '')); }"
}

native_electron_checksum() {
  local native_src="$1"
  local file_name="$2"
  node -e "const fs=require('fs'); const path=require('path'); const checks=path.join('${native_src}', 'node_modules/electron/checksums.json'); if (!fs.existsSync(checks)) process.exit(0); const c=require(checks); process.stdout.write(String(c['${file_name}'] || ''))"
}

sha256_file() {
  local file_path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${file_path}" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${file_path}" | awk '{print $1}'
  else
    return 1
  fi
}

ensure_host_electron_cache() {
  local native_src="$1"
  local electron_cache="${HORC_ELECTRON_CACHE_DIR:-${HOME}/.cache/electron}"
  local electron_version
  local file_name
  local cache_path
  local expected_sha
  local actual_sha
  local url
  local tmp_path

  require_command node "Install Node.js so horc can inspect the Electron package version."
  electron_version="$(native_electron_version "${native_src}")"
  file_name="electron-v${electron_version}-win32-x64.zip"
  cache_path="${electron_cache}/${file_name}"
  expected_sha="$(native_electron_checksum "${native_src}" "${file_name}")"
  mkdir -p "${electron_cache}"

  if [[ -f "${cache_path}" ]]; then
    if [[ -n "${expected_sha}" ]]; then
      actual_sha="$(sha256_file "${cache_path}")" || build_fail "sha256 tool not found for Electron cache validation."
      if [[ "${actual_sha}" != "${expected_sha}" ]]; then
        echo "horc build: cached ${file_name} checksum mismatch; refreshing"
        rm -f "${cache_path}"
      else
        echo "horc build: Electron win32-x64 cache ready: ${cache_path}"
        return 0
      fi
    else
      echo "horc build: Electron win32-x64 cache ready: ${cache_path}"
      return 0
    fi
  fi

  require_command curl "Install curl, or pre-populate ${cache_path}."
  url="https://github.com/electron/electron/releases/download/v${electron_version}/${file_name}"
  tmp_path="${cache_path}.tmp"
  echo "horc build: downloading ${url}"
  curl -fL --retry 3 --retry-delay 2 -o "${tmp_path}" "${url}"
  if [[ -n "${expected_sha}" ]]; then
    actual_sha="$(sha256_file "${tmp_path}")" || build_fail "sha256 tool not found for Electron cache validation."
    if [[ "${actual_sha}" != "${expected_sha}" ]]; then
      rm -f "${tmp_path}"
      build_fail "downloaded ${file_name} checksum mismatch."
    fi
  fi
  mv "${tmp_path}" "${cache_path}"
  echo "horc build: Electron win32-x64 cache ready: ${cache_path}"
}

docker_builder_preflight() {
  local image="$1"
  local requested_mode="$2"
  local host_arch="$3"
  local bootstrap
  local preflight_status
  ensure_docker_available || return 1
  ensure_docker_amd64_emulation "${requested_mode}" "${host_arch}" || return 1

  bootstrap="$(docker_builder_bootstrap_script)"
  echo "horc build: checking Docker linux/amd64 builder prerequisites in ${image}"
  set +e
  docker run --rm --platform linux/amd64 "${image}" bash -lc \
    "$(docker_builder_preflight_script)" 2>&1 | tee /tmp/horc-docker-preflight.log
  preflight_status="${PIPESTATUS[0]}"
  set -e
  if [[ "${preflight_status}" -ne 0 ]]; then
    echo "horc build: Docker linux/amd64 builder preflight failed." >&2
    echo "horc build: ensure the builder can run npm, npx, Wine, and makensis; or set HORC_DOCKER_IMAGE to a prepared builder image." >&2
    return 1
  fi
}

build_doctor() {
  local native_src="${HERMES_WASM_AGENT_NATIVE_SRC:-}"
  local root
  local target_arch="${HORC_TARGET_WIN_ARCH:-x64}"
  local requested_mode="${HORC_WIN_BUILD_MODE:-auto}"
  local host_os
  local host_arch
  local build_mode
  local expected_mode
  local docker_available="no"
  local docker_permission="no"
  local amd64_binfmt="no"
  local image_pullable="no"
  local android_root
  local android_requested_mode="${HORC_ANDROID_BUILD_MODE:-auto}"
  local android_selected_mode
  local docker_image
  local android_docker_image="${HORC_ANDROID_DOCKER_IMAGE:-ghcr.io/cirruslabs/android-sdk:35}"
  local probe_image="${HORC_DOCKER_AMD64_PROBE_IMAGE:-alpine:3.20}"
  local probe_output

  root="$(repo_root)"
  native_src="${native_src:-${root}/native/windows/src}"
  android_root="${HERMES_WASM_AGENT_ANDROID_ROOT:-${root}/native/android}"
  docker_image="$(select_docker_builder_image)"
  host_os="$(host_kernel)"
  host_arch="$(canonical_host_arch)"
  if is_native_windows_shell; then
    host_os="Windows"
  fi

  build_mode="$(select_windows_build_mode "${requested_mode}" "${host_arch}")"
  expected_mode="${build_mode}"
  if [[ "${build_mode}" == "docker" ]]; then
    expected_mode="docker-amd64-wine"
  fi

  if command -v docker >/dev/null 2>&1; then
    docker_available="yes"
    if docker info >/tmp/horc-docker-info.log 2>&1; then
      docker_permission="yes"
      if probe_output="$(docker_amd64_probe "${probe_image}")"; then
        amd64_binfmt="yes (${probe_output})"
      else
        amd64_binfmt="no"
      fi
      if docker_image_pullable "${docker_image}"; then
        image_pullable="yes"
      else
        image_pullable="no"
      fi
    fi
  fi
  android_evaluate_local_tools "${android_root}" || true
  android_selected_mode="$(select_android_build_mode "${android_requested_mode}" "${android_root}")"

  echo "horc build doctor"
  echo "  host OS/arch: ${host_os} ${host_arch}"
  echo "  target: win32-${target_arch}"
  echo "  expected build mode: ${expected_mode}"
  echo "  native source: ${native_src}"
  echo "  Android source: ${android_root}"
  echo "  Android selected build mode: ${android_selected_mode}"
  echo "  Android Java available: ${ANDROID_JAVA_AVAILABLE}"
  echo "  Android Gradle available: ${ANDROID_GRADLE_AVAILABLE}${ANDROID_GRADLE_PATH:+ (${ANDROID_GRADLE_PATH})}"
  echo "  Android SDK path: ${ANDROID_SDK_PATH:-not found}"
  echo "  Android AAPT2 path: ${ANDROID_AAPT2_PATH:-not found}"
  echo "  Android AAPT2 runnable: ${ANDROID_AAPT2_RUNNABLE}${ANDROID_AAPT2_OUTPUT:+ (${ANDROID_AAPT2_OUTPUT})}"
  echo "  Android Docker image: ${android_docker_image}"
  echo "  Docker available: ${docker_available}"
  echo "  Docker user permission: ${docker_permission}"
  echo "  amd64 binfmt available: ${amd64_binfmt}"
  echo "  Wine builder image pullable: ${image_pullable}"
  echo "  auto binfmt install: $(auto_install_binfmt_enabled "${requested_mode}" "${host_arch}" && echo yes || echo no)"

  if [[ "${docker_available}" != "yes" ]]; then
    echo "  remediation: install Docker and start the Docker daemon"
  elif [[ "${docker_permission}" != "yes" ]]; then
    echo "  remediation:"
    echo "    sudo docker info"
    echo "    sudo usermod -aG docker \"\$USER\""
    echo "    newgrp docker"
  elif [[ "${expected_mode}" == "docker-amd64-wine" && "${amd64_binfmt}" == "no" ]]; then
    echo "  remediation:"
    echo "    sudo docker run --privileged --rm tonistiigi/binfmt --install amd64"
    echo "    docker run --rm --platform linux/amd64 ${probe_image} uname -m"
  elif [[ "${expected_mode}" == "docker-amd64-wine" && "${image_pullable}" != "yes" ]]; then
    echo "  remediation:"
    echo "    docker pull --platform linux/amd64 ${docker_image}"
  elif [[ "${android_requested_mode}" == "local" && "${ANDROID_AAPT2_RUNNABLE}" != "yes" ]]; then
    echo "  remediation:"
    echo "    HORC_ANDROID_BUILD_MODE=auto horc build android"
    echo "    HORC_ANDROID_BUILD_MODE=docker horc build android"
    if [[ -n "${ANDROID_AAPT2_PATH}" ]]; then
      echo "    AAPT2 failed: ${ANDROID_AAPT2_OUTPUT}"
    fi
  elif [[ "${android_selected_mode}" == "docker" && "${docker_available}" == "yes" && "${docker_permission}" == "yes" && "${amd64_binfmt}" == "no" ]]; then
    echo "  remediation:"
    echo "    sudo docker run --privileged --rm tonistiigi/binfmt --install amd64"
    echo "    docker run --rm --platform linux/amd64 ${probe_image} uname -m"
  else
    echo "  remediation: none"
  fi
}

run_direct_windows_release() {
  local native_src="$1"
  echo "horc build: cd ${native_src} && npm run release:win:x64:prod"
  (cd "${native_src}" && npm run release:win:x64:prod)
}

build_windows_fast() {
  local native_src="${HERMES_WASM_AGENT_NATIVE_SRC:-}"
  local root
  local started_ms
  local build_status=0
  local tasks
  local filtered_tasks=()
  local task

  if [[ -z "${native_src}" ]]; then
    root="$(repo_root)"
    native_src="${root}/native/windows/src"
  else
    root="$(repo_root)"
  fi

  if [[ ! -f "${native_src}/package.json" ]]; then
    echo "horc build win-fast: native Windows package not found: ${native_src}" >&2
    echo "set HERMES_WASM_AGENT_NATIVE_SRC to override" >&2
    exit 2
  fi

  acquire_build_lock "${native_src}" "Windows fast"
  require_npm_prereqs "${native_src}"

  tasks="${HORC_WIN_FAST_TASKS:-test:native-backend-resolver test:native-policy test:windows-hot-ops test:windows-hot-ops-hmr test:windows-hot-ops-override test:android-connection-parser test:artifacts pack:win:x64}"
  if is_falsey "${HORC_WIN_FAST_PACK:-1}"; then
    for task in ${tasks}; do
      if [[ "${task}" != "pack:win:x64" ]]; then
        filtered_tasks+=("${task}")
      fi
    done
    tasks="${filtered_tasks[*]}"
  fi
  if [[ -z "${tasks// }" ]]; then
    echo "horc build win-fast: no tasks selected" >&2
    exit 2
  fi

  started_ms="$(android_now_ms)"
  echo "horc build win-fast: host $(host_kernel) $(canonical_host_arch), target win32-x64 source/package checks"
  echo "horc build win-fast: selected mode local-node"
  echo "horc build win-fast: ${tasks}"
  set +e
  (
    cd "${native_src}" || exit 2
    if [[ "$(host_kernel)" == "Linux" && "$(canonical_host_arch)" == "aarch64" ]] && ! is_truthy "${HORC_WIN_FAST_RESOURCE_EDIT:-}"; then
      export WASM_AGENT_SKIP_WIN_RESOURCE_EDIT=1
      echo "horc build win-fast: skipping Wine rcedit on Linux ARM64; set HORC_WIN_FAST_RESOURCE_EDIT=1 to force it"
    fi
    for task in ${tasks}; do
      echo "horc build win-fast: npm run ${task}"
      npm run "${task}" || exit $?
    done
  )
  build_status=$?
  set -e
  if [[ "${build_status}" -eq 0 ]]; then
    if compgen -G "${native_src}/../release/win-unpacked/*" >/dev/null; then
      echo "horc build win-fast: win-unpacked output: ${native_src}/../release/win-unpacked"
    fi
    echo "horc build win-fast: source/package checks only; no NSIS installer, release feed, or installed-app proof was produced"
  fi
  record_windows_build_benchmark "${root}" "${native_src}" "win-fast" "local-node" "${build_status}" "${started_ms}" "${tasks}"
  return "${build_status}"
}

run_linux_arm64_native_nsis_no_rcedit_release() {
  local native_src="$1"
  echo "horc build: Docker amd64 Wine builder failed under QEMU; falling back to Linux ARM64 native NSIS without rcedit."
  echo "horc build: this fallback skips Windows executable resource editing and requires a Windows smoke test."
  echo "horc build: cd ${native_src} && WASM_AGENT_SKIP_WIN_RESOURCE_EDIT=1 npm run release:win:x64:prod"
  (cd "${native_src}" && WASM_AGENT_SKIP_WIN_RESOURCE_EDIT=1 npm run release:win:x64:prod)
}

run_docker_windows_release() {
  local root="$1"
  local native_src="$2"
  local image="$3"
  local bootstrap
  local build_script
  local electron_cache="${HORC_ELECTRON_CACHE_DIR:-${HOME}/.cache/electron}"
  local electron_builder_cache="${HORC_ELECTRON_BUILDER_CACHE_DIR:-${HOME}/.cache/electron-builder}"
  local host_uid
  local host_gid
  local docker_status
  bootstrap="$(docker_builder_bootstrap_script)"
  ensure_host_electron_cache "${native_src}"
  mkdir -p "${electron_cache}" "${electron_builder_cache}"
  build_script="$(cat <<'TXT'
set -euo pipefail
cleanup_owner() {
  if [[ -n "${HORC_HOST_UID:-}" && -n "${HORC_HOST_GID:-}" ]] && command -v chown >/dev/null 2>&1; then
    for path in ../release ../dist build node_modules /root/.cache/electron /root/.cache/electron-builder; do
      [[ -e "${path}" ]] && chown -R "${HORC_HOST_UID}:${HORC_HOST_GID}" "${path}" 2>/dev/null || true
    done
  fi
}
trap cleanup_owner EXIT
node_dependency_fingerprint() {
  node - <<'NODE'
const crypto = require("crypto");
const fs = require("fs");
const files = ["package.json", "package-lock.json"];
const hash = crypto.createHash("sha256");
for (const file of files) {
  if (fs.existsSync(file)) {
    hash.update(file);
    hash.update("\0");
    hash.update(fs.readFileSync(file));
    hash.update("\0");
  }
}
process.stdout.write(hash.digest("hex"));
NODE
}
ensure_node_deps() {
  local fingerprint_file="node_modules/.horc-npm-fingerprint"
  local expected
  expected="$(node_dependency_fingerprint)"
  if [[ "${HORC_FORCE_NPM_CI:-0}" != "1" \
    && -f "${fingerprint_file}" \
    && "$(cat "${fingerprint_file}" 2>/dev/null || true)" == "${expected}" \
    && -x node_modules/.bin/electron-builder \
    && -x node_modules/.bin/asar ]]; then
    echo "horc build: reusing cached Windows Node dependencies"
    return
  fi

  echo "horc build: installing Windows Node dependencies with npm ci"
  npm ci
  test -x node_modules/.bin/electron-builder || { echo "missing electron-builder after npm ci" >&2; exit 2; }
  test -x node_modules/.bin/asar || { echo "missing asar after npm ci" >&2; exit 2; }
  mkdir -p node_modules
  printf '%s\n' "${expected}" > "${fingerprint_file}"
}
ensure_node_deps
npm run release:win:x64:prod
TXT
)"
  host_uid="$(id -u 2>/dev/null || true)"
  host_gid="$(id -g 2>/dev/null || true)"

  echo "horc build: starting Docker Wine builder..."
  echo "horc build: docker ${image} --platform linux/amd64"
  docker_status=0
  docker run --rm \
    --platform linux/amd64 \
    -e WASM_AGENT_DEFAULT_SERVER_URL="https://wa.colmeio.com" \
    -e WASM_AGENT_ALLOW_LOCAL_DEV="" \
    -e ELECTRON_CACHE="/root/.cache/electron" \
    -e ELECTRON_BUILDER_CACHE="/root/.cache/electron-builder" \
    -e HORC_FORCE_NPM_CI="${HORC_FORCE_NPM_CI:-0}" \
    -e HORC_HOST_UID="${host_uid}" \
    -e HORC_HOST_GID="${host_gid}" \
    -v "${root}:${root}" \
    -v "${electron_cache}:/root/.cache/electron" \
    -v "${electron_builder_cache}:/root/.cache/electron-builder" \
    -w "${native_src}" \
    "${image}" \
    bash -lc "${bootstrap}
${build_script}" || docker_status=$?
  if [[ "${docker_status}" -ne 0 ]]; then
    echo "horc build: Docker Wine builder exited with status ${docker_status}" >&2
    return "${docker_status}"
  fi
  return 0
}

select_installer_path() {
  local release_root="$1"
  local target_arch="$2"
  local -a versioned_installers=()
  local -a installers=()

  if [[ -d "${release_root}" ]]; then
    mapfile -t versioned_installers < <(find "${release_root}" -maxdepth 1 -type f -name "WASM-Agent-Setup-${target_arch}-*.exe" -print | sort)
    if [[ ${#versioned_installers[@]} -gt 0 ]]; then
      printf '%s\n' "${versioned_installers[$((${#versioned_installers[@]} - 1))]}"
      return
    fi

    if [[ -f "${release_root}/WASM-Agent-Setup-${target_arch}.exe" ]]; then
      printf '%s\n' "${release_root}/WASM-Agent-Setup-${target_arch}.exe"
      return
    fi

    mapfile -t installers < <(find "${release_root}" -maxdepth 1 -type f -name "*.exe" -print | sort)
    if [[ ${#installers[@]} -gt 0 ]]; then
      printf '%s\n' "${installers[$((${#installers[@]} - 1))]}"
      return
    fi
  fi
}

post_build_verify_and_manifest() {
  local native_src="$1"
  local build_mode="$2"
  local target_arch="$3"
  local trusted_production="$4"
  local requires_windows_smoke_test="$5"
  local host_os="$6"
  local host_arch="$7"
  local windows_root
  local release_root
  local unpacked_exe
  local app_asar
  local installer_path
  local manifest_path
  local asar_listing

  windows_root="$(cd "${native_src}/.." && pwd)"
  release_root="${windows_root}/release"
  unpacked_exe="${release_root}/win-unpacked/WASM Agent.exe"
  app_asar="${release_root}/win-unpacked/resources/app.asar"
  installer_path="$(select_installer_path "${release_root}" "${target_arch}")"
  manifest_path="${release_root}/horc-build-manifest.json"

  if [[ "${HORC_REQUIRE_VERIFIED_INSTALLER:-1}" != "0" ]]; then
    [[ -f "${unpacked_exe}" ]] || build_fail "missing packaged app executable: ${unpacked_exe}"
    [[ -f "${app_asar}" ]] || build_fail "missing packaged app.asar: ${app_asar}"
    [[ -n "${installer_path}" && -f "${installer_path}" ]] || build_fail "missing Windows installer under ${release_root}/*.exe"
  fi

  require_command npx "Install npm/npx so horc can inspect resources/app.asar."
  asar_listing="$(mktemp)"
  if ! (cd "${native_src}" && npx --no-install asar list "${app_asar}" > "${asar_listing}"); then
    rm -f "${asar_listing}"
    build_fail "could not inspect app.asar with npx --no-install asar; run 'cd ${native_src} && npm ci'."
  fi

  echo "horc build: app.asar first 80 entries"
  sed -n '1,80p' "${asar_listing}"
  for expected in "/main.js" "/fallback.html" "/native-defaults.json" "/package.json"; do
    if ! grep -Fxq "${expected}" "${asar_listing}"; then
      rm -f "${asar_listing}"
      build_fail "app.asar is missing expected entry: ${expected}"
    fi
  done
  rm -f "${asar_listing}"

  require_command node "Install Node.js so horc can write the build manifest."
  HORC_MANIFEST_PATH="${manifest_path}" \
  HORC_MANIFEST_HOST_OS="${host_os}" \
  HORC_MANIFEST_HOST_ARCH="${host_arch}" \
  HORC_MANIFEST_TARGET="win32-${target_arch}" \
  HORC_MANIFEST_MODE="${build_mode}" \
  HORC_MANIFEST_TRUSTED="${trusted_production}" \
  HORC_MANIFEST_SMOKE="${requires_windows_smoke_test}" \
  HORC_MANIFEST_INSTALLER="${installer_path}" \
  HORC_MANIFEST_ASAR="${app_asar}" \
  node <<'NODE'
const fs = require("fs");

const manifest = {
  host_os: process.env.HORC_MANIFEST_HOST_OS || "",
  host_arch: process.env.HORC_MANIFEST_HOST_ARCH || "",
  target: process.env.HORC_MANIFEST_TARGET || "win32-x64",
  mode: process.env.HORC_MANIFEST_MODE || "",
  trusted_production: process.env.HORC_MANIFEST_TRUSTED === "true",
  requires_windows_smoke_test: process.env.HORC_MANIFEST_SMOKE === "true",
  installer_path: process.env.HORC_MANIFEST_INSTALLER || "",
  app_asar_path: process.env.HORC_MANIFEST_ASAR || "",
  timestamp: new Date().toISOString(),
};

fs.writeFileSync(process.env.HORC_MANIFEST_PATH, `${JSON.stringify(manifest, null, 2)}\n`);
NODE

  echo "horc build: wrote ${manifest_path}"
  echo "horc build: mode=${build_mode} trusted_production=${trusted_production} requires_windows_smoke_test=${requires_windows_smoke_test}"
}

generate_native_release_feed() {
  local root="$1"
  local label="${2:-horc build}"
  echo "${label}: generating native release feed"
  require_command node "Install Node.js so horc can generate the native release feed."
  (cd "${root}" && node plugins/wasm-agent/scripts/generate-native-release-feed.js)
}

should_generate_native_release_feed() {
  ! is_falsey "${HORC_GENERATE_NATIVE_RELEASE_FEED:-1}"
}

android_build_benchmark_path() {
  local root="$1"
  printf '%s\n' "${HORC_ANDROID_BUILD_BENCHMARK_LOG:-${root}/reports/build/android/build-benchmarks.jsonl}"
}

android_now_ms() {
  "${PYTHON_BIN}" - <<'PY'
import time
print(int(time.time() * 1000))
PY
}

record_android_build_benchmark() {
  local root="$1"
  local android_root="$2"
  local lane="$3"
  local build_mode="$4"
  local status="$5"
  local started_ms="$6"
  local tasks="${7:-}"
  local log_path
  local ended_ms
  log_path="$(android_build_benchmark_path "${root}")"
  ended_ms="$(android_now_ms)"
  mkdir -p "$(dirname "${log_path}")"
  "${PYTHON_BIN}" - "${log_path}" "${android_root}" "${lane}" "${build_mode}" "${status}" "${started_ms}" "${ended_ms}" "${tasks}" "$(host_kernel)" "$(canonical_host_arch)" <<'PY'
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

log_path, android_root, lane, build_mode, status, started_ms, ended_ms, tasks, host_os, host_arch = sys.argv[1:11]
started_ms = int(started_ms)
ended_ms = int(ended_ms)
android = Path(android_root)

def size(path: Path) -> int:
    return path.stat().st_size if path.is_file() else 0

def du_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    proc = subprocess.run(["du", "-sb", str(path)], text=True, capture_output=True, check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        return 0
    return int(proc.stdout.split()[0])

def df_avail(path: Path) -> int:
    proc = subprocess.run(["df", "-Pk", str(path)], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return 0
    lines = proc.stdout.strip().splitlines()
    if len(lines) < 2:
        return 0
    return int(lines[-1].split()[3]) * 1024

release = android / "release"
debug_apks = sorted((android / "app" / "build" / "outputs" / "apk").glob("**/*.apk")) if (android / "app" / "build" / "outputs" / "apk").exists() else []
record = {
    "schema": "hermes.horc.android_build_benchmark.v1",
    "recordedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "lane": lane,
    "buildMode": build_mode,
    "status": int(status),
    "ok": int(status) == 0,
    "durationMs": max(0, ended_ms - started_ms),
    "tasks": tasks.split() if tasks else [],
    "host": {"os": host_os, "arch": host_arch},
    "env": {
        "HORC_ANDROID_BUILD_MODE": os.environ.get("HORC_ANDROID_BUILD_MODE", "auto"),
        "HORC_ANDROID_GRADLE_VERSION": os.environ.get("HORC_ANDROID_GRADLE_VERSION", "8.9"),
        "HORC_ANDROID_GRADLE_DAEMON": os.environ.get("HORC_ANDROID_GRADLE_DAEMON", ""),
        "HORC_ANDROID_CONFIGURATION_CACHE": os.environ.get("HORC_ANDROID_CONFIGURATION_CACHE", ""),
        "HORC_ANDROID_FAST_TASKS": os.environ.get("HORC_ANDROID_FAST_TASKS", ""),
    },
    "outputs": {
        "debugApkCount": len(debug_apks),
        "debugApkBytes": sum(size(path) for path in debug_apks),
        "releaseArm64Bytes": size(release / "WASM-Agent-arm64.apk"),
        "releaseUniversalBytes": size(release / "WASM-Agent-universal.apk"),
    },
    "storage": {
        "rootAvailableBytes": df_avail(android),
        "androidAppBuildBytes": du_bytes(android / "app" / "build"),
        "androidGradleHomeBytes": du_bytes(android / ".gradle-home"),
    },
}
with open(log_path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
print(f"horc build {lane}: benchmark duration={record['durationMs']}ms status={status} log={log_path}")
PY
}

windows_build_benchmark_path() {
  local root="$1"
  printf '%s\n' "${HORC_WIN_BUILD_BENCHMARK_LOG:-${root}/reports/build/windows/build-benchmarks.jsonl}"
}

record_windows_build_benchmark() {
  local root="$1"
  local native_src="$2"
  local lane="$3"
  local build_mode="$4"
  local status="$5"
  local started_ms="$6"
  local tasks="${7:-}"
  local log_path
  local ended_ms
  log_path="$(windows_build_benchmark_path "${root}")"
  ended_ms="$(android_now_ms)"
  mkdir -p "$(dirname "${log_path}")"
  "${PYTHON_BIN}" - "${log_path}" "${native_src}" "${lane}" "${build_mode}" "${status}" "${started_ms}" "${ended_ms}" "${tasks}" "$(host_kernel)" "$(canonical_host_arch)" <<'PY'
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

log_path, native_src, lane, build_mode, status, started_ms, ended_ms, tasks, host_os, host_arch = sys.argv[1:11]
started_ms = int(started_ms)
ended_ms = int(ended_ms)
src = Path(native_src)
windows = src.parent
release = windows / "release"

def size(path: Path) -> int:
    return path.stat().st_size if path.is_file() else 0

def du_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    proc = subprocess.run(["du", "-sb", str(path)], text=True, capture_output=True, check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        return 0
    return int(proc.stdout.split()[0])

def df_avail(path: Path) -> int:
    proc = subprocess.run(["df", "-Pk", str(path)], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return 0
    lines = proc.stdout.strip().splitlines()
    if len(lines) < 2:
        return 0
    return int(lines[-1].split()[3]) * 1024

installers = sorted(release.glob("*.exe")) if release.exists() else []
record = {
    "schema": "hermes.horc.windows_build_benchmark.v1",
    "recordedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "lane": lane,
    "buildMode": build_mode,
    "status": int(status),
    "ok": int(status) == 0,
    "durationMs": max(0, ended_ms - started_ms),
    "tasks": tasks.split() if tasks else [],
    "host": {"os": host_os, "arch": host_arch},
    "env": {
        "HORC_WIN_BUILD_MODE": os.environ.get("HORC_WIN_BUILD_MODE", "auto"),
        "HORC_WIN_FAST_TASKS": os.environ.get("HORC_WIN_FAST_TASKS", ""),
        "HORC_WIN_FAST_PACK": os.environ.get("HORC_WIN_FAST_PACK", ""),
    },
    "outputs": {
        "winUnpackedBytes": du_bytes(release / "win-unpacked"),
        "installerCount": len(installers),
        "installerBytes": sum(size(path) for path in installers),
    },
    "storage": {
        "rootAvailableBytes": df_avail(windows),
        "windowsReleaseBytes": du_bytes(release),
        "nodeModulesBytes": du_bytes(src / "node_modules"),
    },
}
with open(log_path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
print(f"horc build {lane}: benchmark duration={record['durationMs']}ms status={status} log={log_path}")
PY
}

android_release_identity_env() {
  if is_truthy "${HORC_ANDROID_PRESERVE_BUILD_ID:-}"; then
    return
  fi
  echo "horc build android-apk: forcing fresh Android build identity for update detection"
  unset WASM_AGENT_ANDROID_BUILD_ID
  unset WASM_AGENT_ANDROID_VERSION_CODE
  unset WASM_AGENT_ANDROID_BUILD_GENERATED_AT
}

build_windows_native_release() {
  local native_src="${HERMES_WASM_AGENT_NATIVE_SRC:-}"
  local root
  local target_arch="${HORC_TARGET_WIN_ARCH:-x64}"
  local requested_mode="${HORC_WIN_BUILD_MODE:-auto}"
  local host_os
  local host_arch
  local build_mode
  local trusted_production="false"
  local requires_windows_smoke_test="true"
  local docker_image
  local benchmark_started_ms
  local build_status=0

  if [[ -z "${native_src}" ]]; then
    root="$(repo_root)"
    native_src="${root}/native/windows/src"
  else
    root="$(repo_root)"
  fi
  docker_image="$(select_docker_builder_image)"

  if [[ ! -f "${native_src}/package.json" ]]; then
    echo "horc build: native Windows package not found: ${native_src}" >&2
    echo "set HERMES_WASM_AGENT_NATIVE_SRC to override" >&2
    exit 2
  fi

  if [[ "${target_arch}" != "x64" ]]; then
    build_fail "HORC_TARGET_WIN_ARCH=${target_arch} is not supported yet; the Windows 11 target is x64."
  fi

  acquire_build_lock "${native_src}"

  host_os="$(host_kernel)"
  host_arch="$(canonical_host_arch)"
  if is_native_windows_shell; then
    host_os="Windows"
  fi
  build_mode="$(select_windows_build_mode "${requested_mode}" "${host_arch}")"
  benchmark_started_ms="$(android_now_ms)"
  echo "horc build: host ${host_os} ${host_arch}, target win32-${target_arch}"
  if [[ "${build_mode}" == "docker" ]]; then
    echo "horc build: selected mode docker-amd64-wine"
  else
    echo "horc build: selected mode ${build_mode}"
  fi

  set +e
  case "${build_mode}" in
    native)
      trusted_production="true"
      requires_windows_smoke_test="false"
      require_npm_prereqs "${native_src}"
      run_direct_windows_release "${native_src}"
      ;;
    wine)
      trusted_production="false"
      requires_windows_smoke_test="true"
      if [[ "${host_arch}" == "aarch64" ]]; then
        echo "horc build: WARNING Linux aarch64 direct Wine mode is debug-only and may hang." >&2
        echo "horc build: WARNING resulting artifact is cross-built and requires a Windows smoke test." >&2
      else
        echo "horc build: Linux x86_64 Wine cross-build selected; Windows smoke test required."
      fi
      require_npm_prereqs "${native_src}"
      require_wine_prereqs
      run_direct_windows_release "${native_src}"
      ;;
    linux-arm64-native-nsis-no-rcedit)
      trusted_production="false"
      requires_windows_smoke_test="true"
      echo "horc build: Linux ARM64 fast Windows cross-build selected; Windows smoke test required."
      require_npm_prereqs "${native_src}"
      require_command makensis "Install NSIS/makensis for HORC_WIN_BUILD_MODE=arm64-fast."
      run_linux_arm64_native_nsis_no_rcedit_release "${native_src}"
      ;;
    docker)
      trusted_production="false"
      requires_windows_smoke_test="true"
      if ! docker_builder_preflight "${docker_image}" "${requested_mode}" "${host_arch}"; then
        if [[ "${requested_mode}" == "auto" && "${host_arch}" == "aarch64" ]] && is_truthy "${HORC_ALLOW_CROSS_WIN_BUILD:-}"; then
          echo "horc build: Docker/QEMU unavailable; HORC_ALLOW_CROSS_WIN_BUILD is set, falling back to direct Wine debug mode." >&2
          require_npm_prereqs "${native_src}"
          require_wine_prereqs
          build_mode="wine"
          run_direct_windows_release "${native_src}"
      else
        echo "horc build: cannot use Docker linux/amd64 builder from $(host_kernel) $(host_machine)." >&2
        echo "horc build: remediation: install/start Docker and register QEMU amd64 binfmt, or run on Linux x86_64/Windows." >&2
        exit 2
        fi
      else
        build_mode="docker-amd64-wine"
        echo "horc build: Docker amd64 Wine cross-build selected; Windows smoke test required."
        if run_docker_windows_release "${root}" "${native_src}" "${docker_image}"; then
          :
        elif [[ "${requested_mode}" == "auto" && "${host_arch}" == "aarch64" ]]; then
          echo "horc build: Docker/QEMU builder failed; falling back to Linux ARM64 native NSIS without rcedit." >&2
          require_npm_prereqs "${native_src}"
          require_command makensis "Install NSIS/makensis for the Linux ARM64 native NSIS fallback."
          build_mode="linux-arm64-native-nsis-no-rcedit"
          run_linux_arm64_native_nsis_no_rcedit_release "${native_src}"
        else
          return 1
        fi
      fi
      ;;
    *)
      build_fail "internal error: unsupported selected build mode ${build_mode}"
      ;;
  esac
  build_status=$?
  set -e
  if [[ "${build_status}" -ne 0 ]]; then
    record_windows_build_benchmark "${root}" "${native_src}" "win" "${build_mode}" "${build_status}" "${benchmark_started_ms}" "release:win:x64:prod"
    return "${build_status}"
  fi

  post_build_verify_and_manifest "${native_src}" "${build_mode}" "${target_arch}" "${trusted_production}" "${requires_windows_smoke_test}" "${host_os}" "${host_arch}"
  if should_generate_native_release_feed; then
    generate_native_release_feed "${root}" "horc build"
  else
    echo "horc build: skipping native release feed generation for parallel build join"
  fi
  record_windows_build_benchmark "${root}" "${native_src}" "win" "${build_mode}" "0" "${benchmark_started_ms}" "release:win:x64:prod verify manifest feed"
}

android_local_tools_available() {
  local android_root="$1"
  android_evaluate_local_tools "${android_root}" >/dev/null 2>&1
}

android_gradle_path() {
  local android_root="$1"
  local cached_gradle="${android_root}/.gradle-dist/gradle-${HORC_ANDROID_GRADLE_VERSION:-8.9}/bin/gradle"
  if [[ -n "${GRADLE_BIN:-}" && -x "${GRADLE_BIN}" ]]; then
    printf '%s\n' "${GRADLE_BIN}"
  elif [[ -x "${android_root}/gradlew" ]]; then
    printf '%s\n' "${android_root}/gradlew"
  elif [[ -x "${cached_gradle}" ]]; then
    printf '%s\n' "${cached_gradle}"
  elif command -v gradle >/dev/null 2>&1; then
    command -v gradle
  fi
}

android_sdk_root() {
  local android_root="$1"
  if [[ -n "${ANDROID_HOME:-}" && -d "${ANDROID_HOME}" ]]; then
    printf '%s\n' "${ANDROID_HOME}"
  elif [[ -n "${ANDROID_SDK_ROOT:-}" && -d "${ANDROID_SDK_ROOT}" ]]; then
    printf '%s\n' "${ANDROID_SDK_ROOT}"
  elif [[ -d "${android_root}/.android-sdk" ]]; then
    printf '%s\n' "${android_root}/.android-sdk"
  fi
}

find_android_aapt2() {
  local android_root="$1"
  local sdk_root="$2"
  if [[ -n "${AAPT2_BIN:-}" && -x "${AAPT2_BIN}" ]]; then
    printf '%s\n' "${AAPT2_BIN}"
    return
  fi

  if [[ -n "${sdk_root}" && -d "${sdk_root}/build-tools" ]]; then
    local sdk_aapt2
    sdk_aapt2="$(find "${sdk_root}/build-tools" -mindepth 2 -maxdepth 2 -type f -name aapt2 -perm -111 -print 2>/dev/null | sort -V | tail -n 1)"
    if [[ -n "${sdk_aapt2}" ]]; then
      printf '%s\n' "${sdk_aapt2}"
      return
    fi
  fi

  find "${android_root}/.gradle-home" "${android_root}/.gradle" \
    -type f -name aapt2 -perm -111 -print 2>/dev/null | sort -V | tail -n 1 || true
}

android_aapt2_runnable() {
  local aapt2_path="$1"
  local android_root="${2:-}"
  local qemu_root="${QEMU_LD_PREFIX:-${android_root}/.android-sdk-qemu-root}"
  local output
  [[ -n "${aapt2_path}" && -x "${aapt2_path}" ]] || return 1
  if output="$("${aapt2_path}" version 2>&1)"; then
    ANDROID_AAPT2_OUTPUT="$(printf '%s\n' "${output}" | head -n 1 | tr -d '\r')"
    return 0
  fi
  if [[ -n "${android_root}" && -d "${qemu_root}" ]] && output="$(QEMU_LD_PREFIX="${qemu_root}" "${aapt2_path}" version 2>&1)"; then
    ANDROID_AAPT2_OUTPUT="$(printf '%s\n' "${output}" | head -n 1 | tr -d '\r') via QEMU_LD_PREFIX=${qemu_root}"
    ANDROID_AAPT2_QEMU_LD_PREFIX="${qemu_root}"
    return 0
  fi
  ANDROID_AAPT2_OUTPUT="${output}"
  return 1
}

android_evaluate_local_tools() {
  local android_root="$1"
  ANDROID_JAVA_AVAILABLE="no"
  ANDROID_GRADLE_AVAILABLE="no"
  ANDROID_GRADLE_PATH=""
  ANDROID_SDK_AVAILABLE="no"
  ANDROID_SDK_PATH=""
  ANDROID_AAPT2_PATH=""
  ANDROID_AAPT2_RUNNABLE="no"
  ANDROID_AAPT2_OUTPUT=""
  ANDROID_AAPT2_QEMU_LD_PREFIX=""
  ANDROID_LOCAL_DIAGNOSIS=""

  if command -v java >/dev/null 2>&1; then
    ANDROID_JAVA_AVAILABLE="yes"
  else
    ANDROID_LOCAL_DIAGNOSIS="Java is not available on PATH."
  fi

  ANDROID_GRADLE_PATH="$(android_gradle_path "${android_root}")"
  if [[ -n "${ANDROID_GRADLE_PATH}" ]]; then
    ANDROID_GRADLE_AVAILABLE="yes"
  elif [[ -z "${ANDROID_LOCAL_DIAGNOSIS}" ]]; then
    ANDROID_LOCAL_DIAGNOSIS="Gradle is not available; set GRADLE_BIN or install/cache Gradle ${HORC_ANDROID_GRADLE_VERSION:-8.9}."
  fi

  ANDROID_SDK_PATH="$(android_sdk_root "${android_root}")"
  if [[ -n "${ANDROID_SDK_PATH}" ]]; then
    ANDROID_SDK_AVAILABLE="yes"
  elif [[ -z "${ANDROID_LOCAL_DIAGNOSIS}" ]]; then
    ANDROID_LOCAL_DIAGNOSIS="Android SDK is not available; set ANDROID_HOME or ANDROID_SDK_ROOT."
  fi

  ANDROID_AAPT2_PATH="$(find_android_aapt2 "${android_root}" "${ANDROID_SDK_PATH}")"
  if [[ -n "${ANDROID_AAPT2_PATH}" ]] && android_aapt2_runnable "${ANDROID_AAPT2_PATH}" "${android_root}"; then
    ANDROID_AAPT2_RUNNABLE="yes"
  elif [[ -z "${ANDROID_AAPT2_PATH}" ]]; then
    [[ -z "${ANDROID_LOCAL_DIAGNOSIS}" ]] && ANDROID_LOCAL_DIAGNOSIS="AAPT2 was not found in the Android SDK build-tools or Gradle cache."
  else
    [[ -z "${ANDROID_LOCAL_DIAGNOSIS}" ]] && ANDROID_LOCAL_DIAGNOSIS="AAPT2 cannot execute on this host: ${ANDROID_AAPT2_OUTPUT}"
  fi

  [[ "${ANDROID_JAVA_AVAILABLE}" == "yes" && "${ANDROID_GRADLE_AVAILABLE}" == "yes" && "${ANDROID_SDK_AVAILABLE}" == "yes" && "${ANDROID_AAPT2_RUNNABLE}" == "yes" ]]
}

android_local_failure_hint() {
  local diagnosis="${ANDROID_LOCAL_DIAGNOSIS:-local Android toolchain is not usable}"
  echo "horc build android-apk: local Android build mode is unavailable: ${diagnosis}" >&2
  if [[ -n "${ANDROID_AAPT2_PATH:-}" ]]; then
    echo "horc build android-apk: AAPT2 path: ${ANDROID_AAPT2_PATH}" >&2
    echo "horc build android-apk: AAPT2 output: ${ANDROID_AAPT2_OUTPUT:-<none>}" >&2
  fi
  echo "horc build android-apk: remediation: use HORC_ANDROID_BUILD_MODE=auto or HORC_ANDROID_BUILD_MODE=docker so horc can build inside ${HORC_ANDROID_DOCKER_IMAGE:-ghcr.io/cirruslabs/android-sdk:35}." >&2
  echo "horc build android-apk: on ARM hosts, enable linux/amd64 Docker emulation with:" >&2
  echo "horc build android-apk:   sudo docker run --privileged --rm tonistiigi/binfmt --install amd64" >&2
}

select_android_build_mode() {
  local requested_mode="$1"
  local android_root="$2"
  case "${requested_mode}" in
    auto|local|docker)
      ;;
    *)
      build_fail "HORC_ANDROID_BUILD_MODE must be auto, local, or docker; got '${requested_mode}'."
      ;;
  esac

  case "${requested_mode}" in
    local)
      printf '%s\n' "local"
      ;;
    docker)
      printf '%s\n' "docker"
      ;;
    auto)
      if android_local_tools_available "${android_root}"; then
        printf '%s\n' "local"
      else
        printf '%s\n' "docker"
      fi
      ;;
  esac
}

android_docker_common_script() {
  cat <<'TXT'
set -euo pipefail
cleanup_owner() {
  if [[ -n "${HORC_HOST_UID:-}" && -n "${HORC_HOST_GID:-}" ]] && command -v chown >/dev/null 2>&1; then
    for path in app/build build release signing .gradle .gradle-home .gradle-dist; do
      [[ -e "${path}" ]] && chown -R "${HORC_HOST_UID}:${HORC_HOST_GID}" "${path}" 2>/dev/null || true
    done
  fi
}
trap cleanup_owner EXIT

ensure_tool() {
  local tool="$1"
  local package_name="$2"
  if command -v "${tool}" >/dev/null 2>&1; then
    return
  fi
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "${HORC_ANDROID_LOG_LABEL:-horc build android}: missing ${tool} and no apt-get in Android builder" >&2
    exit 2
  fi
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends "${package_name}"
}

ensure_gradle() {
  local version="${HORC_ANDROID_GRADLE_VERSION:-8.9}"
  local gradle_home="${PWD}/.gradle-dist"
  local gradle_bin="${gradle_home}/gradle-${version}/bin/gradle"
  if [[ ! -x "${gradle_bin}" ]]; then
    ensure_tool curl curl
    ensure_tool unzip unzip
    mkdir -p "${gradle_home}"
    local zip_path="/tmp/gradle-${version}-bin.zip"
    echo "${HORC_ANDROID_LOG_LABEL:-horc build android}: downloading Gradle ${version}"
    curl -fL --retry 3 --retry-delay 2 -o "${zip_path}" "https://services.gradle.org/distributions/gradle-${version}-bin.zip"
    unzip -q -o "${zip_path}" -d "${gradle_home}"
  fi
  export GRADLE_BIN="${gradle_bin}"
}

ensure_gradle
export GRADLE_USER_HOME="${PWD}/.gradle-home"
if [[ -z "${ANDROID_HOME:-}" && -d "${PWD}/.android-sdk" ]]; then
  export ANDROID_HOME="${PWD}/.android-sdk"
else
  export ANDROID_HOME="${ANDROID_HOME:-/opt/android-sdk-linux}"
fi
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME}}"
if [[ -z "${APKSIGNER_BIN:-}" && -x "${ANDROID_HOME}/build-tools/35.0.0/apksigner" ]]; then
  export APKSIGNER_BIN="${ANDROID_HOME}/build-tools/35.0.0/apksigner"
fi
export HORC_ANDROID_KOTLIN_IN_PROCESS="${HORC_ANDROID_KOTLIN_IN_PROCESS:-1}"
TXT
}

android_docker_build_script() {
  android_docker_common_script
  cat <<'TXT'
ensure_tool node nodejs
if [[ "${HORC_ANDROID_PRESERVE_BUILD_ID:-}" != "1" ]]; then
  unset WASM_AGENT_ANDROID_BUILD_ID
  unset WASM_AGENT_ANDROID_VERSION_CODE
  unset WASM_AGENT_ANDROID_BUILD_GENERATED_AT
fi
node scripts/release-android.js
TXT
}

run_docker_android_release() {
  local root="$1"
  local android_root="$2"
  local image="${HORC_ANDROID_DOCKER_IMAGE:-ghcr.io/cirruslabs/android-sdk:35}"
  local host_arch
  local host_uid
  local host_gid
  local docker_status
  local skip_apksigner_verify
  host_arch="$(canonical_host_arch)"
  ensure_docker_available || exit 2
  if [[ "${host_arch}" == "aarch64" ]]; then
    ensure_docker_amd64_emulation "${HORC_ANDROID_BUILD_MODE:-auto}" "${host_arch}" || exit 2
  fi
  mkdir -p "${android_root}/.gradle-home" "${android_root}/.gradle-dist"
  host_uid="$(id -u 2>/dev/null || true)"
  host_gid="$(id -g 2>/dev/null || true)"
  echo "horc build android-apk: starting Docker Android builder..."
  echo "horc build android-apk: docker ${image} --platform linux/amd64"
  docker_status=0
  skip_apksigner_verify="${WASM_AGENT_ANDROID_SKIP_APKSIGNER_VERIFY:-}"
  if [[ -z "${skip_apksigner_verify}" && "${host_arch}" == "aarch64" ]]; then
    skip_apksigner_verify=1
  fi
  docker run --rm \
    --platform linux/amd64 \
    -e HORC_ANDROID_GRADLE_VERSION="${HORC_ANDROID_GRADLE_VERSION:-8.9}" \
    -e HORC_ANDROID_LOG_LABEL="horc build android-apk" \
    -e HORC_ANDROID_RUN_UNIT_TESTS="${HORC_ANDROID_RUN_UNIT_TESTS:-0}" \
    -e HORC_ANDROID_PRESERVE_BUILD_ID="${HORC_ANDROID_PRESERVE_BUILD_ID:-0}" \
    -e WASM_AGENT_ANDROID_SKIP_LINT="${WASM_AGENT_ANDROID_SKIP_LINT:-1}" \
    -e WASM_AGENT_ANDROID_APKSIGNER_TIMEOUT_MS="${WASM_AGENT_ANDROID_APKSIGNER_TIMEOUT_MS:-600000}" \
    -e WASM_AGENT_ANDROID_SKIP_APKSIGNER_VERIFY="${skip_apksigner_verify:-0}" \
    -e WASM_AGENT_ANDROID_VOSK_MODEL_DIR="${WASM_AGENT_ANDROID_VOSK_MODEL_DIR:-}" \
    -e WASM_AGENT_ANDROID_BUILD_ID="${WASM_AGENT_ANDROID_BUILD_ID:-}" \
    -e WASM_AGENT_ANDROID_VERSION_CODE="${WASM_AGENT_ANDROID_VERSION_CODE:-}" \
    -e WASM_AGENT_ANDROID_BUILD_GENERATED_AT="${WASM_AGENT_ANDROID_BUILD_GENERATED_AT:-}" \
    -e HORC_HOST_UID="${host_uid}" \
    -e HORC_HOST_GID="${host_gid}" \
    -v "${root}:${root}" \
    -w "${android_root}" \
    "${image}" \
    bash -lc "$(android_docker_build_script)" || docker_status=$?
  if [[ "${docker_status}" -ne 0 ]]; then
    echo "horc build android-apk: Docker Android builder exited with status ${docker_status}" >&2
    return "${docker_status}"
  fi
}

verify_android_release_artifact_on_host() {
  local android_root="$1"
  local apk="${android_root}/release/WASM-Agent-arm64.apk"
  local sdk_root="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-${android_root}/.android-sdk}}"
  local apksigner=""
  if [[ -n "${APKSIGNER_BIN:-}" && -x "${APKSIGNER_BIN}" ]]; then
    apksigner="${APKSIGNER_BIN}"
  elif [[ -d "${sdk_root}/build-tools" ]]; then
    apksigner="$(find "${sdk_root}/build-tools" -maxdepth 2 -type f -name apksigner -perm -u+x 2>/dev/null | sort -V | tail -1)"
  fi
  if [[ -z "${apksigner}" ]]; then
    echo "horc build android-apk: host apksigner not found; skipping host signature verification" >&2
    return 0
  fi
  echo "horc build android-apk: host verifying APK signature with ${apksigner}"
  "${apksigner}" verify --verbose "${apk}"
}

android_fast_docker_script() {
  android_docker_common_script
  cat <<'TXT'
read -r -a tasks <<< "${HORC_ANDROID_FAST_TASKS:-:app:assembleDebug}"
args=("${GRADLE_BIN}")
if [[ "${HORC_ANDROID_GRADLE_DAEMON:-}" != "1" ]]; then
  args+=("--no-daemon")
fi
args+=("--build-cache" "--parallel" "-Dkotlin.compiler.execution.strategy=in-process")
if [[ "${HORC_ANDROID_CONFIGURATION_CACHE:-}" == "1" ]]; then
  args+=("--configuration-cache")
fi
args+=("${tasks[@]}")
echo "horc build android-fast: ${args[*]}"
"${args[@]}"
TXT
}

run_docker_android_fast_build() {
  local root="$1"
  local android_root="$2"
  local image="${HORC_ANDROID_DOCKER_IMAGE:-ghcr.io/cirruslabs/android-sdk:35}"
  local host_arch
  local host_uid
  local host_gid
  local docker_status=0
  host_arch="$(canonical_host_arch)"
  ensure_docker_available || exit 2
  if [[ "${host_arch}" == "aarch64" ]]; then
    ensure_docker_amd64_emulation "${HORC_ANDROID_BUILD_MODE:-auto}" "${host_arch}" || exit 2
  fi
  mkdir -p "${android_root}/.gradle-home" "${android_root}/.gradle-dist"
  host_uid="$(id -u 2>/dev/null || true)"
  host_gid="$(id -g 2>/dev/null || true)"
  echo "horc build android-fast: starting Docker Android builder..."
  echo "horc build android-fast: docker ${image} --platform linux/amd64"
  docker run --rm \
    --platform linux/amd64 \
    -e HORC_ANDROID_GRADLE_VERSION="${HORC_ANDROID_GRADLE_VERSION:-8.9}" \
    -e HORC_ANDROID_LOG_LABEL="horc build android-fast" \
    -e HORC_ANDROID_FAST_TASKS="${HORC_ANDROID_FAST_TASKS:-:app:assembleDebug}" \
    -e HORC_ANDROID_GRADLE_DAEMON="${HORC_ANDROID_GRADLE_DAEMON:-0}" \
    -e HORC_ANDROID_CONFIGURATION_CACHE="${HORC_ANDROID_CONFIGURATION_CACHE:-0}" \
    -e WASM_AGENT_ANDROID_VOSK_MODEL_DIR="${WASM_AGENT_ANDROID_VOSK_MODEL_DIR:-}" \
    -e HORC_HOST_UID="${host_uid}" \
    -e HORC_HOST_GID="${host_gid}" \
    -v "${root}:${root}" \
    -w "${android_root}" \
    "${image}" \
    bash -lc "$(android_fast_docker_script)" || docker_status=$?
  if [[ "${docker_status}" -ne 0 ]]; then
    echo "horc build android-fast: Docker Android builder exited with status ${docker_status}" >&2
    return "${docker_status}"
  fi
}

android_vosk_expectation() {
  local android_root="$1"
  local model_dir="${WASM_AGENT_ANDROID_VOSK_MODEL_DIR:-${android_root}/build/generated/asr/vosk-model}"
  if [[ -d "${model_dir}" ]] && find "${model_dir}" -type f -print -quit 2>/dev/null | grep -q .; then
    printf '%s\n' "--expect-vosk-model"
  else
    printf '%s\n' "--expect-no-vosk-model"
  fi
}

inspect_android_fast_apks() {
  local root="$1"
  local android_root="$2"
  local expect_vosk
  local inspect_script="${root}/native/android/scripts/inspect-wake-apk.sh"
  local -a apks=()
  if [[ "${HORC_ANDROID_FAST_INSPECT_APK:-1}" == "0" ]]; then
    echo "horc build android-fast: skipping APK wake asset inspection"
    return 0
  fi
  if [[ ! -x "${inspect_script}" ]]; then
    echo "horc build android-fast: wake APK inspector not found or not executable: ${inspect_script}" >&2
    return 0
  fi
  mapfile -t apks < <(find "${android_root}/app/build/outputs/apk" -type f -name "*.apk" -print 2>/dev/null | sort)
  if [[ ${#apks[@]} -eq 0 ]]; then
    echo "horc build android-fast: no APK outputs found for wake asset inspection" >&2
    return 0
  fi
  expect_vosk="$(android_vosk_expectation "${android_root}")"
  echo "horc build android-fast: inspecting APK wake assets (${expect_vosk})"
  for apk in "${apks[@]}"; do
    "${inspect_script}" "${apk}" --expect-no-model "${expect_vosk}"
  done
}

build_android_fast() {
  local root
  local android_root="${HERMES_WASM_AGENT_ANDROID_ROOT:-}"
  local requested_mode="${HORC_ANDROID_BUILD_MODE:-auto}"
  local build_mode
  local gradle_bin
  local benchmark_started_ms
  local build_status=0
  local fast_tasks="${HORC_ANDROID_FAST_TASKS:-:app:assembleDebug}"
  root="$(repo_root)"
  android_root="${android_root:-${root}/native/android}"

  if [[ ! -f "${android_root}/app/build.gradle" ]]; then
    echo "horc build android-fast: Android native project not found: ${android_root}" >&2
    echo "set HERMES_WASM_AGENT_ANDROID_ROOT to override" >&2
    exit 2
  fi

  acquire_build_lock "${android_root}/app" "Android"
  benchmark_started_ms="$(android_now_ms)"
  echo "horc build android-fast: host $(host_kernel) $(canonical_host_arch), target debug-apk"
  build_mode="$(select_android_build_mode "${requested_mode}" "${android_root}")"
  echo "horc build android-fast: selected mode ${build_mode}"
  set +e
  case "${build_mode}" in
    local)
      if ! android_evaluate_local_tools "${android_root}"; then
        android_local_failure_hint
        build_status=2
      else
        gradle_bin="$(android_gradle_path "${android_root}")"
        (
          cd "${android_root}"
          export GRADLE_USER_HOME="${GRADLE_USER_HOME:-${android_root}/.gradle-home}"
          export ANDROID_HOME="${ANDROID_HOME:-$(android_sdk_root "${android_root}")}"
          export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME}}"
          export QEMU_LD_PREFIX="${QEMU_LD_PREFIX:-${android_root}/.android-sdk-qemu-root}"
          read -r -a HORC_ANDROID_FAST_TASK_ARRAY <<< "${fast_tasks}"
          gradle_args=("${gradle_bin}")
          if ! is_truthy "${HORC_ANDROID_GRADLE_DAEMON:-}"; then
            gradle_args+=("--no-daemon")
          fi
          gradle_args+=("--build-cache" "--parallel" "-Dkotlin.compiler.execution.strategy=in-process")
          if is_truthy "${HORC_ANDROID_CONFIGURATION_CACHE:-}"; then
            gradle_args+=("--configuration-cache")
          fi
          gradle_args+=("${HORC_ANDROID_FAST_TASK_ARRAY[@]}")
          echo "horc build android-fast: ${gradle_args[*]}"
          "${gradle_args[@]}"
        )
        build_status=$?
      fi
      ;;
    docker)
      run_docker_android_fast_build "${root}" "${android_root}"
      build_status=$?
      ;;
    *)
      build_fail "internal error: unsupported Android build mode ${build_mode}"
      ;;
  esac
  set -e

  if [[ "${build_status}" -eq 0 ]]; then
    echo "horc build android-fast: APK outputs:"
    find "${android_root}/app/build/outputs/apk" -type f -name "*.apk" -print 2>/dev/null | sort || true
    inspect_android_fast_apks "${root}" "${android_root}" || build_status=$?
    echo "horc build android-fast: debug build only; no release feed or runtime proof was produced"
  fi
  record_android_build_benchmark "${root}" "${android_root}" "android-fast" "${build_mode}" "${build_status}" "${benchmark_started_ms}" "${fast_tasks}"
  if [[ "${build_status}" -ne 0 ]]; then
    exit "${build_status}"
  fi
}

build_android_native_release() {
  local root
  local android_root="${HERMES_WASM_AGENT_ANDROID_ROOT:-}"
  local release_script
  local requested_mode="${HORC_ANDROID_BUILD_MODE:-auto}"
  local build_mode
  local benchmark_started_ms
  local build_status=0
  local release_tasks=":app:assembleRelease"
  root="$(repo_root)"
  android_root="${android_root:-${root}/native/android}"
  release_script="${android_root}/scripts/release-android.js"

  if [[ ! -f "${android_root}/app/build.gradle" || ! -f "${release_script}" ]]; then
    echo "horc build android-apk: Android native project not found: ${android_root}" >&2
    echo "set HERMES_WASM_AGENT_ANDROID_ROOT to override" >&2
    exit 2
  fi

  acquire_build_lock "${android_root}/app" "Android"
  require_command node "Install Node.js so horc can run the Android release promoter."
  benchmark_started_ms="$(android_now_ms)"
  echo "horc build android-apk: host $(host_kernel) $(canonical_host_arch), target android-apk"
  build_mode="$(select_android_build_mode "${requested_mode}" "${android_root}")"
  echo "horc build android-apk: selected mode ${build_mode}"
  if [[ "${HORC_ANDROID_RUN_UNIT_TESTS:-0}" == "1" ]]; then
    release_tasks=":app:testReleaseUnitTest ${release_tasks}"
  fi
  set +e
  case "${build_mode}" in
    local)
      if ! android_evaluate_local_tools "${android_root}"; then
        android_local_failure_hint
        build_status=2
      else
        echo "horc build android-apk: cd ${android_root} && node scripts/release-android.js"
        (
          cd "${android_root}"
          export GRADLE_USER_HOME="${GRADLE_USER_HOME:-${android_root}/.gradle-home}"
          export ANDROID_HOME="${ANDROID_HOME:-$(android_sdk_root "${android_root}")}"
          export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME}}"
          export QEMU_LD_PREFIX="${QEMU_LD_PREFIX:-${android_root}/.android-sdk-qemu-root}"
          export HORC_ANDROID_KOTLIN_IN_PROCESS="${HORC_ANDROID_KOTLIN_IN_PROCESS:-1}"
          export WASM_AGENT_ANDROID_SKIP_LINT="${WASM_AGENT_ANDROID_SKIP_LINT:-1}"
          android_release_identity_env
          node scripts/release-android.js
        )
        build_status=$?
      fi
      ;;
    docker)
      run_docker_android_release "${root}" "${android_root}"
      build_status=$?
      ;;
    *)
      build_fail "internal error: unsupported Android build mode ${build_mode}"
      ;;
  esac
  set -e

  if [[ "${build_status}" -eq 0 && ( -x "${android_root}/scripts/verify-launcher-icon.py" || -f "${android_root}/scripts/verify-launcher-icon.py" ) ]]; then
    echo "horc build android-apk: verifying launcher icon resources"
    (cd "${root}" && python3 "${android_root}/scripts/verify-launcher-icon.py") || build_status=$?
  fi

  if [[ "${build_status}" -eq 0 ]]; then
    [[ -f "${android_root}/release/WASM-Agent-arm64.apk" ]] || build_status=2
    if [[ "${build_status}" -eq 0 ]]; then
      [[ -f "${android_root}/release/WASM-Agent-universal.apk" ]] || build_status=2
    fi
    if [[ "${build_status}" -eq 0 ]]; then
      verify_android_release_artifact_on_host "${android_root}" || build_status=$?
    fi
    if [[ "${build_status}" -eq 0 ]]; then
      if should_generate_native_release_feed; then
        generate_native_release_feed "${root}" "horc build android-apk" || build_status=$?
      else
        echo "horc build android-apk: skipping native release feed generation for parallel build join"
      fi
    fi
  fi
  if [[ "${build_status}" -eq 0 ]]; then
    echo "horc build android-apk: APK artifacts ready:"
    echo "horc build android-apk:   ${android_root}/release/WASM-Agent-arm64.apk"
    echo "horc build android-apk:   ${android_root}/release/WASM-Agent-universal.apk"
  else
    echo "horc build android-apk: failed with status ${build_status}" >&2
  fi
  record_android_build_benchmark "${root}" "${android_root}" "android" "${build_mode}" "${build_status}" "${benchmark_started_ms}" "${release_tasks}"
  if [[ "${build_status}" -ne 0 ]]; then
    exit "${build_status}"
  fi
}

build_all_native_release() {
  local root
  local win_pid
  local android_pid
  local win_status=0
  local android_status=0
  root="$(repo_root)"
  echo "horc build all: starting Windows and Android builds in parallel"
  (export HORC_GENERATE_NATIVE_RELEASE_FEED=0; build_windows_native_release) &
  win_pid=$!
  (export HORC_GENERATE_NATIVE_RELEASE_FEED=0; build_android_native_release) &
  android_pid=$!

  set +e
  wait "${win_pid}"
  win_status=$?
  wait "${android_pid}"
  android_status=$?
  set -e

  if [[ "${win_status}" -ne 0 || "${android_status}" -ne 0 ]]; then
    echo "horc build all: Windows status=${win_status}, Android status=${android_status}" >&2
    exit 1
  fi

  generate_native_release_feed "${root}" "horc build all"
  echo "horc build all: target matrix"
  (cd "${root}" && node <<'NODE'
const fs = require("fs");
const path = require("path");
const manifestPath = path.join("plugins", "wasm-agent", "public", "native", "releases", "latest.json");
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const rows = [];
for (const [platform, byArch] of Object.entries(manifest.artifacts || {})) {
  for (const [arch, artifact] of Object.entries(byArch || {})) {
    if (!artifact || typeof artifact !== "object") continue;
    rows.push({
      target: `${platform}-${arch}`,
      mode: artifact.updateMode || artifact.kind || "",
      path: artifact.path || artifact.url || "",
      sha256: artifact.sha256 || "-",
      status: artifact.url ? "published" : "missing",
      runtime: artifact.runtimeProofStatus || "unknown",
    });
  }
}
console.log("target\tbuild mode\tartifact path/url\tsha256\tstatus\truntime proof");
for (const row of rows) {
  console.log(`${row.target}\t${row.mode}\t${row.path}\t${row.sha256}\t${row.status}\t${row.runtime}`);
}
NODE
  )
}

resolve_name_and_exec() {
  local action="$1"
  shift

  if [[ "${1:-}" == "--name" ]]; then
    exec_manager "${action}" "$@"
  fi

  local name="${DEFAULT_NODE}"
  if [[ $# -gt 0 && "${1}" != --* ]]; then
    name="${1}"
    shift
  fi

  exec_manager "${action}" --name "${name}" "$@"
}

resolve_name_and_run() {
  local action="$1"
  shift

  if [[ "${1:-}" == "--name" ]]; then
    manager "${action}" "$@"
    return
  fi

  local name="${DEFAULT_NODE}"
  if [[ $# -gt 0 && "${1}" != --* ]]; then
    name="${1}"
    shift
  fi

  manager "${action}" --name "${name}" "$@"
}

confirm_delete() {
  local name="$1"
  if [[ "${HERMES_HORC_ASSUME_YES:-}" == "1" || "${HERMES_HORC_ASSUME_YES:-}" == "true" ]]; then
    return 0
  fi
  if [[ ! -t 0 ]]; then
    echo "horc delete: confirmation required. Re-run interactively and type: DELETE ${name}" >&2
    exit 2
  fi

  echo "horc delete will stop/remove the container and delete:"
  echo "  /local/agents/envs/${name}.env"
  echo "  /local/agents/nodes/${name}/"
  echo "Shared data, cron, and logs are preserved; use 'horc purge-node ${name}' for full cleanup."
  printf 'Type "DELETE %s" to continue: ' "${name}" >&2
  local answer
  IFS= read -r answer
  if [[ "${answer}" != "DELETE ${name}" ]]; then
    echo "horc delete: aborted" >&2
    exit 130
  fi
}

resolve_delete_and_exec() {
  local name="${DEFAULT_NODE}"
  local -a passthrough=()

  while [[ $# -gt 0 ]]; do
    case "${1}" in
      --name)
        if [[ $# -lt 2 ]]; then
          echo "horc: delete --name requires a value" >&2
          exit 2
        fi
        name="${2}"
        passthrough+=("--name" "${2}")
        shift 2
        ;;
      --yes|-y)
        HERMES_HORC_ASSUME_YES=1
        shift
        ;;
      --*)
        passthrough+=("${1}")
        shift
        ;;
      *)
        name="${1}"
        passthrough+=("${1}")
        shift
        ;;
    esac
  done

  confirm_delete "${name}"
  exec_manager delete "${passthrough[@]}"
}

discover_restart_nodes() {
  local env_root="${HERMES_AGENTS_ENVS_ROOT:-/local/agents/envs}"
  local nodes_root="${HERMES_AGENTS_NODES_ROOT:-/local/agents/nodes}"
  declare -A seen=()
  local ordered=()

  if [[ -d "${env_root}" ]]; then
    while IFS= read -r file; do
      local name="${file%.env}"
      [[ -z "${name}" ]] && continue
      if [[ -z "${seen[${name}]:-}" ]]; then
        seen["${name}"]=1
        ordered+=("${name}")
      fi
    done < <(find "${env_root}" -maxdepth 1 -type f -name '*.env' -printf '%f\n' | sort)
  fi

  if [[ -d "${nodes_root}" ]]; then
    while IFS= read -r name; do
      [[ -z "${name}" ]] && continue
      if [[ -z "${seen[${name}]:-}" ]]; then
        seen["${name}"]=1
        ordered+=("${name}")
      fi
    done < <(find "${nodes_root}" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
  fi

  if [[ ${#ordered[@]} -eq 0 ]]; then
    ordered=("${DEFAULT_NODE}")
  fi

  printf '%s\n' "${ordered[@]}"
}

restart_all_nodes() {
  local -a start_args=("$@")
  local -a nodes=()
  mapfile -t nodes < <(discover_restart_nodes)

  local -a workers=()
  local orchestrator_present=0
  for name in "${nodes[@]}"; do
    if [[ "${name}" == "orchestrator" ]]; then
      orchestrator_present=1
    else
      workers+=("${name}")
    fi
  done

  for name in "${workers[@]}"; do
    manager stop --name "${name}" >/dev/null || true
  done
  if [[ "${orchestrator_present}" -eq 1 ]]; then
    manager stop --name orchestrator >/dev/null || true
  fi

  if [[ "${orchestrator_present}" -eq 1 ]]; then
    manager start --name orchestrator "${start_args[@]}"
  fi
  for name in "${workers[@]}"; do
    manager start --name "${name}" "${start_args[@]}"
  done
}

space_usage() {
  cat <<'TXT'
horc space — wasm-agent workspace

Usage:
  horc space start
  horc space stop
  horc space restart
  horc space status
  horc space backup

Behavior:
  - Starts wasm-agent PWA on http://127.0.0.1:8877.
  - Starts the wasm-agent-owned Hermes bridge on http://127.0.0.1:8790.
  - Restarts by stopping the workspace and starting it again.
  - Backs up wasm-agent app/private state with `horc space backup`.
TXT
}

space_plugin_dir() {
  local root="${HERMES_ORCHESTRATOR_ROOT:-/local}"
  printf '%s\n' "${HERMES_WASM_AGENT_PLUGIN_DIR:-${root}/plugins/wasm-agent}"
}

space_app_pid_file() {
  local state_dir="${HERMES_WASM_AGENT_STATE_DIR:-/local/plugins/wasm-agent/state}"
  printf '%s\n' "${HERMES_WASM_AGENT_PID_FILE:-${state_dir}/wasm-agent.pid}"
}

space_bridge_pid_file() {
  local state_dir="${HERMES_WASM_AGENT_STATE_DIR:-/local/plugins/wasm-agent/state}"
  local bridge_state_dir="${HERMES_WASM_AGENT_BRIDGE_STATE_DIR:-${state_dir}/bridge}"
  printf '%s\n' "${HERMES_WASM_AGENT_BRIDGE_PID_FILE:-${bridge_state_dir}/bridge.pid}"
}

space_kill_port() {
  local port="${1}"
  local pids=""

  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${port}/tcp" >/dev/null 2>&1 || true
    return
  fi

  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)"
  elif command -v ss >/dev/null 2>&1; then
    pids="$(ss -ltnp "sport = :${port}" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | sort -u)"
  fi

  if [[ -n "${pids}" ]]; then
    while IFS= read -r pid; do
      [[ -z "${pid}" ]] && continue
      kill "${pid}" 2>/dev/null || true
    done <<< "${pids}"
    sleep 1
    while IFS= read -r pid; do
      [[ -z "${pid}" ]] && continue
      kill -9 "${pid}" 2>/dev/null || true
    done <<< "${pids}"
  fi
}

space_start() {
  local plugin_dir
  plugin_dir="$(space_plugin_dir)"
  local start_script="${plugin_dir}/scripts/start_wasm_agent.sh"

  if [[ ! -x "${start_script}" ]]; then
    echo "horc space: start script not found: ${start_script}" >&2
    exit 1
  fi

  echo "horc space: starting wasm-agent workspace"
  "${start_script}"
  echo "horc space: browser target is localhost:${HERMES_WASM_AGENT_PORT:-8877}"
}

space_stop() {
  local plugin_dir
  plugin_dir="$(space_plugin_dir)"
  local stop_script="${plugin_dir}/scripts/stop_wasm_agent.sh"

  if [[ ! -x "${stop_script}" ]]; then
    echo "horc space: stop script not found: ${stop_script}" >&2
    exit 1
  fi

  "${stop_script}"
}

space_restart() {
  echo "horc space: restarting wasm-agent workspace"
  space_stop
  space_kill_port "${HERMES_WASM_AGENT_PORT:-8877}"
  space_kill_port "${HERMES_WASM_AGENT_BRIDGE_PORT:-8790}"
  space_start
}

space_status() {
  local app_pid_file
  app_pid_file="$(space_app_pid_file)"
  local bridge_pid_file
  bridge_pid_file="$(space_bridge_pid_file)"
  local port="${HERMES_WASM_AGENT_PORT:-8877}"
  local bridge_port="${HERMES_WASM_AGENT_BRIDGE_PORT:-8790}"
  local ok=0
  if [[ -s "${app_pid_file}" ]]; then
    local pid
    pid="$(cat "${app_pid_file}")"
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      echo "wasm-agent running pid=${pid} url=http://127.0.0.1:${port}"
      ok=1
    fi
  fi
  if [[ -s "${bridge_pid_file}" ]]; then
    local bridge_pid
    bridge_pid="$(cat "${bridge_pid_file}")"
    if [[ -n "${bridge_pid}" ]] && kill -0 "${bridge_pid}" 2>/dev/null; then
      echo "wasm-agent bridge running pid=${bridge_pid} url=http://127.0.0.1:${bridge_port}"
      ok=1
    fi
  fi
  if [[ "${ok}" -eq 1 ]]; then
    exit 0
  fi
  echo "horc space is not running"
  exit 1
}

ACTION="${1:-help}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "${ACTION}" in
  build)
    SUBACTION="${1:-win-x64-prod}"
    if [[ $# -gt 0 ]]; then
      shift
    fi
    case "${SUBACTION}" in
      help|-h|--help)
        build_usage
        ;;
      doctor|--doctor)
        if [[ $# -gt 0 ]]; then
          echo "horc build doctor: unexpected arguments: $*" >&2
          build_usage >&2
          exit 2
        fi
        build_doctor
        ;;
      prepare-docker|docker-prepare|prepare-builder)
        if [[ $# -gt 0 ]]; then
          echo "horc build prepare-docker: unexpected arguments: $*" >&2
          build_usage >&2
          exit 2
        fi
        prepare_docker_builder_image
        ;;
      win|windows|win-x64|win-x64-prod|native|wasm-agent|wasm-agent-native)
        if [[ $# -gt 0 ]]; then
          echo "horc build: unexpected arguments: $*" >&2
          build_usage >&2
          exit 2
        fi
        build_windows_native_release
        ;;
      win-fast|windows-fast|win-debug|wasm-agent-win-fast|wasm-agent-windows-fast)
        if [[ $# -gt 0 ]]; then
          echo "horc build win-fast: unexpected arguments: $*" >&2
          build_usage >&2
          exit 2
        fi
        build_windows_fast
        ;;
      android|android-apk|apk|wasm-agent-android)
        if [[ $# -gt 0 ]]; then
          echo "horc build android-apk: unexpected arguments: $*" >&2
          build_usage >&2
          exit 2
        fi
        build_android_native_release
        ;;
      android-fast|android-debug|apk-fast|wasm-agent-android-fast)
        if [[ $# -gt 0 ]]; then
          echo "horc build android-fast: unexpected arguments: $*" >&2
          build_usage >&2
          exit 2
        fi
        build_android_fast
        ;;
      all|native-all|wasm-agent-native-all)
        if [[ $# -gt 0 ]]; then
          echo "horc build all: unexpected arguments: $*" >&2
          build_usage >&2
          exit 2
        fi
        build_all_native_release
        ;;
      *)
        echo "horc build: unknown target '${SUBACTION}'" >&2
        build_usage >&2
        exit 2
        ;;
    esac
    ;;
  simulate)
    SUBACTION="${1:-help}"
    if [[ $# -gt 0 ]]; then
      shift
    fi
    case "${SUBACTION}" in
      help|-h|--help)
        simulate_usage
        ;;
      web|android|windows|all)
        run_app_simulator "${SUBACTION}" "$@"
        ;;
      *)
        echo "horc simulate: unknown target '${SUBACTION}'" >&2
        simulate_usage >&2
        exit 2
        ;;
    esac
    ;;
  space)
    SUBACTION="${1:-help}"
    if [[ $# -gt 0 ]]; then
      shift
    fi
    case "${SUBACTION}" in
      start)
        space_start "$@"
        ;;
      stop)
        space_stop "$@"
        ;;
      restart)
        space_restart "$@"
        ;;
      status)
        space_status "$@"
        ;;
      backup)
        exec_manager space-backup "$@"
        ;;
      help|-h|--help)
        space_usage
        ;;
      *)
        echo "horc space: unknown command '${SUBACTION}'" >&2
        space_usage >&2
        exit 2
        ;;
    esac
    ;;
  start|status|stop)
    resolve_name_and_exec "${ACTION}" "$@"
    ;;
  delete)
    resolve_delete_and_exec "$@"
    ;;
  purge-node)
    SUBACTION="${1:-}"
    if [[ "${SUBACTION}" == "confirm" ]]; then
      if [[ $# -lt 2 ]]; then
        echo "horc: purge-node confirm requires <request-id>" >&2
        usage >&2
        exit 2
      fi
      REQUEST_ID="${2}"
      shift 2
      exec_manager purge-node-confirm --run-id "${REQUEST_ID}" "$@"
    fi
    TARGET_NAME="${1:-}"
    if [[ -z "${TARGET_NAME}" || "${TARGET_NAME}" == --* ]]; then
      echo "horc: purge-node requires <name>" >&2
      usage >&2
      exit 2
    fi
    shift
    exec_manager purge-node-request --name "${TARGET_NAME}" "$@"
    ;;
  logs)
    if [[ "${1:-}" == "clean" ]]; then
      shift
      if [[ $# -eq 0 ]]; then
        exec_manager logs --clean --all
      fi
      if [[ "${1:-}" == "all" || "${1:-}" == "*" ]]; then
        shift
        exec_manager logs --clean --all "$@"
      fi
      if [[ "${1:-}" == --* ]]; then
        exec_manager logs --clean "$@"
      fi
      NAME="${1}"
      shift
      exec_manager logs --clean --name "${NAME}" "$@"
    fi
    resolve_name_and_exec logs "$@"
    ;;
  restart)
    if [[ "${1:-}" == "--name" ]]; then
      resolve_name_and_run stop "$@" >/dev/null
      resolve_name_and_exec start "$@"
    fi
    if [[ $# -eq 0 || "${1:-}" == "all" || "${1:-}" == "--all" || "${1:-}" == --* ]]; then
      if [[ "${1:-}" == "all" || "${1:-}" == "--all" ]]; then
        shift
      fi
      restart_all_nodes "$@"
      exit 0
    fi
    resolve_name_and_run stop "$@" >/dev/null
    resolve_name_and_exec start "$@"
    ;;
  update)
    SUBACTION="${1:-}"
    if [[ $# -gt 0 ]]; then
      shift
    fi
    if [[ -z "${SUBACTION}" || "${SUBACTION}" == "help" || "${SUBACTION}" == "--help" || "${SUBACTION}" == "-h" ]]; then
      update_usage
      exit 0
    fi
    case "${SUBACTION}" in
      all)
        exec_manager update-all "$@"
        ;;
      node)
        TARGET_NAME="${1:-}"
        if [[ -z "${TARGET_NAME}" || "${TARGET_NAME}" == --* ]]; then
          echo "horc: update node requires <name>" >&2
          update_usage >&2
          exit 2
        fi
        shift
        exec_manager update-node --name "${TARGET_NAME}" "$@"
        ;;
      *)
        echo "horc: unknown update subcommand '${SUBACTION}'" >&2
        update_usage >&2
        exit 2
        ;;
    esac
    ;;
  agent|test|test-update)
    LEGACY_ACTION="${ACTION}"
    if [[ "${ACTION}" == "agent" || "${ACTION}" == "test" ]]; then
      LEGACY_ACTION+=" ${1:-}"
    fi
    echo "horc: legacy command '${LEGACY_ACTION}' has been removed." >&2
    echo "use 'horc update help' for the supported update commands." >&2
    exit 2
    ;;
  update-all|update-node)
    # Internal actions are intentionally not user-facing through horc.
    echo "horc: use 'horc update help', 'horc update all', or 'horc update node <name>'." >&2
    exit 2
    ;;
  backup)
    MODE="${1:-all}"
    if [[ $# -gt 0 ]]; then
      shift
    fi
    case "${MODE}" in
      all)
        exec_manager backup --all "$@"
        ;;
      node)
        NAME="${1:-}"
        if [[ -z "${NAME}" ]]; then
          echo "horc: backup node requires <name>" >&2
          usage >&2
          exit 2
        fi
        shift
        exec_manager backup --name "${NAME}" "$@"
        ;;
      *)
        # Convenience alias: `horc backup <name>`
        exec_manager backup --name "${MODE}" "$@"
        ;;
    esac
    ;;
  restore)
    BACKUP_PATH="${1:-}"
    if [[ -z "${BACKUP_PATH}" ]]; then
      echo "horc: restore requires <path>" >&2
      usage >&2
      exit 2
    fi
    shift
    exec_manager restore --path "${BACKUP_PATH}" "$@"
    ;;
  profile)
    echo "horc: profile clone has been retired from operator use." >&2
    echo "use 'horc update help' for supported fleet update commands." >&2
    exit 2
    ;;
  help|-h|--help)
    usage
    exit 0
    ;;
  *)
    echo "horc: unknown command '${ACTION}'" >&2
    usage >&2
    exit 2
    ;;
esac
