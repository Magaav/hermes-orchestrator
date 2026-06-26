const assert = require("assert");
const fs = require("fs");
const path = require("path");

const pluginRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(pluginRoot, "..", "..");
const androidAppPath = path.join(pluginRoot, "public", "android-app.js");
const appLoaderPath = path.join(pluginRoot, "public", "app-loader.js");
const fullAppPath = path.join(pluginRoot, "public", "app.js");
const stylesPath = path.join(pluginRoot, "public", "styles.css");
const androidManifestPath = path.join(repoRoot, "native", "android", "app", "src", "main", "AndroidManifest.xml");
const mainActivityPath = path.join(repoRoot, "native", "android", "app", "src", "main", "java", "com", "colmeio", "wasmagent", "MainActivity.kt");
const voiceWakeServicePath = path.join(repoRoot, "native", "android", "app", "src", "main", "java", "com", "colmeio", "wasmagent", "HermesVoiceWakeService.kt");
const shellV2ActivityPath = path.join(repoRoot, "native", "android", "app", "src", "main", "java", "com", "colmeio", "wasmagent", "shell", "NativeShellV2Activity.kt");
const shellV2BridgePath = path.join(repoRoot, "native", "android", "app", "src", "main", "java", "com", "colmeio", "wasmagent", "shell", "NativeShellV2Bridge.kt");
const shellV2ConfigPath = path.join(repoRoot, "native", "android", "app", "src", "main", "java", "com", "colmeio", "wasmagent", "shell", "NativeShellV2Config.kt");
const shellV2DiagnosticsPath = path.join(repoRoot, "native", "android", "app", "src", "main", "java", "com", "colmeio", "wasmagent", "shell", "NativeShellV2Diagnostics.kt");
const androidInputProofHotOpPath = path.join(repoRoot, "native", "windows", "ops", "android", "android-ui-input-proof.js");
const androidInputProofManifestPath = path.join(repoRoot, "native", "windows", "ops", "android", "android-ui-input-proof.manifest.json");
const androidInputBudgetPath = path.join(repoRoot, "tools", "android", "prove-android-input-budget.py");
const androidUxReleaseLoopPath = path.join(repoRoot, "tools", "android", "prove-android-native-ux-release-loop.py");
const androidAppJs = fs.readFileSync(androidAppPath, "utf8");
const appLoaderJs = fs.readFileSync(appLoaderPath, "utf8");
const fullAppJs = fs.readFileSync(fullAppPath, "utf8");
const stylesCss = fs.readFileSync(stylesPath, "utf8");
const androidManifestXml = fs.readFileSync(androidManifestPath, "utf8");
const mainActivityKt = fs.readFileSync(mainActivityPath, "utf8");
const voiceWakeServiceKt = fs.readFileSync(voiceWakeServicePath, "utf8");
const shellV2ActivityKt = fs.readFileSync(shellV2ActivityPath, "utf8");
const shellV2BridgeKt = fs.readFileSync(shellV2BridgePath, "utf8");
const shellV2ConfigKt = fs.readFileSync(shellV2ConfigPath, "utf8");
const shellV2DiagnosticsKt = fs.readFileSync(shellV2DiagnosticsPath, "utf8");
const androidInputProofHotOpJs = fs.readFileSync(androidInputProofHotOpPath, "utf8");
const androidInputProofManifest = fs.readFileSync(androidInputProofManifestPath, "utf8");
const androidInputBudgetPy = fs.readFileSync(androidInputBudgetPath, "utf8");
const androidUxReleaseLoopPy = fs.readFileSync(androidUxReleaseLoopPath, "utf8");

const MAX_LITE_INTERACTION_LISTENERS = 6;
const MAX_BOOTSTRAP_FETCH_CALLS = 1;
const MAX_SHELL_V2_ACTIVITY_LINES = 220;
const MAX_SHELL_V2_BRIDGE_LINES = 430;
const MAX_SHELL_V2_CONFIG_LINES = 115;
const MAX_SHELL_V2_DIAGNOSTICS_LINES = 115;
const MAX_SHELL_V2_JAVASCRIPT_INTERFACES = 22;
const MAX_SHELL_V2_WEBVIEW_INTERFACES = 3;
const MAX_SHELL_V2_LOAD_URL_CALLS = 3;
const SHELL_V2_FORBIDDEN_STARTUP_PATTERN = /HermesVoiceWakeService|VoiceTuning|WakeModel|FalseWake|NativeTelemetryBus|HttpURLConnection|OkHttp|Thread\.sleep|thread\(|postDelayed|Timer\(|startService|startForegroundService|WebChromeClient|setDownloadListener|onShowFileChooser|resolveBackend|\/health|\/healthz|\/config\.json|\/native\/releases|native\/control/i;
const SHELL_V2_BRIDGE_FORBIDDEN_BACKGROUND_PATTERN = /HttpURLConnection|OkHttp|Thread\.sleep|thread\(|postDelayed|Timer\(|WebChromeClient|setDownloadListener|onShowFileChooser|resolveBackend|\/health|\/healthz|\/config\.json|\/native\/releases|native\/control/i;

function countMatches(source, pattern) {
  const match = source.match(pattern);
  return match ? match.length : 0;
}

function lineCount(source) {
  return source.trimEnd().split(/\r?\n/).length;
}

function sourceBetween(startMarker, endMarker) {
  return sourceBetweenIn(androidAppJs, startMarker, endMarker);
}

function sourceBetweenIn(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  assert.notStrictEqual(start, -1, `${startMarker} was not found`);
  const end = source.indexOf(endMarker, start);
  assert.notStrictEqual(end, -1, `${endMarker} was not found after ${startMarker}`);
  return source.slice(start, end);
}

function functionSource(name, nextMarker) {
  return sourceBetween(`function ${name}`, nextMarker);
}

function manifestActivityBlock(activityName) {
  const marker = `android:name="${activityName}"`;
  const markerIndex = androidManifestXml.indexOf(marker);
  assert.notStrictEqual(markerIndex, -1, `${activityName} manifest activity was not found`);
  const start = androidManifestXml.lastIndexOf("<activity", markerIndex);
  assert.notStrictEqual(start, -1, `${activityName} manifest activity start was not found`);
  const startClose = androidManifestXml.indexOf(">", markerIndex);
  assert.notStrictEqual(startClose, -1, `${activityName} manifest activity start tag was not closed`);
  if (androidManifestXml.slice(start, startClose + 1).trimEnd().endsWith("/>")) {
    return androidManifestXml.slice(start, startClose + 1);
  }
  const end = androidManifestXml.indexOf("</activity>", startClose);
  assert.notStrictEqual(end, -1, `${activityName} manifest activity end tag was not found`);
  return androidManifestXml.slice(start, end + "</activity>".length);
}

assert(
  androidAppJs.includes("const architectureMetrics = {")
    && androidAppJs.includes("function architectureSnapshot()")
    && androidAppJs.includes("window.__wasmAgentArchitectureMetrics = architectureSnapshot")
    && androidAppJs.includes("architecture_metrics: true"),
  "Android lite shell must expose architecture metrics for instant performance-budget checks"
);

const architectureSnapshotSource = functionSource("architectureSnapshot", "window.__wasmAgentArchitectureMetrics");
assert(
  architectureSnapshotSource.includes('schema: "hermes.wasm_agent.architecture_metrics.v1"')
    && architectureSnapshotSource.includes("render_total: architectureMetricTotal(architectureMetrics.renders)")
    && architectureSnapshotSource.includes("fetch_total: architectureMetricTotal(architectureMetrics.fetches)")
    && architectureSnapshotSource.includes("listener_total: architectureMetricTotal(architectureMetrics.listeners)")
    && architectureSnapshotSource.includes("repeated_fetch_paths")
    && architectureSnapshotSource.includes("recent_render_bursts"),
  "Architecture snapshot must report render, fetch, listener, repeated-fetch, and render-burst waste signals"
);

const liteInteractionSource = functionSource("installLiteInteractions", "async function markPrepaintShell");
const liteListenerCount = countMatches(liteInteractionSource, /\.addEventListener\(/g);
assert(
  liteListenerCount <= MAX_LITE_INTERACTION_LISTENERS,
  `Android lite interactions must stay delegated; found ${liteListenerCount} listeners, budget is ${MAX_LITE_INTERACTION_LISTENERS}`
);
assert.strictEqual(
  countMatches(liteInteractionSource, /noteArchitectureListener\(/g),
  liteListenerCount,
  "Every Android lite interaction listener must be counted by architecture metrics"
);
assert(
  liteInteractionSource.includes('document.addEventListener("click", handleLiteClick)')
    && liteInteractionSource.includes('document.addEventListener("keydown", handleLiteKeydown)')
    && liteInteractionSource.includes('document.addEventListener("submit", handleLiteSubmit')
    && !liteInteractionSource.includes("querySelectorAll"),
  "Android lite interactions must stay centralized instead of binding per-control listeners"
);

const bootstrapFetchCount = countMatches(androidAppJs, /fetchJson\("\/app\/bootstrap"/g);
assert.strictEqual(
  bootstrapFetchCount,
  MAX_BOOTSTRAP_FETCH_CALLS,
  `Android lite startup must keep one authoritative /app/bootstrap fetch; found ${bootstrapFetchCount}`
);
assert(
  !androidAppJs.includes('fetchJson("/auth/session"'),
  "Android lite startup must not reintroduce /auth/session beside /app/bootstrap"
);

const fetchJsonSource = sourceBetween("async function fetchJson", "function applyBootstrapPayload");
assert.strictEqual(
  countMatches(fetchJsonSource, /noteArchitectureFetch\(/g),
  1,
  "fetchJson must count every fetch path through one architecture hook"
);

for (const [name, nextMarker] of [
  ["renderLiteSpaceLauncher", "function renderConfigLite"],
  ["renderConfigLite", "function renderDevicesLite"],
  ["renderDevicesLite", "function renderFleetLite"],
  ["renderFleetLite", "function renderArtifactsLite"],
  ["renderArtifactsLite", "function renderModulesLite"],
  ["renderModulesLite", "function liteDeviceProfile"],
  ["renderNativeLite", "function nativeDebugRows"],
  ["renderNativeDebugLite", "function renderWakeWordLite"],
  ["renderWakeWordLite", "function renderActiveLiteModal"],
  ["renderLiteModal", "function openLiteModal"],
]) {
  const body = functionSource(name, nextMarker);
  assert(
    body.includes("noteArchitectureRender("),
    `${name} must report render work to architecture metrics`
  );
}

const runtimeSnapshotSource = functionSource("runtimeSnapshot", "function eventPointForElement");
assert(
  runtimeSnapshotSource.includes("architecture: architectureSnapshot()"),
  "Runtime snapshots must include architecture metrics"
);

const bootTracePayloadSource = functionSource("bootTracePayload", "async function uploadTrace");
assert(
  bootTracePayloadSource.includes("architecture: architectureSnapshot()"),
  "Uploaded boot traces must include architecture metrics"
);

assert(
  appLoaderJs.includes("window.__WASM_AGENT_ANDROID_PERF_SAFE_MODE__ = perfSafeMode")
    && appLoaderJs.includes('window.__WASM_AGENT_ANDROID_BRIDGE_DIAGNOSTICS__ = perfSafeMode ? "off" : "sampled"')
    && appLoaderJs.includes('window.__WASM_AGENT_ANDROID_WAKE_STARTUP__ = perfSafeMode ? "off" : "deferred"')
    && appLoaderJs.includes('return "user-full"')
    && appLoaderJs.includes('"debug-lite"'),
  "Android app loader must expose perf flags before module boot while defaulting to the full runtime unless debug-lite is explicit"
);

const windowsUpdateCompareSource = sourceBetweenIn(fullAppJs, 'if (platform === "windows")', "const sameBuild = current.buildId && latestBuildId");
assert(
  windowsUpdateCompareSource.includes("const newerBuild = currentBuildId && latestBuildId && latestRank > currentRank")
    && !windowsUpdateCompareSource.includes("!currentBuildId || latestRank > currentRank"),
  "Windows native update UI must not classify an unknown current build as update_available"
);
assert(
  fullAppJs.includes("androidInfo.packageInfo?.buildId || androidInfo.buildId || androidInfo.build_id")
    && fullAppJs.includes("function nativeInstallerUpdateAvailable(resolution = state.nativeInstallerResolution, profile = state.nativeInstallProfile || detectNativeDeviceProfileSync())")
    && fullAppJs.includes('cleanText(state.nativeUpdateState.platform, "").toLowerCase() === platform')
    && fullAppJs.includes("!nativeInstallerUpdateAvailable(null, base)")
    && fullAppJs.includes('"Android APK update available"')
    && fullAppJs.includes('updateAvailable && profilePlatform === "windows" && !windowsNativeShellNeedsDiagnosticsUpdate() ? metric("Reason", "New Windows build available") : null')
    && fullAppJs.includes('updateAvailable && profilePlatform === "android" ? metric("Reason", "New Android APK available") : null'),
  "Native update UI must keep Android APK updates out of the Windows installer/update-required lane"
);

const mainSource = sourceBetweenIn(fullAppJs, "async function main()", "main().catch");
assert(
  fullAppJs.includes("function requestAndroidNativeWebRuntimeReload")
    && fullAppJs.includes('bridge.hardReloadWebRuntime(JSON.stringify({')
    && fullAppJs.includes('nativeAuthDiagnostic("dev_hmr_android_hard_reload_requested"')
    && fullAppJs.includes("function clearAndroidWebRuntimeCachesAndReload")
    && fullAppJs.includes('nativeAuthDiagnostic("dev_hmr_android_web_fallback_reload_started"')
    && fullAppJs.includes('url.searchParams.set("native_refresh", Date.now().toString());')
    && fullAppJs.includes('if (isAndroidNativeShell()) return !window.__WASM_AGENT_DISABLE_HMR__;')
    && mainSource.indexOf("installDevHmrBridge();") < mainSource.indexOf("renderAndroidNativeCachedAuthenticatedShell()")
    && mainSource.indexOf("if (shouldStartDevHmr()) startDevHmr();") < mainSource.indexOf("renderAndroidNativeCachedAuthenticatedShell()"),
  "Android native HMR must start before cached-shell early return and use hard web-runtime reload when available"
);

assert(
  mainActivityKt.includes("@Volatile private var pendingPerfSafeMode: Boolean = false")
    && mainActivityKt.includes("private fun healthProbesMode()")
    && fullAppJs.includes("function androidNativeControlAutoStartEnabled")
    && fullAppJs.includes("android_native_control_agent_auto_start_skipped")
    && fullAppJs.includes("android_wake_request_polling_disabled"),
  "Android native production boot must keep perf-safe mode explicit and keep wake/control polling off the startup path when that mode is enabled"
);

assert(
  androidAppJs.includes("function androidNativeUxReport")
    && androidAppJs.includes("window.__wasmAgentAndroidNativeUxReport")
    && androidAppJs.includes('"get_android_native_ux_report"')
    && androidAppJs.includes("android_native_ux_report: androidNativeUxReport(reason)"),
  "Android lite runtime must expose the compact Android native UX report and native-control command"
);

assert(
  fullAppJs.includes("function androidNativeUxReport")
    && fullAppJs.includes("window.__wasmAgentAndroidNativeUxReport")
    && fullAppJs.includes("android_native_ux_report: isAndroidNativeShell() ? androidNativeUxReport(reason) : null")
    && fullAppJs.includes("androidNativeRecordMiniMap")
    && fullAppJs.includes("androidNativeRecordTouch")
    && fullAppJs.includes("frame_gap_p95_ms"),
  "Shared Android runtime must expose UX report, minimap/touch counters, and frame-gap percentiles"
);

assert(
  !fullAppJs.includes('if (androidPan && event.pointerType === "touch")')
    && fullAppJs.includes('if (androidPan) androidNativeRecordTouch("pan_start");')
    && fullAppJs.includes('if (canPanX) viewport.scrollLeft = startLeft - (moveEvent.clientX - startX);')
    && fullAppJs.includes("const ANDROID_CANVAS_INTERACTION_RELEASE_MS = 140;")
    && fullAppJs.includes("now - Number(state.spaceNavigationInputAt || 0) < ANDROID_CANVAS_INTERACTION_RELEASE_MS")
    && fullAppJs.includes("function isCanvasPanBlockedTarget")
    && fullAppJs.includes("if (isCanvasPanBlockedTarget(event.target))")
    && fullAppJs.includes("!isSpaceInteractiveTapTarget(event.target) && !isCanvasPanBlockedTarget(event.target)")
    && fullAppJs.includes("function clearAndroidCanvasInputDeferral")
    && fullAppJs.includes("function androidMomentumTapClickTarget")
    && fullAppJs.includes("function androidEventClientPoint")
    && fullAppJs.includes("function rememberAndroidMomentumInterruptedTap")
    && fullAppJs.includes("function cancelAndroidMomentumForInteractiveTap")
    && fullAppJs.includes("function clearAndroidCanvasDeferralForScreenOpen")
    && fullAppJs.includes("function finishAndroidMomentumInterruptedTap")
    && fullAppJs.includes("function androidNativeRecordMomentumTapEvent")
    && fullAppJs.includes("momentum_tap_trace")
    && fullAppJs.includes('androidNativeRecordMomentumTapEvent("touchstart_during_momentum"')
    && fullAppJs.includes('androidNativeRecordMomentumTapEvent("fallback_scheduled"')
    && fullAppJs.includes('androidNativeRecordMomentumTapEvent("real_click_arrived"')
    && fullAppJs.includes('document.addEventListener("touchstart", (event) => {')
    && fullAppJs.includes('document.addEventListener("touchend", (event) => {')
    && fullAppJs.includes('clearAndroidCanvasDeferralForScreenOpen("screen_open_tap")')
    && fullAppJs.includes('clearAndroidCanvasDeferralForScreenOpen("panel_switch")')
    && fullAppJs.includes("state.androidMomentumInterruptedTap")
    && fullAppJs.includes("momentum_synthetic_click_fallback")
    && fullAppJs.includes("momentum_touch_synthetic_click_fallback")
    && fullAppJs.includes("if (androidPan && state.spacePanMomentumActive) cancelAndroidMomentumForInteractiveTap(event);")
    && !fullAppJs.includes('if (isSpaceInteractiveTapTarget(event.target)) {\n      if (androidPan) androidNativeRecordTouch("ignored", "interactive_target");')
    && !sourceBetweenIn(fullAppJs, "function isSpaceInteractiveTapTarget", "function installAndroidMomentumInteractiveTapCancel").includes("[data-space-id]")
    && !sourceBetweenIn(fullAppJs, "function isSpaceInteractiveTapTarget", "function installAndroidMomentumInteractiveTapCancel").includes("[data-widget-id]")
    && !sourceBetweenIn(fullAppJs, "function isSpaceInteractiveTapTarget", "function installAndroidMomentumInteractiveTapCancel").includes("[data-widget-app]")
    && !fullAppJs.includes('renderSpaceMiniMap({ force: true, reason: "pan-start" });')
    && !fullAppJs.includes('renderSpaceMiniMap({ force: true, reason: "pan-end" });')
    && fullAppJs.includes("function syncSpaceMiniMapViewportBox")
    && fullAppJs.includes('scheduleSpaceMiniMapViewportSync("pan-move");')
    && fullAppJs.includes('scheduleSpaceMiniMapViewportSync("momentum");')
    && fullAppJs.includes("function installAndroidMomentumInteractiveTapCancel")
    && fullAppJs.includes("stopSpacePanMomentum();")
    && fullAppJs.includes("momentum_cancel_for_interactive_tap")
    && fullAppJs.includes('startSpacePanMomentum(viewport, releaseVelocity.x, releaseVelocity.y, canPanX, canPanY);')
    && fullAppJs.includes('if (state.spaceMiniMapVisible) renderSpaceMiniMap({ force: true, reason: "momentum-end" });')
    && stylesCss.includes(".os-shell.native-android .space-viewport {\n  touch-action: none;")
    && stylesCss.includes(".os-shell.native-android #spaceCanvas")
    && stylesCss.includes(".os-shell.native-android .app-layer"),
  "Android native finger pan must stay JS-owned for canvas control while deferring minimap/navigation maintenance"
);

const setPanelSource = sourceBetweenIn(fullAppJs, "function setPanel(panel, options = {})", "function handleAppPopState()");
assert(
  setPanelSource.includes("clearAndroidCanvasDeferralForScreenOpen(\"panel_switch\")")
    && setPanelSource.includes("}, ANDROID_CANVAS_INTERACTION_RELEASE_MS);")
    && !setPanelSource.includes("}, ANDROID_NATIVE_CONTROL_INTERACTION_QUIET_MS);"),
  "Android panel/screen opening must not wait for the long native-control quiet window after canvas momentum"
);

assert(
  fullAppJs.includes('document.addEventListener("pointerrawupdate", (event) => queueSharedSpacePointerMove(event, { raw: true }), { capture: true, passive: true });')
    && fullAppJs.includes('document.addEventListener("pointermove", queueSharedSpacePointerMove, { capture: true, passive: true });')
    && !fullAppJs.includes('if (!isAndroidNativeShell()) {\n    document.addEventListener("pointerrawupdate"')
    && fullAppJs.includes("if (isAndroidNativeShell()) state.androidSharedPointerFollowScrollAt = performance.now();")
    && fullAppJs.includes('scheduleSpaceMiniMapViewportSync("shared-pointer-follow");')
    && fullAppJs.includes('scheduleSpaceMiniMapViewportSync("shared-pointer-follow-scroll");')
    && fullAppJs.includes("now - Number(state.androidSharedPointerFollowScrollAt || 0) < 120"),
  "Android shared-space pointer must use the same live move path as PWA while programmatic follow scroll avoids local-pan quiet gates"
);

const resolveBackendSource = sourceBetweenIn(mainActivityKt, "private fun resolveBackend()", "private fun immediateLaunchOrigin");
assert(
  resolveBackendSource.indexOf("openRemotePwaWebView(immediateOrigin)") < resolveBackendSource.indexOf('scheduleBackendProbeDiagnostics("post_first_load")')
    && !resolveBackendSource.includes("identifiesWasmAgent(")
    && !resolveBackendSource.includes("showErrorScreen("),
  "MainActivity resolveBackend must open the WebView immediately and move backend probing to diagnostics"
);

const homeUrlSource = sourceBetweenIn(mainActivityKt, "private fun pwaHomeUrl", "private fun openRemotePwaWebView(origin: String)");
assert(
  homeUrlSource.includes('.appendQueryParameter("android_startup", "instant")')
    && homeUrlSource.includes('.appendQueryParameter("android_runtime", "user-full")')
    && homeUrlSource.includes('.appendQueryParameter("healthProbes", healthProbesMode())')
    && homeUrlSource.includes('.appendQueryParameter("wake", wakeStartupMode())')
    && homeUrlSource.includes('.appendQueryParameter("bridgeDiagnostics", bridgeDiagnosticsMode())')
    && homeUrlSource.includes('.appendQueryParameter("perfSafeMode", "1")'),
  "Android native URL must carry instant-start, post-paint health, wake, bridge diagnostics, and perf safe mode flags"
);

assert(
  mainActivityKt.includes("private fun shouldForwardConsoleDiagnostic")
    && mainActivityKt.includes("BOOT_CONSOLE_FORWARD_LIMIT")
    && mainActivityKt.includes("CONSOLE_FORWARD_MIN_INTERVAL_MS")
    && mainActivityKt.includes("bridge_calls_during_boot")
    && mainActivityKt.includes("console_messages_dropped")
    && mainActivityKt.includes("diagnostics_writes_during_boot"),
  "MainActivity must sample console/native diagnostics and expose boot bridge/console counters"
);

const onCreateSource = sourceBetweenIn(mainActivityKt, "override fun onCreate", "override fun onSaveInstanceState");
assert(
  !onCreateSource.includes("reconcileStaleVoiceWakeStatus(")
    && onCreateSource.includes("voice_wake_boot_reconciliation\", \"deferred_until_after_first_load"),
  "MainActivity must not reconcile wake status synchronously before first WebView load"
);

assert(
  mainActivityKt.includes("private fun schedulePostFirstLoadBootDiagnostics")
    && mainActivityKt.includes("voice_wake_boot_reconciliation_skipped")
    && mainActivityKt.includes("val deferRoutineSnapshot = !important"),
  "MainActivity must defer wake reconciliation and routine diagnostics snapshots until after first load/visible commit"
);

const shellV2OnCreate = sourceBetweenIn(shellV2ActivityKt, "override fun onCreate", "override fun onNewIntent");
const shellV2CombinedKt = [
  shellV2ActivityKt,
  shellV2BridgeKt,
  shellV2ConfigKt,
].join("\n");
assert(
  shellV2ConfigKt.includes('require(origin == "https://wa.colmeio.com")')
    && shellV2ConfigKt.includes('.appendQueryParameter("android_startup", "instant-v2")')
    && shellV2ConfigKt.includes('.appendQueryParameter("wake", "off")')
    && shellV2ConfigKt.includes('.appendQueryParameter("bridgeDiagnostics", "off")')
    && shellV2ConfigKt.includes('.appendQueryParameter("healthProbes", "off")')
    && shellV2ConfigKt.includes('.appendQueryParameter("nativeControl", "off")')
    && shellV2ConfigKt.includes('.put("blocks_before_load_url", 0)')
    && !shellV2ConfigKt.includes("127.0.0.1")
    && !shellV2ConfigKt.includes("localhost"),
  "Android shell v2 config must be production-only and declare zero startup blockers"
);
assert(
  shellV2OnCreate.indexOf("setContentView(root)") < shellV2OnCreate.indexOf("diagnostics.markLoadUrl(url)")
    && shellV2OnCreate.indexOf("diagnostics.markLoadUrl(url)") < shellV2OnCreate.indexOf("view.loadUrl(url)")
    && !/resolveBackend|Thread\.sleep|startService|startForegroundService|HermesVoiceWakeService|schedulePostFirstLoad/i.test(shellV2OnCreate),
  "Android shell v2 onCreate must load the production WebView immediately without backend, wake, service, or delayed diagnostic gates"
);
assert(
  lineCount(shellV2ActivityKt) <= MAX_SHELL_V2_ACTIVITY_LINES
    && lineCount(shellV2BridgeKt) <= MAX_SHELL_V2_BRIDGE_LINES
    && lineCount(shellV2ConfigKt) <= MAX_SHELL_V2_CONFIG_LINES
    && lineCount(shellV2DiagnosticsKt) <= MAX_SHELL_V2_DIAGNOSTICS_LINES,
  `Android shell v2 layer 0 must stay small: activity=${lineCount(shellV2ActivityKt)}/${MAX_SHELL_V2_ACTIVITY_LINES}, bridge=${lineCount(shellV2BridgeKt)}/${MAX_SHELL_V2_BRIDGE_LINES}, config=${lineCount(shellV2ConfigKt)}/${MAX_SHELL_V2_CONFIG_LINES}, diagnostics=${lineCount(shellV2DiagnosticsKt)}/${MAX_SHELL_V2_DIAGNOSTICS_LINES}`
);
assert(
  countMatches(shellV2BridgeKt, /@JavascriptInterface/g) <= MAX_SHELL_V2_JAVASCRIPT_INTERFACES
    && countMatches(shellV2ActivityKt, /addJavascriptInterface\(/g) <= MAX_SHELL_V2_WEBVIEW_INTERFACES
    && countMatches(shellV2ActivityKt, /\.loadUrl\(/g) <= MAX_SHELL_V2_LOAD_URL_CALLS,
  `Android shell v2 layer 0 exceeded bridge/load budget: jsInterfaces=${countMatches(shellV2BridgeKt, /@JavascriptInterface/g)}/${MAX_SHELL_V2_JAVASCRIPT_INTERFACES}, webViewInterfaces=${countMatches(shellV2ActivityKt, /addJavascriptInterface\(/g)}/${MAX_SHELL_V2_WEBVIEW_INTERFACES}, loadUrl=${countMatches(shellV2ActivityKt, /\.loadUrl\(/g)}/${MAX_SHELL_V2_LOAD_URL_CALLS}`
);
assert(
  !SHELL_V2_FORBIDDEN_STARTUP_PATTERN.test(shellV2OnCreate)
    && !SHELL_V2_BRIDGE_FORBIDDEN_BACKGROUND_PATTERN.test(shellV2CombinedKt),
  "Android shell v2 layer 0 must not import or call wake, diagnostics upload, backend probe, release feed, native-control, threaded delay, file chooser, or service startup primitives"
);
assert(
  shellV2BridgeKt.includes("fun getWakeWordState(): String = wakeWordState().toString()")
    && shellV2BridgeKt.includes("fun enableVoiceWake(): String")
    && shellV2BridgeKt.includes("fun disableVoiceWake(): String")
    && shellV2BridgeKt.includes("fun requestVoiceWakePermission(): String")
    && shellV2BridgeKt.includes('"fetch_wake_word_state", "android.wake_word.state"')
    && shellV2BridgeKt.includes('"apply_wake_word_policy", "android.wake_word.apply_policy"')
    && shellV2BridgeKt.includes("HermesVoiceWakeService.statusFile(activity)")
    && shellV2BridgeKt.includes("HermesVoiceWakeService.start(activity, config.origin)")
    && shellV2BridgeKt.includes("startWakeService(intent)")
    && shellV2BridgeKt.includes("unsupported(\"downloaded_runtime\"")
    && shellV2BridgeKt.includes("unsupported(\"hot_ops\"")
    && shellV2BridgeKt.includes("fun startGoogleLogin()")
    && !/resolveNativeAndroidAuthStartUrl|HttpURLConnection|pollAndroidAuth/.test(shellV2BridgeKt),
  "Android shell v2 bridge must expose explicit wake controls while keeping hot-op, runtime sync, polling, and pre-auth network work out of layer 0"
);
assert(
  shellV2BridgeKt.includes("fun hardReloadWebRuntime(payloadJson: String?): String")
    && shellV2BridgeKt.includes("view.clearCache(true)")
    && shellV2BridgeKt.includes("navigator.serviceWorker?.getRegistrations")
    && shellV2BridgeKt.includes("window.caches.delete(key)")
    && shellV2BridgeKt.includes("native_refresh=")
    && !shellV2BridgeKt.includes("WebStorage.getInstance().deleteAllData()")
    && fullAppJs.includes('if (type === "hard_reload_web_runtime" || type === "refresh_web_runtime")')
    && fullAppJs.includes('bridge.hardReloadWebRuntime(JSON.stringify({'),
  "Android native must expose a deterministic hard web-runtime refresh without wiping app WebStorage"
);
const mainActivityManifestEntry = manifestActivityBlock(".MainActivity");
const shellV2ManifestEntry = manifestActivityBlock(".shell.NativeShellV2Activity");
assert(
  shellV2ManifestEntry.includes('android:name=".shell.NativeShellV2Activity"')
    && shellV2ManifestEntry.includes('android:exported="true"')
    && shellV2ManifestEntry.includes("android.intent.action.MAIN")
    && shellV2ManifestEntry.includes("android.intent.category.LAUNCHER")
    && shellV2ManifestEntry.includes("android.intent.category.BROWSABLE")
    && shellV2ManifestEntry.includes('android:scheme="wasm-agent"')
    && shellV2ManifestEntry.includes('android:host="android-auth-return"')
    && shellV2ManifestEntry.includes('android:pathPrefix="/native/android/auth/return"')
    && countMatches(androidManifestXml, /android\.intent\.action\.MAIN/g) === 1
    && countMatches(androidManifestXml, /android\.intent\.category\.LAUNCHER/g) === 1
    && !mainActivityManifestEntry.includes("android.intent.action.MAIN")
    && !mainActivityManifestEntry.includes("android.intent.category.LAUNCHER")
    && mainActivityManifestEntry.includes('android:exported="false"'),
  "Android shell v2 must own the installed launcher and auth-return routes; legacy MainActivity must not be the normal relaunch path"
);
assert(
  voiceWakeServiceKt.includes("NativeShellV2Activity::class.java")
    && voiceWakeServiceKt.includes("private fun wakeForegroundIntent")
    && voiceWakeServiceKt.includes('appendQueryParameter("native_screen", "wake-word")')
    && voiceWakeServiceKt.includes('appendQueryParameter("wake", "off")')
    && !voiceWakeServiceKt.includes("Intent(this, MainActivity::class.java)"),
  "Android wake foregrounding and notification taps must reopen shell v2 directly instead of the legacy MainActivity"
);
assert(
  shellV2ActivityKt.includes("override fun dispatchTouchEvent")
    && shellV2ActivityKt.includes("PREF_FOREGROUND_UI_ACTIVE_UNTIL")
    && shellV2ActivityKt.includes("VOICE_WAKE_UI_MARK_THROTTLE_MS")
    && voiceWakeServiceKt.includes("FOREGROUND_UI_ACTIVE_PREF_READ_INTERVAL_MS")
    && voiceWakeServiceKt.includes("foregroundUiActiveUntilCache"),
  "Android shell v2 touch activity must signal the wake listener to yield without per-frame preference reads"
);
assert(
  androidInputProofHotOpJs.includes("args.componentName || args.component_name")
    && androidInputProofHotOpJs.includes('componentName,')
    && androidInputProofManifest.includes('"componentName"')
    && androidInputProofManifest.includes('"component_name"'),
  "Android input proof hot-op must support explicit component launch so shell v2 can be proven without replacing the default launcher"
);
assert(
  androidInputBudgetPy.includes("def parse_launch_timing")
    && androidInputBudgetPy.includes("launch_total_time_ms")
    && androidInputBudgetPy.includes("launch_wait_time_ms")
    && androidInputBudgetPy.includes('--launch-only')
    && androidInputBudgetPy.includes("Android native launch budget passed without synthetic ADB input.")
    && androidInputBudgetPy.includes('--max-launch-total-ms')
    && androidInputBudgetPy.includes('--max-launch-wait-ms'),
  "Android input budget proof must include launch-only Activity timing budgets so slow native startup cannot pass on swipe metrics alone"
);
assert(
  androidUxReleaseLoopPy.includes('SHELL_V2_COMPONENT = "com.colmeio.wasmagent/.shell.NativeShellV2Activity"')
    && androidUxReleaseLoopPy.includes('parser.add_argument("--shell-v2"')
    && androidUxReleaseLoopPy.includes('parser.add_argument("--run-shell-v2-adb-proof"')
    && androidUxReleaseLoopPy.includes('parser.add_argument("--launch-component"')
    && androidUxReleaseLoopPy.includes('elif args.publish_feed and not args.skip_publish_feed:')
    && !androidUxReleaseLoopPy.includes("elif not args.skip_publish_feed:")
    && androidUxReleaseLoopPy.includes('"reuse_existing_native_release_feed"')
    && androidUxReleaseLoopPy.includes("phase = android_hot_op_install_phase(")
    && androidUxReleaseLoopPy.includes('"acceptedForUxLoop": bool(phase.get("acceptedForUxLoop"))')
    && !androidUxReleaseLoopPy.includes('phase["ok"] or install_phase_usable')
    && androidUxReleaseLoopPy.includes('"shell_v2_adb_relaunch_proof_skipped"')
    && androidUxReleaseLoopPy.includes('input_cmd.extend(["--launch-component", launch_component])')
    && androidUxReleaseLoopPy.includes('"--launch-only", "--no-stop-first"')
    && androidUxReleaseLoopPy.includes('"install_android_apk_via_windows_ui_input_hot_op"')
    && androidUxReleaseLoopPy.includes('"Android APK install without post-install relaunch"')
    && androidUxReleaseLoopPy.includes('"fresh_ui_input_hot_op_install"')
    && !androidUxReleaseLoopPy.includes('"tools/voice/reinstall-android-via-windows-bridge.py"')
    && androidUxReleaseLoopPy.includes('"interrupted": True')
    && androidUxReleaseLoopPy.includes('interrupted_by_user')
    && androidUxReleaseLoopPy.includes('phase.get("label") not in {"install_android_apk_via_windows_bridge", "install_android_apk_via_windows_ui_input_hot_op"}')
    && androidUxReleaseLoopPy.includes('input_cmd.append("--no-prepare-space")')
    && androidUxReleaseLoopPy.includes('"android_ui_input_hot_op_feed_stale"'),
  "Android UX release loop must keep skip-build/feed reuse deterministic, require matching install proof, and keep shell-v2 ADB proof explicit and launch-only"
);

console.log("android lite performance budget ok");
