const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const mainJs = fs.readFileSync(path.join(__dirname, "main.js"), "utf8");

assert(mainJs.includes("function validateAndroidVoiceTuningApk"), "APK validation helper must exist");
assert(mainJs.includes('"stale_or_stub_apk"'), "stale/tiny APKs must be rejected");
assert(mainJs.includes("sizeBytes <= 50 * 1024 * 1024"), "fresh APK validation must enforce the >50 MB floor when no exact size is available");
assert(mainJs.includes('"apk_sha256_mismatch"') && mainJs.includes('"apk_size_mismatch"'), "APK validation must check hash and exact size metadata");

const resolver = mainJs.slice(mainJs.indexOf("async function resolveAndroidVoiceTuningApk"), mainJs.indexOf("async function runAndroidVoiceTuningProof"));
assert(resolver.includes("explicitUrl") && resolver.includes("releaseArtifact.url") && resolver.includes("bundledAndroidApkPath"), "resolver must support explicit URL, release feed, and bundled fallback");
assert(resolver.indexOf("explicitUrl") < resolver.indexOf("releaseArtifact.url"), "explicit apkUrl must be considered before the release feed");
assert(resolver.indexOf("releaseArtifact.url") < resolver.indexOf("bundledAndroidApkPath"), "fresh release APK must be preferred over bundled fallback");
assert(resolver.includes("apk_source_selected") && resolver.includes("apk_validation_passed"), "resolver must emit source and validation progress");

assert(mainJs.includes("fresh_apk_download_failed"), "download failures must return a structured fresh_apk_download_failed blocker");
assert(mainJs.includes("apk_download_started") && mainJs.includes("apk_download_finished") && mainJs.includes("apk_hash_computed"), "downloads must emit bounded progress and hash events");
assert(mainJs.includes("androidVoiceTuningStagingRoot") && mainJs.includes('"staged", "android"'), "downloaded APKs must stage under a controlled Android staging path");
assert(!mainJs.includes("app-debug.apk"), "proof command must not stage the fresh release as the old generic app-debug.apk");

assert(mainJs.includes("adb_install_started") && mainJs.includes("adb_install_finished"), "ADB install must emit structured progress");
assert(mainJs.includes("app_force_stopped") && mainJs.includes("app_launched"), "force-stop and launch must emit structured progress");
assert(mainJs.includes("logcat_capture_started") && mainJs.includes("logcat_capture_finished"), "logcat capture must emit structured progress");
assert(!mainJs.includes("android_voice_tuning_pull_dataset"), "proof command must not record/export or pull datasets before bridge proof");

assert(mainJs.includes('"check_android_connection"'), "safe Android connection check command must be allowlisted");
assert(mainJs.includes("runAndroidConnectionCheck(sender, opId)") && mainJs.includes('connection.status !== "one_authorized_device"'), "voice-tuning install/runtime paths must be gated behind exactly one authorized Android device");
assert(mainJs.includes('"debug_android_voice_tuning_runtime"'), "runtime debug command must remain allowlisted");
assert(mainJs.includes('"export_hermes_wake_dataset"') && mainJs.includes("async function exportHermesWakeDataset") && mainJs.includes('"files/voice/exports/hermes-dataset.zip"') && mainJs.includes("/native/android/hermes-wake-dataset"), "Hermes wake dataset export must remain a dedicated allowlisted bridge with backend upload");
assert(mainJs.includes('"run_android_voice_tuning_goal_loop"'), "guarded Hermes Wake goal loop must be allowlisted");
assert(mainJs.includes("screencap") && mainJs.includes("uiautomator_dump") && mainJs.includes("native-diagnostics/latest.json") && mainJs.includes("appops_record_audio") && mainJs.includes("gfxinfo"), "goal loop/runtime capture must collect screenshot, UIAutomator XML, native diagnostics, permission state, and frame timing evidence");
assert(mainJs.includes("permission_prompt_auto_clicked: false") && mainJs.includes("voice_samples_collected: false") && mainJs.includes("recording_started_automatically"), "goal loop must report hard safety guarantees and detect accidental recording");
assert(!/input\s+tap|pm\s+grant|startVoiceTuningSample\(/.test(mainJs), "goal loop must not tap permission prompts, grant microphone permission, or start voice samples");
assert(!mainJs.includes('["shell"]'), "runtime debug support must not expose arbitrary adb shell execution");

console.log("android voice tuning APK resolver ok");
