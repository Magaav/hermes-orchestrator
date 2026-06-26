package com.colmeio.wasmagent.shell

import android.app.Activity
import android.Manifest
import android.content.Intent
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.WebView
import com.colmeio.wasmagent.BuildConfig
import com.colmeio.wasmagent.HermesVoiceWakeService
import com.colmeio.wasmagent.NativeBridgeContract
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder

class NativeShellV2Bridge(
    private val activity: Activity,
    private val config: NativeShellV2Config,
    private val diagnostics: NativeShellV2Diagnostics,
    private val webViewProvider: () -> WebView?,
) {
    @JavascriptInterface
    fun authSessionId(): String = config.authSessionId

    @JavascriptInterface
    fun shellInfo(): String = config.shellInfo().toString()

    @JavascriptInterface
    fun config(): String = config.shellInfo().toString()

    @JavascriptInterface
    fun getNativeState(): String = diagnostics.snapshot(config).toString()

    @JavascriptInterface
    fun getKernelStatus(): String {
        return JSONObject()
            .put("schema", "hermes.wasm_agent.native_kernel_status.v1")
            .put("native.kernel.version", NativeBridgeContract.KERNEL_CONTRACT_VERSION)
            .put("nativeBuildId", config.buildId)
            .put("platform", "android")
            .put("runtime", NativeShellV2Config.SHELL_NAME)
            .put("productionTarget", config.origin)
            .put("supportedCapabilities", JSONArray(NativeShellV2Config.CAPABILITIES))
            .put("unsupportedCapabilities", JSONArray(NativeBridgeContract.allKernelCapabilities.filter {
                !NativeShellV2Config.CAPABILITIES.contains(it)
            }))
            .put("disabledLayers", JSONArray(NativeShellV2Config.DISABLED_LAYERS))
            .put("startupContract", config.startupContract())
            .toString()
    }

    @JavascriptInterface
    fun appReady(payloadJson: String?) {
        diagnostics.markRendererReady(parseJson(payloadJson))
    }

    @JavascriptInterface
    fun logDiagnostic(kind: String, payloadJson: String?) {
        diagnostics.record("renderer_${kind.take(80)}", parseJson(payloadJson))
    }

    @JavascriptInterface
    fun logAuthDiagnostic(kind: String, payloadJson: String?) {
        diagnostics.record("renderer_auth_${kind.take(80)}", parseJson(payloadJson))
    }

    @JavascriptInterface
    fun noteUserInteraction(reason: String?): String {
        diagnostics.record("renderer_user_interaction", JSONObject()
            .put("reason", reason.orEmpty().take(80)))
        return JSONObject().put("ok", true).toString()
    }

    @JavascriptInterface
    fun reload() {
        activity.runOnUiThread {
            diagnostics.record("renderer_reload_requested")
            webViewProvider()?.reload()
        }
    }

    @JavascriptInterface
    fun hardReloadWebRuntime(payloadJson: String?): String {
        val payload = parseJson(payloadJson)
        val reason = payload.optString("reason", "native_control").take(80)
        activity.runOnUiThread {
            val view = webViewProvider()
            diagnostics.record("renderer_hard_reload_requested", JSONObject()
                .put("reason", reason)
                .put("clear_cache", true)
                .put("unregister_service_worker", true))
            if (view == null) {
                diagnostics.record("renderer_hard_reload_failed", JSONObject()
                    .put("reason", reason)
                    .put("error", "webview_unavailable"))
                return@runOnUiThread
            }
            runCatching { CookieManager.getInstance().flush() }
            runCatching { view.clearCache(true) }
            runCatching {
                view.evaluateJavascript("""
                    (async () => {
                      try {
                        if (navigator.serviceWorker?.getRegistrations) {
                          const registrations = await navigator.serviceWorker.getRegistrations();
                          await Promise.all(registrations.map((registration) => registration.unregister()));
                        }
                        if (window.caches?.keys) {
                          const keys = await window.caches.keys();
                          await Promise.all(keys.map((key) => window.caches.delete(key)));
                        }
                      } catch (error) {}
                      return true;
                    })();
                """.trimIndent()) {
                    reloadWithCacheBust(view, reason)
                }
            }.onFailure {
                diagnostics.record("renderer_hard_reload_service_worker_clear_failed", JSONObject()
                    .put("reason", reason)
                    .put("error", it.javaClass.simpleName))
                reloadWithCacheBust(view, reason)
            }
        }
        return JSONObject()
            .put("ok", true)
            .put("command", "hard_reload_web_runtime")
            .put("reloading", true)
            .put("reason", reason)
            .toString()
    }

    @JavascriptInterface
    fun openExternal(url: String, reason: String?) {
        diagnostics.record("renderer_open_external", JSONObject()
            .put("url", url.take(300))
            .put("reason", reason.orEmpty().take(80)))
        activity.runOnUiThread {
            runCatching {
                activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            }.onFailure {
                diagnostics.record("renderer_open_external_failed", JSONObject()
                    .put("error", it.javaClass.simpleName))
            }
        }
    }

    @JavascriptInterface
    fun startGoogleLogin() {
        val loginUrl = config.origin.trimEnd('/') +
            "/native/android/auth/start?session=${encode(config.authSessionId)}" +
            "&native_correlation_id=${encode(config.authSessionId)}" +
            "&build_id=${encode(config.buildId)}" +
            "&device_hash=${encode(config.installDeviceHash)}"
        diagnostics.record("renderer_google_login_start_requested", JSONObject()
            .put("login_url", loginUrl)
            .put("session", config.authSessionId))
        activity.runOnUiThread {
            runCatching {
                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(loginUrl))
                intent.addCategory(Intent.CATEGORY_BROWSABLE)
                activity.startActivity(intent)
            }.onFailure {
                diagnostics.record("renderer_google_login_start_failed", JSONObject()
                    .put("error", it.javaClass.simpleName))
            }
        }
    }

    @JavascriptInterface
    fun flushAuthCookies(payloadJson: String?): String {
        val cookies = CookieManager.getInstance().getCookie(config.origin).orEmpty()
        CookieManager.getInstance().flush()
        diagnostics.record("renderer_auth_cookie_flush_requested", parseJson(payloadJson)
            .put("cookie_count", cookieCount(cookies))
            .put("has_wa_uid", cookies.contains("wa_uid=")))
        return JSONObject()
            .put("ok", true)
            .put("cookieCount", cookieCount(cookies))
            .put("hasWaUid", cookies.contains("wa_uid="))
            .toString()
    }

    @JavascriptInterface
    fun getWakeWordState(): String = wakeWordState().toString()

    @JavascriptInterface
    fun enableVoiceWake(): String {
        if (!recordAudioGranted()) return wakeUnavailable("record_audio_permission_missing").toString()
        activity.runOnUiThread {
            HermesVoiceWakeService.start(activity, config.origin)
        }
        return wakeWordState()
            .put("ok", true)
            .put("command", "enableVoiceWake")
            .put("start_deferred", true)
            .toString()
    }

    @JavascriptInterface
    fun disableVoiceWake(): String {
        activity.runOnUiThread {
            HermesVoiceWakeService.stop(activity)
        }
        return wakeWordState()
            .put("ok", true)
            .put("command", "disableVoiceWake")
            .put("stop_deferred", true)
            .toString()
    }

    @JavascriptInterface
    fun requestVoiceWakePermission(): String {
        return JSONObject()
            .put("ok", recordAudioGranted())
            .put("command", "requestVoiceWakePermission")
            .put("permission", Manifest.permission.RECORD_AUDIO)
            .put("granted", recordAudioGranted())
            .put("requiresUserGesture", !recordAudioGranted())
            .put("message", if (recordAudioGranted()) "record_audio_permission_granted" else "record_audio_permission_required")
            .toString()
    }

    @JavascriptInterface
    fun syncDownloadedRuntime(manifestJson: String?): String =
        unsupported("downloaded_runtime", "Downloaded runtime is not part of shell v2 layer 0").toString()

    @JavascriptInterface
    fun forceSyncDownloadedRuntime(manifestJson: String?): String =
        unsupported("downloaded_runtime", "Downloaded runtime is not part of shell v2 layer 0").toString()

    @JavascriptInterface
    fun rollbackDownloadedRuntime(): String =
        unsupported("downloaded_runtime", "Downloaded runtime is not part of shell v2 layer 0").toString()

    @JavascriptInterface
    fun runDownloadedOperation(operationManifestJson: String?, inputsJson: String?): String {
        val manifest = parseJson(operationManifestJson)
        val operationId = manifest.optString("operationId", manifest.optString("operation", ""))
        val inputs = parseJson(inputsJson)
        return when (operationId) {
            "fetch_wake_word_state", "android.wake_word.state", "fetch_wake_world_state" -> wakeWordState()
                .put("ok", true)
                .put("stable", true)
                .put("operation", operationId)
                .put("failureClassification", "pass")
                .toString()
            "apply_wake_word_policy", "android.wake_word.apply_policy" -> applyWakeWordPolicy(inputs)
                .put("stable", true)
                .put("operation", operationId)
                .put("failureClassification", "pass")
                .toString()
            else -> unsupported("hot_ops", "Downloaded operations are not part of shell v2 layer 0").toString()
        }
    }

    private fun applyWakeWordPolicy(inputs: JSONObject): JSONObject {
        val prefs = activity.getSharedPreferences(HermesVoiceWakeService.PREFS_NAME, Context.MODE_PRIVATE)
        val wakeThreshold = normalizedDouble(inputs, "wake_threshold", "wakeThreshold")
            ?.let { HermesVoiceWakeService.normalizedWakeThreshold(it) }
        val vadRms = normalizedDouble(inputs, "vad_rms_threshold", "vadRmsThreshold")?.coerceIn(0.001, 0.2)
        val vadPeak = normalizedInt(inputs, "vad_peak_threshold", "vadPeakThreshold", HermesVoiceWakeService.DEFAULT_VAD_PEAK_THRESHOLD)?.coerceIn(100, 30000)
        val cooldown = normalizedLong(inputs, "wake_cooldown_ms", "wakeCooldownMs", HermesVoiceWakeService.DEFAULT_WAKE_COOLDOWN_MS)?.coerceIn(500L, 60_000L)
        val frames = normalizedInt(inputs, "wake_confirmation_frames", "wakeConfirmationFrames", HermesVoiceWakeService.DEFAULT_WAKE_CONFIRMATION_FRAMES)?.coerceIn(1, 5)
        val windowMs = normalizedLong(inputs, "wake_confirmation_window_ms", "wakeConfirmationWindowMs", HermesVoiceWakeService.DEFAULT_WAKE_CONFIRMATION_WINDOW_MS)?.coerceIn(150L, 2_000L)
        val sessionId = inputs.optString("tuning_session_id", inputs.optString("tuningSessionId", "")).take(120)
        val editor = prefs.edit()
        wakeThreshold?.let {
            editor.putFloat(HermesVoiceWakeService.PREF_WAKE_THRESHOLD, it.toFloat())
                .putString(HermesVoiceWakeService.PREF_WAKE_THRESHOLD_SOURCE, HermesVoiceWakeService.THRESHOLD_SOURCE_REMOTE_CONFIG)
        }
        vadRms?.let { editor.putFloat(HermesVoiceWakeService.PREF_VAD_RMS_THRESHOLD, it.toFloat()) }
        vadPeak?.let { editor.putInt(HermesVoiceWakeService.PREF_VAD_PEAK_THRESHOLD, it) }
        cooldown?.let { editor.putLong(HermesVoiceWakeService.PREF_WAKE_COOLDOWN_MS, it) }
        frames?.let { editor.putInt(HermesVoiceWakeService.PREF_WAKE_CONFIRMATION_FRAMES, it) }
        windowMs?.let { editor.putLong(HermesVoiceWakeService.PREF_WAKE_CONFIRMATION_WINDOW_MS, it) }
        if (sessionId.isNotBlank()) editor.putString(HermesVoiceWakeService.PREF_TUNING_SESSION_ID, sessionId)
        val committed = editor.commit()
        activity.runOnUiThread {
            val intent = Intent(activity, HermesVoiceWakeService::class.java)
                .setAction(HermesVoiceWakeService.ACTION_STATUS)
                .putExtra(HermesVoiceWakeService.EXTRA_ORIGIN, config.origin)
            wakeThreshold?.let { intent.putExtra(HermesVoiceWakeService.EXTRA_WAKE_THRESHOLD, it) }
            vadRms?.let { intent.putExtra("vad_rms_threshold", it) }
            vadPeak?.let { intent.putExtra("vad_peak_threshold", it) }
            cooldown?.let { intent.putExtra("wake_cooldown_ms", it) }
            frames?.let { intent.putExtra("wake_confirmation_frames", it) }
            windowMs?.let { intent.putExtra("wake_confirmation_window_ms", it) }
            if (sessionId.isNotBlank()) intent.putExtra("tuning_session_id", sessionId)
            startWakeService(intent)
        }
        return JSONObject()
            .put("ok", true)
            .put("preferencesCommitted", committed)
            .put("stateRefreshDeferred", true)
            .put("applied", JSONObject()
                .put("wakeThreshold", wakeThreshold ?: HermesVoiceWakeService.configuredWakeThreshold(activity))
                .put("vadRmsThreshold", vadRms ?: HermesVoiceWakeService.configuredVadRmsThreshold(activity))
                .put("vadPeakThreshold", vadPeak ?: HermesVoiceWakeService.configuredVadPeakThreshold(activity))
                .put("wakeCooldownMs", cooldown ?: HermesVoiceWakeService.configuredWakeCooldownMs(activity))
                .put("wakeConfirmationFrames", frames ?: HermesVoiceWakeService.configuredWakeConfirmationFrames(activity))
                .put("wakeConfirmationWindowMs", windowMs ?: HermesVoiceWakeService.configuredWakeConfirmationWindowMs(activity))
                .put("tuningSessionId", sessionId.ifBlank { prefs.getString(HermesVoiceWakeService.PREF_TUNING_SESSION_ID, "").orEmpty() }))
    }

    private fun wakeWordState(): JSONObject {
        val status = runCatching {
            val file = HermesVoiceWakeService.statusFile(activity)
            if (file.exists()) JSONObject(file.readText()) else JSONObject()
        }.getOrElse { JSONObject().put("status_read_error", it.javaClass.simpleName) }
        val prefs = activity.getSharedPreferences(HermesVoiceWakeService.PREFS_NAME, Context.MODE_PRIVATE)
        return JSONObject()
            .put("schema", "hermes.wasm_agent.android_wake_word_state.v1")
            .put("ok", true)
            .put("build_id", BuildConfig.NATIVE_BUILD_ID)
            .put("enabled", prefs.getBoolean(HermesVoiceWakeService.PREF_ENABLED, false))
            .put("wake_word", HermesVoiceWakeService.configuredWakePhrase(activity))
            .put("threshold", status.optDouble("threshold", HermesVoiceWakeService.configuredWakeThreshold(activity)))
            .put("vad_rms_threshold", status.optDouble("vad_rms_threshold", HermesVoiceWakeService.configuredVadRmsThreshold(activity)))
            .put("vad_peak_threshold", status.optInt("vad_peak_threshold", HermesVoiceWakeService.configuredVadPeakThreshold(activity)))
            .put("wake_engine_ready", status.optBoolean("wake_engine_ready", false))
            .put("wake_service_ready", status.optBoolean("wake_service_ready", status.optBoolean("foreground_service_started", false) && recordAudioGranted()))
            .put("foreground_service_active", status.optBoolean("foreground_service_active", status.optBoolean("foreground_service_started", false)))
            .put("listener_lane", status.optString("listener_lane", if (status.optBoolean("foreground_service_started", false)) "foreground_service" else "off"))
            .put("listener_mode", status.optString("listener_mode", if (status.optBoolean("command_capture_active", false)) "command_capture" else if (status.optBoolean("foreground_service_started", false)) "standby" else "off"))
            .put("permission_state", JSONObject().put("record_audio", recordAudioGranted()))
            .put("inference_count", status.optLong("inference_count", 0L))
            .put("last_confidence", status.optDouble("last_confidence", 0.0))
            .put("raw_wake_detection_count", status.optLong("raw_wake_detection_count", 0L))
            .put("wake_hit_count", status.optLong("wake_hit_count", status.optLong("wake_detection_count", 0L)))
            .put("false_wake_count", status.optLong("false_wake_count", 0L))
            .put("last_error", status.optString("last_error", status.optString("failure_reason", "")))
            .put("voice_wake", status)
    }

    private fun wakeUnavailable(reason: String): JSONObject = wakeWordState()
        .put("ok", false)
        .put("error", reason)
        .put("failureClassification", reason)

    private fun recordAudioGranted(): Boolean =
        activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    private fun startWakeService(intent: Intent) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) activity.startForegroundService(intent) else activity.startService(intent)
    }

    private fun normalizedDouble(inputs: JSONObject, snake: String, camel: String): Double? {
        if (!inputs.has(snake) && !inputs.has(camel)) return null
        return when (val raw = inputs.opt(snake) ?: inputs.opt(camel)) {
            is Number -> raw.toDouble()
            is String -> raw.toDoubleOrNull()
            else -> null
        }?.takeIf { it.isFinite() }
    }

    private fun normalizedInt(inputs: JSONObject, snake: String, camel: String, fallback: Int): Int? {
        if (!inputs.has(snake) && !inputs.has(camel)) return null
        return when (val raw = inputs.opt(snake) ?: inputs.opt(camel)) {
            is Number -> raw.toInt()
            is String -> raw.toIntOrNull() ?: fallback
            else -> fallback
        }
    }

    private fun normalizedLong(inputs: JSONObject, snake: String, camel: String, fallback: Long): Long? {
        if (!inputs.has(snake) && !inputs.has(camel)) return null
        return when (val raw = inputs.opt(snake) ?: inputs.opt(camel)) {
            is Number -> raw.toLong()
            is String -> raw.toLongOrNull() ?: fallback
            else -> fallback
        }
    }

    private fun unsupported(layer: String, message: String): JSONObject {
        return JSONObject()
            .put("ok", false)
            .put("unsupported", true)
            .put("layer", layer)
            .put("message", message)
            .put("shell", NativeShellV2Config.SHELL_NAME)
    }

    private fun parseJson(payloadJson: String?): JSONObject {
        val text = payloadJson.orEmpty().trim()
        if (text.isBlank()) return JSONObject()
        return runCatching { JSONObject(text) }.getOrElse {
            JSONObject().put("raw", text.take(500))
        }
    }

    private fun cookieCount(cookies: String): Int {
        return if (cookies.isBlank()) 0 else cookies.split(";").size
    }

    private fun reloadWithCacheBust(view: WebView, reason: String) {
        val current = view.url.orEmpty().ifBlank { config.homeUrl() }
        val separator = if (current.contains("?")) "&" else "?"
        val url = "$current${separator}native_refresh=${System.currentTimeMillis()}"
        diagnostics.record("renderer_hard_reload_running", JSONObject()
            .put("reason", reason)
            .put("url", url.take(300)))
        view.loadUrl(url)
    }

    private fun encode(value: String): String = URLEncoder.encode(value, "UTF-8")
}
