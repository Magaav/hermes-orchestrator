# horc Command Reference

`horc` is the Hermes Orchestrator CLI for lifecycle, logs, backup/restore, and simplified fleet updates.

## Defaults

- Default node for most lifecycle commands: `orchestrator`
- Backup destination: `/local/backups`
- Canonical update artifact root: `/local/logs/update`

## Lifecycle Commands

```bash
horc start [name] [--image IMAGE]
horc status [name]
horc stop [name]
horc restart [all|name] [--image IMAGE]
horc delete [name] [--yes]
horc purge-node <name>
horc purge-node confirm <request-id> --token TOKEN
```

`horc delete <name>` asks for confirmation, removes the node container, and deletes
`/local/agents/envs/<name>.env` plus `/local/agents/nodes/<name>/`. Shared node data,
cron, and logs are preserved; use `horc purge-node <name>` for full cleanup.

`horc purge-node <name>` is a destructive two-step cleanup. The first command
creates a purge request; the second confirms it with the request id and token.

## Logs Commands

```bash
horc logs [name] [--lines N]
horc logs clean [name|all]
```

## Backup and Restore

```bash
horc backup all
horc backup node <name>
horc backup <name>
horc space backup
horc restore <path>
```

`horc space backup` is the current wasm-agent-cloud proof-of-concept backup. It
archives the active wasm-agent state root into `/local/backups` with a manifest
under `wasm-agent-cloud/<instance>/backup-manifest.json`. In cloud mode it reads
`<HERMES_WASM_AGENT_CLOUD_STATE_ROOT>/state` when that directory exists; then it
falls back to `HERMES_WASM_AGENT_STATE_DIR`, and finally to the local
development root `/local/plugins/wasm-agent/state`. Browser caches, logs, pid
files, symlinks, and other noisy runtime files are excluded.

## Update Commands

```bash
horc update [help]
horc update all [--force]
horc update node <name> [--force]
```

## Build Commands

```bash
horc build win
horc build android
horc build all
horc build prepare-docker
horc build doctor
horc build --doctor
horc simulate web
horc simulate android [--device|--emulator|--local-report PATH|--voice-wake FIXTURE]
horc simulate windows
horc simulate all
```

`horc build win` builds the Windows 11 x64 wasm-agent Electron/NSIS installer. The
underlying release command still runs from `native/windows/src`:

```bash
npm run release:win:x64:prod
```

The release script cleans stale output, regenerates production native defaults,
builds the Windows x64 NSIS installer, extracts the final artifact, and verifies
that the packaged app is cloud-backed by default. After it returns, `horc build win`
checks the unpacked executable, `resources/app.asar`, and the final installer,
prints the first 80 `app.asar` entries, and writes
`/local/native/windows/release/horc-build-manifest.json`.

`horc build android` builds only the Android APK lane. In `auto` mode it uses
the local lane only when Java, Gradle, an Android SDK, and the actual Android
resource compiler (`aapt2 version`) all execute on the current CPU. If local
Android tooling is present but AAPT2 cannot run, such as an ARM host with an
x86_64 AAPT2 binary and no loader, `auto` selects the existing Docker
linux/amd64 Android SDK builder instead. The Docker lane persists Gradle caches
under `native/android/.gradle-*`. It runs `native/android/scripts/release-android.js`,
generates a local sideload signing key if no signing environment is provided,
verifies the signed release APK with `apksigner`, rejects production APKs that
contain localhost backend literals, and promotes the APKs to:

- `/local/native/android/release/WASM-Agent-universal.apk`
- `/local/native/android/release/WASM-Agent-arm64.apk`

The Docker Android lane sets `HORC_ANDROID_KOTLIN_IN_PROCESS=1` unless
overridden, so the release script passes Kotlin's in-process compiler strategy
to Gradle and avoids Kotlin daemon handshakes under linux/amd64 emulation.

The APK sidecars and `release-manifest.json` let `/native/resolve` and
`/native/download` expose the Android artifact through Home `Go Native` when the
file exists. After a successful Android release, `horc build android` also runs
`native/android/scripts/verify-launcher-icon.py` when present, so the launcher
icon remains standardized on the shared WA artwork. Build success is not runtime
proof; use `horc simulate android --device` for installed-app behavior. `horc
build all` explicitly runs the Windows lane first and then the Android APK lane.
When both concrete lanes succeed, it generates the local update feed at
`/local/plugins/wasm-agent/public/native/releases/latest.json`, copies published
artifacts under `public/native/releases/{windows,android}/`, and prints a
matrix with target, build mode, artifact path/URL, SHA-256, status, and runtime
proof status. The local server serves the feed at `/native/releases/latest.json`
and Android APKs at `/native/releases/android/WASM-Agent-{arm64,universal}.apk`.

The Go Native modal checks `/native/releases/latest.json` and compares it with
metadata embedded in the current client. Windows uses a guided installer update
unless electron-builder updater metadata is wired later. Android sideload APKs
are guided updates only: the app must verify SHA-256, preserve package
name/signing key, require a greater `versionCode`, and hand off to Android's
package installer. Android may require the user to allow "install unknown apps"
and always requires OS confirmation. Web/PWA updates mean service-worker/cache
refresh and reload. Do not treat build proof as runtime proof.

Build trust lanes:

- Native Windows: preferred production path, marked `trusted_production: true`.
- Linux x86_64 with Wine/NSIS: supported CI cross-build, marked
  `requires_windows_smoke_test: true`.
- Linux aarch64 with Docker `--platform linux/amd64`: supported experimental
  cross-build, marked `requires_windows_smoke_test: true`. If amd64 Docker
  emulation is missing, `horc build` tries to register QEMU binfmt with
  `docker run --privileged --rm tonistiigi/binfmt --install amd64`, then
  re-tests before starting the Wine builder. In `auto` mode, if QEMU can run
  amd64 containers but the amd64 Electron Builder helper crashes under
  emulation, `horc build` falls back to a Linux ARM64 native NSIS build with
  Windows executable resource editing disabled and marks the manifest mode as
  `linux-arm64-native-nsis-no-rcedit`.
- Linux aarch64 direct Wine: debug-only, requires
  `HORC_ALLOW_CROSS_WIN_BUILD=1`, and may hang in Windows resource editing.

For faster repeated Linux ARM64 Docker builds, run the one-time prepared image
step:

```bash
horc build prepare-docker
```

This builds `horc/electron-builder-wine-nsis:jammy` with NSIS and `unar`
preinstalled. Future `horc build` runs auto-use that local image when
`HORC_DOCKER_IMAGE` is unset, avoiding repeated `apt-get update` and package
installs inside each disposable builder container.

`horc build doctor` prints host OS/arch, Docker availability, Docker user
permission, amd64 binfmt status, Wine builder image pullability, Android
selected build mode, Java availability, Gradle path, Android SDK path, AAPT2
path, AAPT2 runnable status, Android Docker image, expected Windows build mode,
and exact remediation commands for missing prerequisites. On ARM hosts where the
Android Docker lane needs linux/amd64 emulation and binfmt is missing, run:

```bash
sudo docker run --privileged --rm tonistiigi/binfmt --install amd64
docker run --rm --platform linux/amd64 alpine:3.20 uname -m
```

## Simulation Commands

```bash
horc simulate web
horc simulate android --emulator
horc simulate android --device
horc simulate android --local-report reports/sim/android/latest/result.json
horc simulate android --voice-wake fixture-hermes-command.wav
horc simulate windows
horc simulate all
```

`horc simulate web` uses Playwright to verify the wasm-agent PWA/browser brain at
runtime. It defaults to `http://127.0.0.1:8877/home` when reachable, or uses
`WASM_AGENT_SIM_URL` when set. The web simulator always adds Android shell query
mode:

```text
native=android&shell=android-webview&buildId=playwright-sim
```

The web simulator verifies that the app loads, Android native shell mode is
detected, Go Native/native-desktop install prompts are hidden, visible UI does
not leak browser/native-install placeholder text, and renderer diagnostics
confirm the shell mode. It captures screenshots, redacted console logs, redacted
network failures, and failure-only Playwright trace/video artifacts.

Every simulator run writes:

```text
reports/sim/<platform>/latest/result.json
reports/sim/<platform>/latest/summary.md
```

The simulator lifecycle is `boot -> observe -> act -> assert -> collect evidence
-> score -> report`. The JSON result schema and Markdown summary are written for
both Frontier and human operators.

`horc simulate android` verifies the Android APK through explicit backends:
`--emulator`, `--device`, and `--local-report <path>`. The default remains an
ADB auto lane for compatibility, but any OAuth/app-link/chooser claim should use
the narrow backend that produced the evidence.

`horc simulate android --emulator` is for cloud/CI regression. It detects
`/dev/kvm`, nested virtualization, CPU architecture, Android SDK/emulator
binaries, existing AVDs, and Docker. If host emulator setup is not viable, it
checks whether Docker is available and whether Docker can access the required
device/virtualization features. Docker is reported honestly: it cannot
magically replace missing KVM/nested virtualization.

`horc simulate android --device` is the required real-device proof path for
Android OAuth return, app-link/deep-link ownership, chooser, Chrome handoff, and
WebView session claims. It discovers `adb` from `PATH`, `WASM_AGENT_SIM_ADB`,
`ANDROID_HOME` / `ANDROID_SDK_ROOT`, or the repo-local Android SDK, requires a
connected physical device in `device` state, installs
`/local/native/android/release/WASM-Agent-arm64.apk` by default, launches
`com.colmeio.wasmagent/.MainActivity`, waits for the WebView/PWA boot, captures
screenshots, redacted logcat, UIAutomator XML, and `dumpsys` activity/window
evidence, taps `Sign in with Google`, and observes what opens.

On Windows, the preferred real-device path is the installed native diagnostics
console: `Open wasm-agent Windows app -> Diagnostics -> Verify Android OAuth`.
That flow exposes only allowlisted native diagnostics operations, streams
redacted `adb`/local verifier output to the UI, resolves the bundled local horc
runner from Electron resources before any development PATH fallback, and runs
`simulate android --device --interactive-oauth` only after `adb devices` reports
an authorized phone. If the installed app cannot be launched, use
`tools/windows/verify-android-oauth.cmd` or
`tools/windows/verify-android-oauth.ps1` as fallbacks.

`horc simulate android --local-report <path>` validates a report copied from a
local USB-phone run, which is the current bridge when Frontier cloud cannot see
Victor's phone. Pass a copied `result.json` or the report directory containing
it. The validator checks schema, Android platform, APK build id, APK SHA-256,
device info, screenshot/log/activity artifacts, and required assertions.

The Android pass condition is intentionally narrow: the first tap must open
Google directly, must not show an `Open with` / `Complete action using`
resolver, must not show Chrome or WASM Agent as chooser options, must not
externally open `wa.colmeio.com/native/android/auth/start` or
`wa.colmeio.com/home`, OAuth completion must redirect to the native return path,
the installed app must resume, the WebView must redeem the native auth session
and become authenticated, and cancel/retry must not remain stuck on
`Opening Google sign-in...`. If a run only proves the first Google launch and
does not include post-authorization return/authenticated-WebView evidence, the
OAuth-completion assertions remain pending.

Set `WASM_AGENT_ANDROID_APK` or `WASM_AGENT_SIM_ANDROID_APK` to test another
APK. Set `WASM_AGENT_SIM_ADB` to test with a specific `adb`. Classifier fixtures
for simulator development live under `tools/app-simulator/fixtures/android/`;
`WASM_AGENT_SIM_ANDROID_FIXTURE=external-auth-start horc simulate android` must
fail because it models the old resolver chooser bug.
`WASM_AGENT_SIM_ANDROID_FIXTURE=post-auth-pwa-redirect horc simulate android`
must fail because it models the post-auth browser/PWA redirect bug.
`WASM_AGENT_SIM_ANDROID_FIXTURE=stale-cancel-retry horc simulate android` must
fail because it models the stale cancel/retry bug. Set
`WASM_AGENT_SIM_ANDROID_OAUTH_WAIT_MS=180000` or pass `--interactive-oauth` on a
local device run when a human will finish Google login during the simulator run.

`horc simulate android --voice-wake fixture-hermes-command.wav` verifies the
Android-native Hermes Voice Wake path: foreground microphone service evidence,
known `RECORD_AUDIO` permission state, local wake detection, bounded
transcription, a stored `voice_command` native event, visible timeline evidence,
and redacted logs. Negative fixtures include `false-wake`, `permission-denied`,
`service-killed`, and `no-transcription-engine`.

`horc simulate windows` is a pending skeleton only. Its future engine is
Playwright Electron + Windows smoke/PowerShell scripts. It does not verify
Windows installed-app behavior yet.

`horc simulate all` runs web normally and runs the Android auto lane. Windows
remains pending until its installed-app simulator exists. Build success is not
runtime verification. Frontier should prefer the relevant simulator before
claiming a UI/native fix: web = PWA/browser proof, emulator = CI/regression
proof, device/local-report = Android OAuth/app-link/chooser proof, all = broad
proof. The proof loop is `boot -> observe -> act -> assert -> evidence -> score
-> report -> patch`.

## wasm-agent Space Commands

```bash
horc space start
horc space stop
horc space status
horc space backup
```

`horc space start` starts the wasm-agent PWA on `http://127.0.0.1:8877` and
the wasm-agent-owned Hermes bridge on `http://127.0.0.1:8790`.

## Notes

- `horc restart` with no node restarts all nodes in orchestrator-first order.
- `hord` and `clone.sh` are compatibility aliases for `horc`.
- `horc backup` produces lean archives and includes a shared runtime seed for reseeding nodes during restore.
- `horc space backup` produces a client-first wasm-agent state archive and does not include public repo source.
- `horc restore` stops included running nodes, restores payloads, and restarts nodes that were running.
- Every update refreshes `/local/hermes-agent` as a hard mirror of the configured upstream repo/branch before reseeding nodes.
- `horc update all` reseeds every node and reconciles `/local/agents/registry.json`.
- `horc update node <name>` reseeds only the named node and leaves others untouched.
- Add `--force` to discard local `/local/hermes-agent` checkout changes when the upstream refresh would otherwise fail on a dirty working tree.
- `horc build` is the shortcut for the Windows wasm-agent native release artifact.
- Prefer the explicit native build targets for releases: `horc build win`,
  `horc build android`, and `horc build all`.
- Nodes that were already running are restarted through the normal lifecycle; stopped nodes keep their stopped state.
- `NODE_RESEED=true` in `/local/agents/envs/<node>.env` forces a one-shot reseed from `/local/hermes-agent` on the next start/restart.
- Update reports are written under `/local/logs/update/<run-id>/`.

## Wrapper Environment

- `HERMES_DEFAULT_NODE`: default node when a command omits a name; default `orchestrator`.
- `HERMES_CLONE_MANAGER_SCRIPT`: override path for `clone_manager.py`.
- `HERMES_CLONE_PYTHON_BIN`: override Python runtime for the wrapper.
- `HERMES_HORC_ASSUME_YES=1`: skip interactive `delete` confirmation.
- `HERMES_WASM_AGENT_STATE_DIR`: local wasm-agent state root for `horc space`
  runtime state and backup fallback.
- `HERMES_WASM_AGENT_BRIDGE_STATE_DIR`: optional bridge state root, default
  `<HERMES_WASM_AGENT_STATE_DIR>/bridge`.
- `HERMES_WASM_AGENT_CLOUD_STATE_ROOT`: private wasm-agent-cloud instance state root used by `horc space backup`.
- `HERMES_WASM_AGENT_CLOUD_INSTANCE_ID`: optional stable id used in wasm-agent-cloud backup archive paths.
- `HORC_WIN_BUILD_MODE`: `auto`, `native`, `wine`, or `docker`; default `auto`.
- `HORC_TARGET_WIN_ARCH`: Windows target architecture; currently only `x64`.
- `HORC_REQUIRE_VERIFIED_INSTALLER=1`: require installer, unpacked exe, and
  app.asar artifact checks; default `1`.
- `HORC_DOCKER_IMAGE`: Docker image for Linux amd64 Wine builds; default
  auto-selects local `horc/electron-builder-wine-nsis:jammy` when present,
  otherwise `electronuserland/builder:wine`.
- `HORC_PREPARED_DOCKER_IMAGE`: local prepared builder image tag created by
  `horc build prepare-docker`; default `horc/electron-builder-wine-nsis:jammy`.
- `HORC_DOCKER_AMD64_PROBE_IMAGE`: small linux/amd64 image used to verify
  Docker/QEMU emulation before pulling the Electron builder; default
  `alpine:3.20`.
- `HORC_AUTO_INSTALL_BINFMT=1`: enable automatic QEMU binfmt registration;
  default on Linux aarch64 in `auto` or `docker` mode.
- `HORC_NO_AUTO_INSTALL_BINFMT=1`: disable automatic QEMU binfmt registration.
- `HORC_ALLOW_CROSS_WIN_BUILD=1`: allow Linux aarch64 direct Wine debug builds.
- `WASM_AGENT_SKIP_WIN_RESOURCE_EDIT=1`: internal fallback switch used to skip
  Windows executable resource editing on Linux ARM64 native NSIS builds.
- `HERMES_WASM_AGENT_ANDROID_ROOT`: override Android native project root;
  default `/local/native/android`.
- `HORC_ANDROID_BUILD_MODE`: `auto`, `local`, or `docker`; default `auto`.
  `auto` selects local only when Java, Gradle, Android SDK, and runnable AAPT2
  are all valid; otherwise it selects Docker. `local` fails clearly if AAPT2
  cannot execute on the host CPU.
- `HORC_ANDROID_DOCKER_IMAGE`: Docker image for the Android SDK builder;
  default `ghcr.io/cirruslabs/android-sdk:35`.
- `HORC_ANDROID_GRADLE_VERSION`: Gradle distribution version cached under
  `native/android/.gradle-dist`; default `8.9`.
- `WASM_AGENT_SIM_URL`: optional `horc simulate web` target URL override.
- `WASM_AGENT_SIM_CHROMIUM`: optional Chromium/Chrome executable path for
  `horc simulate web`; otherwise the simulator searches common local browser
  commands.
- `WASM_AGENT_SIM_HEADED=1`: run the Playwright web simulator headed.
- `WASM_AGENT_SIM_ADB`: optional `adb` executable path for
  `horc simulate android`.
- `WASM_AGENT_ANDROID_APK` / `WASM_AGENT_SIM_ANDROID_APK`: optional Android APK
  path override for `horc simulate android`.
- `WASM_AGENT_SIM_ANDROID_OAUTH_WAIT_MS`: optional local-device wait window for
  a human to finish Google OAuth so the simulator can capture native return and
  authenticated-WebView proof.
- `HORC_SIM_SKIP_FFMPEG_INSTALL=1`: skip the Playwright ffmpeg helper download;
  failure traces still run, but failure video artifacts are skipped.
- `GRADLE_BIN`: optional Android Gradle executable override.
- `ANDROID_HOME` / `ANDROID_SDK_ROOT`: Android SDK root used by Gradle and
  `apksigner`.
- `WASM_AGENT_ANDROID_KEYSTORE`, `WASM_AGENT_ANDROID_KEYSTORE_PASSWORD`,
  `WASM_AGENT_ANDROID_KEY_ALIAS`, `WASM_AGENT_ANDROID_KEY_PASSWORD`: optional
  production signing key configuration for the APK lane.

## Governance

Every node receives a generated runtime contract at startup and restart:
- `/local/agents/nodes/<node>/.hermes/NODE_RUNTIME_CONTRACT.md`
- `/local/agents/nodes/<node>/workspace/NODE_RUNTIME_CONTRACT.md`

The clone manager also injects a condensed governance prompt through `HERMES_EPHEMERAL_SYSTEM_PROMPT` so live agent behavior stays aligned with the contract on each start.

Shared framework changes under `/local/plugins` and `/local/scripts` follow this execution discipline:
- Think before acting: inspect current state, state assumptions explicitly, and assess blast radius before editing shared assets.
- Simplicity first: prefer the smallest reversible change that solves the problem.
- Surgical changes: touch only the files required for the task and avoid unrelated refactors in shared infrastructure.
- Goal-driven execution: define success checks up front and require rollout, rollback, and post-restart verification for shared changes.

Operational implication:
- documentation-only changes to the generated contract files are not enough for a running node
- restart the affected node, usually with `horc restart <name>`, to load the updated injected governance prompt

## Source of Truth

- CLI wrapper: `/local/scripts/public/clone/horc.sh`
- Engine: `/local/scripts/public/clone/clone_manager.py`
- Fleet inventory: `/local/agents/registry.json`

## Registry Role

`/local/agents/registry.json` is the canonical operational inventory for orchestrated nodes. It is maintained by the clone manager and is intended for inspection, reconciliation, and version auditing.

Each node entry records:
- topology and identity: `clone_name`, `clone_root`, `env_path`, `state_mode`, `state_code`
- runtime attachment: `container_name`, `container_id`, `runtime_type`, and `host_pid` for bare-metal nodes
- reconciliation timestamp: `updated_at`
- Hermes runtime version metadata under `hermes_agent`

`hermes_agent` includes:
- `package_version`
- `git_commit`
- `git_branch`
- `git_describe`
- `engines_node`

If a node runtime tree does not keep a `.git` directory, the version snapshot falls back to the bootstrap source recorded in `.clone-meta/bootstrap.json`.

Operator guidance:
- treat `registry.json` as derived state, not declarative config
- use it to compare node versions before and after updates
- remove stale entries as part of node cleanup
