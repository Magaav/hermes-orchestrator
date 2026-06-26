package com.colmeio.wasmagent

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.DownloadManager
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.net.Uri
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Looper
import android.provider.Settings
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Base64
import android.util.Log
import android.view.Gravity
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.DownloadListener
import android.webkit.GeolocationPermissions
import android.webkit.JavascriptInterface
import android.webkit.PermissionRequest
import android.webkit.RenderProcessGoneDetail
import android.webkit.SslErrorHandler
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebStorage
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import com.colmeio.wasmagent.voice.WakeModelSelector
import com.colmeio.wasmagent.voice.FalseWakeStore
import com.colmeio.wasmagent.voice.LocalCommandTranscriptionEngine
import com.colmeio.wasmagent.voice.OpenWakeWordBundleEngine
import com.colmeio.wasmagent.voice.OpenWakeWordOnnxEngine
import com.colmeio.wasmagent.voice.VoiceTuningCategory
import com.colmeio.wasmagent.voice.VoiceTuningRecorder
import com.colmeio.wasmagent.voice.VoiceTuningStore
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.security.MessageDigest
import java.util.Locale
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.zip.ZipInputStream
import kotlin.concurrent.thread
import kotlin.math.abs
import kotlin.math.roundToInt
import kotlin.math.sqrt

class MainActivity : Activity() {
    companion object {
        private const val PREFS_NAME = "wasm_agent_android_shell"
        private const val PREF_ANDROID_AUTH_SESSION = "android_auth_session"
        private const val PREF_NATIVE_CORRELATION_ID = "native_correlation_id"
        private const val PREF_INSTALL_ID = "install_id"
        private const val PREF_LAST_URL = "last_url"
        private const val PREF_SELECTED_ORIGIN = "selected_origin"
        private const val PREF_ACTIVE_RUNTIME_ID = "active_downloaded_runtime_id"
        private const val PREF_ACTIVE_RUNTIME_SHA = "active_downloaded_runtime_sha"
        private const val PREF_ACTIVE_RUNTIME_MANIFEST_SHA = "active_downloaded_runtime_manifest_sha"
        private const val PREF_ACTIVE_RUNTIME_SYNCED_AT = "active_downloaded_runtime_synced_at"
        private const val PREF_LAST_GOOD_RUNTIME_ID = "last_good_downloaded_runtime_id"
        private const val PREF_LAST_GOOD_RUNTIME_SHA = "last_good_downloaded_runtime_sha"
        private const val PREF_LAST_RUNTIME_SYNC_STATUS = "last_downloaded_runtime_sync_status"
        private const val PREF_ACTIVE_HOT_OP_ID = "active_hot_op_bundle_id"
        private const val PREF_ACTIVE_HOT_OP_SHA = "active_hot_op_bundle_sha"
        private const val STATE_WEBVIEW = "wasm_agent_webview_state"
        private const val STATE_SELECTED_ORIGIN = "wasm_agent_selected_origin"
        private const val EXTRA_DEBUG_SCREEN = "debug_screen"
        private const val EXTRA_CLEAR_WEBVIEW_DATA = "clear_webview_data"
        private const val EXTRA_NATIVE_SCREEN = "native_screen"
        private val LEGACY_FETCH_WAKE_WORD_STATE_OPERATION = listOf("fetch_wake", "world_state").joinToString("_")
        private val LEGACY_PROVE_WAKE_WORD_LOOP_OPERATION = listOf("prove_wake", "world_loop").joinToString("_")
        private const val LOG_TAG = "WasmAgentNative"
        private const val REQUEST_FILE_CHOOSER = 8801
        private const val REQUEST_WEB_PERMISSIONS = 8802
        private const val REQUEST_GEOLOCATION_PERMISSION = 8803
        private const val REQUEST_VOICE_WAKE_PERMISSION = 8804
        private const val HERMES_WAKE_ACCEPTANCE_MODEL_SHA256 = "2abbebf21610f91f8d1fcfc12ac92f8ec19dc1191f3c90dbda4cba46e71027b2"
        private const val VOICE_WAKE_UI_ACTIVE_WINDOW_MS = 4_000L
        private const val BOOT_CONSOLE_FORWARD_LIMIT = 12
        private const val CONSOLE_FORWARD_MIN_INTERVAL_MS = 1_200L
        private const val BRAND_BG = 0xFF050A12.toInt()
        private const val BRAND_PANEL = 0xFF0E1726.toInt()
        private const val BRAND_TEXT = 0xFFEFF6FF.toInt()
        private const val BRAND_MUTED = 0xFFA7B4C8.toInt()
        private const val BRAND_ACCENT = 0xFF7DDCFF.toInt()
    }

    private lateinit var container: FrameLayout
    private var webView: WebView? = null
    private var webViewOrigin: String = ""
    private var splashView: View? = null
    private var errorView: View? = null
    private var filePathCallback: ValueCallback<Array<Uri>>? = null
    private var pendingWebPermissionRequest: PermissionRequest? = null
    private var pendingGeolocationCallback: GeolocationPermissions.Callback? = null
    private var pendingGeolocationOrigin: String = ""
    @Volatile private var selectedOrigin: String = ""
    @Volatile private var latestWebViewUrl: String = ""
    @Volatile private var activityCreatedAt: Long = 0
    @Volatile private var firstLoadUrlAt: Long = 0
    @Volatile private var webViewPageStartedAt: Long = 0
    @Volatile private var webViewPageFinishedAt: Long = 0
    @Volatile private var webViewPageCommitVisibleAt: Long = 0
    @Volatile private var webViewMainFrameError: JSONObject? = null
    @Volatile private var lastRendererReadiness: JSONObject? = null
    @Volatile private var backendProbeStartedAt: Long = 0
    @Volatile private var backendProbeFinishedAt: Long = 0
    @Volatile private var backendProbeSelectedOrigin: String = ""
    @Volatile private var backendProbeResult: String = "not_started"
    @Volatile private var bridgeCallsDuringBoot: Long = 0
    @Volatile private var rendererDiagnosticsDuringBoot: Long = 0
    @Volatile private var nativeDiagnosticsWritesDuringBoot: Long = 0
    @Volatile private var webViewConsoleSeenCount: Long = 0
    @Volatile private var webViewConsoleForwardedCount: Long = 0
    @Volatile private var webViewConsoleDroppedCount: Long = 0
    @Volatile private var lastConsoleForwardAt: Long = 0
    @Volatile private var pendingPerfSafeMode: Boolean = false
    @Volatile private var pendingWakeParam: String = ""
    @Volatile private var pendingBridgeDiagnosticsParam: String = ""
    @Volatile private var postFirstLoadBootDiagnosticsScheduled: Boolean = false
    private val prefs by lazy { getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE) }
    private val diagnostics by lazy { NativeDiagnostics(File(filesDir, "native-diagnostics/latest.json")) }
    private val modelShaCacheLock = Any()
    private val diagnosticsSnapshotLock = Any()
    @Volatile private var androidAuthSessionId: String = ""
    @Volatile private var nativeCorrelationId: String = ""
    @Volatile private var installDeviceHash: String = ""
    @Volatile private var androidAuthPollToken: Int = 0
    @Volatile private var waitingForAndroidAuth: Boolean = false
    @Volatile private var oauthStage: String = "IDLE"
    @Volatile private var oauthResult: String = ""
    @Volatile private var lastAndroidReturnIntentAt: Long = 0
    @Volatile private var lastAndroidReturnSessionId: String = ""
    @Volatile private var lastDiagnosticsUploadAt: Long = 0
    @Volatile private var diagnosticsSnapshotScheduled: Boolean = false
    @Volatile private var diagnosticsSnapshotPending: Boolean = false
    @Volatile private var diagnosticsSnapshotReason: String = ""
    @Volatile private var diagnosticsUploadReason: String = ""
    @Volatile private var lastVoiceWakeUiActivityMarkAt: Long = 0
    @Volatile private var cachedModelShaPath: String = ""
    @Volatile private var cachedModelShaModifiedAt: Long = -1L
    @Volatile private var cachedModelShaSize: Long = -1L
    @Volatile private var cachedModelSha: String = ""
    @Volatile private var pendingDebugScreen: String = ""
    private var lastIntentSummary: JSONObject? = null
    private var lastDeepLinkSummary: JSONObject? = null
    private var lastExceptionSummary: JSONObject? = null
    private val voiceTuningStore by lazy { VoiceTuningStore(File(filesDir, "voice/hermes-dataset")) }
    private val voiceTuningRecorder by lazy {
        VoiceTuningRecorder(this, voiceTuningStore) { nativeDeviceLabel() }
    }
    private val candidates: List<String> by lazy {
        buildList {
            add(BuildConfig.DEFAULT_SERVER_URL)
            if (BuildConfig.ALLOW_LOCAL_DEV) {
                BuildConfig.LOCAL_DEV_SERVER_URLS
                    .split(",")
                    .map { candidate -> candidate.trim() }
                    .filter { candidate -> candidate.isNotEmpty() }
                    .forEach { candidate -> add(candidate) }
            }
        }.distinct()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        activityCreatedAt = System.currentTimeMillis()
        configureWindow()
        container = FrameLayout(this)
        container.setBackgroundColor(BRAND_BG)
        setContentView(container)
        showSplash("WASM Agent", "Connecting to wa.colmeio.com")
        androidAuthSessionId = getOrCreateAndroidAuthSessionId()
        nativeCorrelationId = getOrCreateNativeCorrelationId()
        installDeviceHash = getOrCreateInstallDeviceHash()
        logDiagnostic("activity_on_create", JSONObject()
            .put("has_saved_state", savedInstanceState != null)
            .put("build_id", BuildConfig.NATIVE_BUILD_ID)
            .put("shell", "android-webview")
            .put("voice_wake_boot_reconciliation", "deferred_until_after_first_load"))
        handleLaunchIntent(intent, "activity_create")

        val savedOrigin = savedInstanceState?.getString(STATE_SELECTED_ORIGIN).orEmpty()
        if (savedOrigin.isNotBlank()) {
            val restoredOrigin = immediateLaunchOrigin(savedOrigin)
            selectedOrigin = restoredOrigin
            openRemotePwaWebView(restoredOrigin, null)
            scheduleBackendProbeDiagnostics("restore_state")
            return
        }
        resolveBackend()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString(STATE_SELECTED_ORIGIN, selectedOrigin)
        val webViewState = Bundle()
        webView?.saveState(webViewState)
        outState.putBundle(STATE_WEBVIEW, webViewState)
        webView?.url?.let {
            latestWebViewUrl = it
            prefs.edit().putString(PREF_LAST_URL, it).apply()
        }
        logDiagnostic("activity_save_instance_state", JSONObject()
            .put("selected_origin", selectedOrigin)
            .put("url", latestWebViewUrl))
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        logDiagnostic("activity_configuration_changed", JSONObject()
            .put("orientation", newConfig.orientation)
            .put("screen_width_dp", newConfig.screenWidthDp)
            .put("screen_height_dp", newConfig.screenHeightDp))
        emitRendererEvent("wasm-agent:native-configuration", JSONObject()
            .put("orientation", newConfig.orientation)
            .put("screenWidthDp", newConfig.screenWidthDp)
            .put("screenHeightDp", newConfig.screenHeightDp))
    }

	    override fun onResume() {
	        super.onResume()
	        webView?.onResume()
	        markVoiceWakeUiActivity("activity_resume")
	        logDiagnostic("activity_resume", JSONObject()
            .put("waiting_for_android_auth", waitingForAndroidAuth)
            .put("selected_origin", selectedOrigin))
        if (waitingForAndroidAuth && selectedOrigin.isNotBlank()) {
            val returnedViaIntent = System.currentTimeMillis() - lastAndroidReturnIntentAt < 2000
            if (!returnedViaIntent) {
                transitionOAuth("AUTH_CANCELED", "activity_resumed_without_return_intent", JSONObject()
                    .put("selected_origin", selectedOrigin))
                emitRendererEvent("wasm-agent:native-android-auth-canceled", JSONObject()
                    .put("reason", "activity_resume_without_auth_code")
                    .put("session", androidAuthSessionId)
                    .put("native_correlation_id", nativeCorrelationId))
            }
            pollAndroidAuth(selectedOrigin, "activity_resume")
        }
    }

	    override fun onPause() {
	        CookieManager.getInstance().flush()
	        webView?.onPause()
	        clearVoiceWakeUiActivity("activity_pause")
	        logDiagnostic("activity_pause", JSONObject()
            .put("url", latestWebViewUrl)
            .put("selected_origin", selectedOrigin))
        super.onPause()
    }

    override fun onDestroy() {
        logDiagnostic("activity_destroy", JSONObject()
            .put("finishing", isFinishing)
            .put("changing_configurations", isChangingConfigurations))
        if (isFinishing) {
            webView?.stopLoading()
        }
        super.onDestroy()
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleLaunchIntent(intent, "activity_new_intent")
    }

    override fun onBackPressed() {
        val current = webView
        logDiagnostic("back_button_pressed", JSONObject()
            .put("can_go_back", current?.canGoBack() == true)
            .put("url", latestWebViewUrl))
        emitRendererEvent("wasm-agent:native-back", JSONObject()
            .put("canGoBack", current?.canGoBack() == true)
            .put("url", latestWebViewUrl))
        if (current?.canGoBack() == true) {
            current.goBack()
            logDiagnostic("back_button_webview_go_back")
            return
        }
        moveTaskToBack(true)
        logDiagnostic("back_button_task_moved_to_back")
    }

    private fun handleLaunchIntent(intent: Intent?, reason: String) {
        val summary = summarizeIntent(intent, reason)
        lastIntentSummary = summary
        logDiagnostic("activity_intent_observed", summary)
        val debugScreen = intent?.getStringExtra(EXTRA_DEBUG_SCREEN).orEmpty()
            .ifBlank { intent?.getStringExtra(EXTRA_NATIVE_SCREEN).orEmpty() }
        if (debugScreen.isNotBlank()) {
            pendingDebugScreen = debugScreen
            logDiagnostic("activity_debug_screen_requested", JSONObject()
                .put("reason", reason)
                .put("debug_screen", debugScreen))
            if (debugScreen == "export-hermes-dataset") {
                triggerHermesDatasetExport("debug_intent")
            } else if (debugScreen == "hermes-wake-proof") {
                beginHermesWakeProof("debug_intent", thresholdFromIntent(intent))
            }
        }
        if (intent?.getBooleanExtra(EXTRA_CLEAR_WEBVIEW_DATA, false) == true) {
            clearWebViewData("launch_intent")
            logDiagnostic("activity_clear_webview_requested", JSONObject()
                .put("reason", reason)
                .put("debug_screen", debugScreen))
        }
        val data = intent?.data ?: return
        captureNativePerformanceFlags(data)
        lastDeepLinkSummary = JSONObject()
            .put("reason", reason)
            .put("data", data.toString())
            .put("scheme", data.scheme.orEmpty())
            .put("host", data.host.orEmpty())
        logDiagnostic("activity_intent_data_observed", lastDeepLinkSummary ?: JSONObject())
        val requestedScreen = data.getQueryParameter(EXTRA_NATIVE_SCREEN).orEmpty()
        if (requestedScreen.isNotBlank()) {
            pendingDebugScreen = requestedScreen
            logDiagnostic("activity_debug_screen_url_requested", JSONObject()
                .put("reason", reason)
                .put("debug_screen", requestedScreen))
            if (requestedScreen == "hermes-wake-proof") {
                beginHermesWakeProof("debug_url", thresholdFromData(data))
            }
        }
        val isCustomSchemeReturn = data.scheme == "wasm-agent" && data.host == "android-auth-return"
        val isHttpsReturn = data.scheme == "https" && data.host == "wa.colmeio.com" && data.path.orEmpty().startsWith("/native/android/auth/return")
        if (!isCustomSchemeReturn && !isHttpsReturn) return
        lastAndroidReturnIntentAt = System.currentTimeMillis()
        val incomingCorrelationId = data.getQueryParameter("native_correlation_id").orEmpty()
        if (incomingCorrelationId.isNotBlank()) {
            nativeCorrelationId = incomingCorrelationId
            prefs.edit().putString(PREF_NATIVE_CORRELATION_ID, incomingCorrelationId).apply()
        }
        val sessionMatches = data.getQueryParameter("session").orEmpty() == androidAuthSessionId
        transitionOAuth("NATIVE_RETURN_PAGE_OBSERVED", "deep_link_received", JSONObject()
            .put("reason", reason)
            .put("session_matches", sessionMatches))
        transitionOAuth("ANDROID_INTENT_RECEIVED", "deep_link_received", JSONObject()
            .put("reason", reason)
            .put("session_matches", sessionMatches))
        logDiagnostic("android_auth_return_intent_received", JSONObject()
            .put("reason", reason)
            .put("session_matches", sessionMatches)
            .put("selected_origin", selectedOrigin)
            .put("package_targeted", intent.`package` == packageName || intent.component?.packageName == packageName))
        if (!sessionMatches) {
            waitingForAndroidAuth = false
            transitionOAuth("AUTH_ERROR", "session_mismatch")
            logDiagnostic("android_auth_return_intent_ignored", JSONObject()
                .put("reason", "session_mismatch"))
            return
        }
        lastAndroidReturnSessionId = androidAuthSessionId
        waitingForAndroidAuth = true
        val pollOrigin = selectedOrigin
            .ifBlank { prefs.getString(PREF_SELECTED_ORIGIN, "").orEmpty() }
            .ifBlank { BuildConfig.DEFAULT_SERVER_URL }
        pollAndroidAuth(pollOrigin, "return_intent")
        emitRendererEvent("wasm-agent:native-android-auth-return", JSONObject()
            .put("reason", reason)
            .put("session", androidAuthSessionId)
            .put("native_correlation_id", nativeCorrelationId))
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        if (keyCode == KeyEvent.KEYCODE_R && event.isCtrlPressed) {
            if (event.isShiftPressed) {
                webView?.clearCache(true)
                logDiagnostic("keyboard_reload_clear_cache")
            } else {
                logDiagnostic("keyboard_reload")
            }
            webView?.reload()
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

	    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == REQUEST_FILE_CHOOSER) {
            val result = if (resultCode == RESULT_OK) {
                WebChromeClient.FileChooserParams.parseResult(resultCode, data)
            } else {
                null
            }
            filePathCallback?.onReceiveValue(result)
            filePathCallback = null
            logDiagnostic("file_picker_result", JSONObject()
                .put("result_code", resultCode)
                .put("uri_count", result?.size ?: 0))
            return
        }
	        super.onActivityResult(requestCode, resultCode, data)
	    }

	    override fun dispatchTouchEvent(event: MotionEvent?): Boolean {
	        if (event?.actionMasked == MotionEvent.ACTION_DOWN || event?.actionMasked == MotionEvent.ACTION_MOVE) {
	            markVoiceWakeUiActivity("native_touch")
	        }
	        return super.dispatchTouchEvent(event)
	    }

	    private fun markVoiceWakeUiActivity(reason: String = "ui") {
	        val now = System.currentTimeMillis()
	        if (now - lastVoiceWakeUiActivityMarkAt < 650L) return
	        lastVoiceWakeUiActivityMarkAt = now
	        thread(name = "voice-wake-ui-activity") {
	            prefs.edit()
	                .putLong(HermesVoiceWakeService.PREF_FOREGROUND_UI_ACTIVE_UNTIL, now + VOICE_WAKE_UI_ACTIVE_WINDOW_MS)
	                .apply()
	            logDiagnostic("voice_wake_ui_activity_marked", JSONObject()
	                .put("reason", reason)
	                .put("active_for_ms", VOICE_WAKE_UI_ACTIVE_WINDOW_MS))
	        }
	    }

	    private fun clearVoiceWakeUiActivity(reason: String = "ui_idle") {
	        thread(name = "voice-wake-ui-activity-clear") {
	            prefs.edit()
	                .putLong(HermesVoiceWakeService.PREF_FOREGROUND_UI_ACTIVE_UNTIL, 0L)
	                .apply()
	            logDiagnostic("voice_wake_ui_activity_cleared", JSONObject().put("reason", reason))
	        }
	    }

	    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        when (requestCode) {
            REQUEST_WEB_PERMISSIONS -> finishPendingWebPermissionRequest(permissions, grantResults)
            REQUEST_GEOLOCATION_PERMISSION -> finishPendingGeolocationRequest(permissions, grantResults)
            REQUEST_VOICE_WAKE_PERMISSION -> finishVoiceWakePermissionRequest(permissions, grantResults)
        }
    }

    private fun configureWindow() {
        window.statusBarColor = BRAND_BG
        window.navigationBarColor = BRAND_BG
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            window.navigationBarDividerColor = BRAND_BG
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.setDecorFitsSystemWindows(true)
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_VISIBLE
        }
    }

    private fun getOrCreateAndroidAuthSessionId(): String {
        val existing = prefs.getString(PREF_ANDROID_AUTH_SESSION, "").orEmpty()
        if (existing.isNotBlank()) return existing
        val created = UUID.randomUUID().toString()
        prefs.edit().putString(PREF_ANDROID_AUTH_SESSION, created).apply()
        return created
    }

    private fun rotateAndroidAuthSessionId(): String {
        val created = UUID.randomUUID().toString()
        androidAuthSessionId = created
        lastAndroidReturnIntentAt = 0
        lastAndroidReturnSessionId = ""
        prefs.edit().putString(PREF_ANDROID_AUTH_SESSION, created).apply()
        logDiagnostic("android_auth_session_rotated", JSONObject()
            .put("session", created))
        return created
    }

    private fun getOrCreateNativeCorrelationId(): String {
        val existing = prefs.getString(PREF_NATIVE_CORRELATION_ID, "").orEmpty()
        if (existing.isNotBlank()) return existing
        val created = "wa-android-${UUID.randomUUID()}"
        prefs.edit().putString(PREF_NATIVE_CORRELATION_ID, created).apply()
        return created
    }

    private fun rotateNativeCorrelationId(): String {
        val created = "wa-android-${UUID.randomUUID()}"
        nativeCorrelationId = created
        prefs.edit().putString(PREF_NATIVE_CORRELATION_ID, created).apply()
        logDiagnostic("native_correlation_rotated", JSONObject()
            .put("native_correlation_id", created))
        return created
    }

    private fun getOrCreateInstallDeviceHash(): String {
        val existingInstallId = prefs.getString(PREF_INSTALL_ID, "").orEmpty()
        val installId = existingInstallId.ifBlank {
            UUID.randomUUID().toString().also { created ->
                prefs.edit().putString(PREF_INSTALL_ID, created).apply()
            }
        }
        val androidId = try {
            Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID).orEmpty()
        } catch (_: Exception) {
            ""
        }
        return sha256Hex("${packageName}|$installId|$androidId").take(24)
    }

    private fun resolveBackend() {
        val immediateOrigin = immediateLaunchOrigin()
        val selected = immediateOrigin
        selectedOrigin = selected
        prefs.edit().putString(PREF_SELECTED_ORIGIN, selected).apply()
        logDiagnostic("backend_resolve_bypassed_for_instant_load", JSONObject()
            .put("selected_origin", selected)
            .put("candidates", JSONArray(candidates))
            .put("allow_local_dev", BuildConfig.ALLOW_LOCAL_DEV)
            .put("first_load_not_blocked_by_probe", true))
        openRemotePwaWebView(selected)
        scheduleBackendProbeDiagnostics("post_first_load")
    }

    private fun immediateLaunchOrigin(candidate: String = ""): String {
        val restored = candidate.trim()
        val persisted = prefs.getString(PREF_SELECTED_ORIGIN, "").orEmpty().trim()
        val selected = restored.ifBlank { persisted }.ifBlank { BuildConfig.DEFAULT_SERVER_URL }.trimEnd('/')
        if (BuildConfig.ALLOW_LOCAL_DEV) return selected
        val defaultOrigin = BuildConfig.DEFAULT_SERVER_URL.trimEnd('/')
        val selectedHost = runCatching { Uri.parse(selected).host.orEmpty().lowercase() }.getOrDefault("")
        val defaultHost = runCatching { Uri.parse(defaultOrigin).host.orEmpty().lowercase() }.getOrDefault("")
        return if (selectedHost == defaultHost && selected.startsWith("https://")) selected else defaultOrigin
    }

    private fun captureNativePerformanceFlags(data: Uri) {
        val perfSafeMode = data.getQueryParameter("perfSafeMode")
            ?: data.getQueryParameter("perf_safe_mode")
        if (perfSafeMode != null) {
            pendingPerfSafeMode = perfSafeMode == "1" ||
                perfSafeMode.equals("true", ignoreCase = true) ||
                perfSafeMode.equals("yes", ignoreCase = true)
        }
        pendingWakeParam = data.getQueryParameter("wake").orEmpty().take(32)
        pendingBridgeDiagnosticsParam = data.getQueryParameter("bridgeDiagnostics")
            .orEmpty()
            .ifBlank { data.getQueryParameter("bridge_diagnostics").orEmpty() }
            .take(32)
    }

    private fun scheduleBackendProbeDiagnostics(reason: String) {
        if (backendProbeStartedAt > 0L) return
        backendProbeStartedAt = System.currentTimeMillis()
        backendProbeResult = "running"
        logDiagnostic("backend_probe_diagnostics_scheduled", JSONObject()
            .put("reason", reason)
            .put("first_load_url_at", firstLoadUrlAt)
            .put("probe_blocks_first_load", false))
        thread(name = "wasm-agent-origin-probe") {
            val selected = candidates.firstOrNull { candidate -> identifiesWasmAgent(candidate) }
            backendProbeFinishedAt = System.currentTimeMillis()
            backendProbeSelectedOrigin = selected.orEmpty()
            backendProbeResult = if (selected == null) "no_candidate_identified" else "identified"
            if (selected != null && BuildConfig.ALLOW_LOCAL_DEV && selected != selectedOrigin) {
                selectedOrigin = selected
                prefs.edit().putString(PREF_SELECTED_ORIGIN, selected).apply()
            }
            logDiagnostic("backend_probe_diagnostics_finished", JSONObject()
                .put("reason", reason)
                .put("selected_origin", selected.orEmpty())
                .put("result", backendProbeResult)
                .put("elapsed_ms", backendProbeFinishedAt - backendProbeStartedAt)
                .put("first_load_url_at", firstLoadUrlAt)
                .put("probe_blocks_first_load", false))
        }
    }

    private fun noteBridgeCall(name: String) {
        if (webViewPageCommitVisibleAt == 0L) bridgeCallsDuringBoot += 1
        if (name.contains("diagnostic", ignoreCase = true)) rendererDiagnosticsDuringBoot += 1
    }

    private fun shouldForwardConsoleDiagnostic(level: String): Boolean {
        val now = System.currentTimeMillis()
        webViewConsoleSeenCount += 1
        val important = level == "error" || level == "warning"
        val booting = webViewPageCommitVisibleAt == 0L || now - activityCreatedAt < 12_000L
        val underBootLimit = booting && webViewConsoleForwardedCount < BOOT_CONSOLE_FORWARD_LIMIT
        val intervalElapsed = now - lastConsoleForwardAt >= CONSOLE_FORWARD_MIN_INTERVAL_MS
        val forward = important || underBootLimit || (!booting && intervalElapsed)
        if (forward) {
            webViewConsoleForwardedCount += 1
            lastConsoleForwardAt = now
        } else {
            webViewConsoleDroppedCount += 1
        }
        return forward
    }

    private fun bridgeDiagnosticsMode(): String {
        return pendingBridgeDiagnosticsParam.ifBlank { if (pendingPerfSafeMode) "off" else "sampled" }
    }

    private fun wakeStartupMode(): String {
        return pendingWakeParam.ifBlank { if (pendingPerfSafeMode) "off" else "deferred" }
    }

    private fun healthProbesMode(): String {
        return if (pendingPerfSafeMode) "off" else "afterFirstPaint"
    }

    private fun bootPerformanceFlags(): JSONObject {
        return JSONObject()
            .put("perfSafeMode", pendingPerfSafeMode)
            .put("wake", wakeStartupMode())
            .put("bridgeDiagnostics", bridgeDiagnosticsMode())
            .put("healthProbes", healthProbesMode())
            .put("startup", "instant")
    }

    private fun webViewBootMetrics(): JSONObject {
        val now = System.currentTimeMillis()
        return JSONObject()
            .put("activity_created_at", activityCreatedAt)
            .put("first_load_url_at", firstLoadUrlAt)
            .put("first_load_url_delta_ms", if (firstLoadUrlAt > 0L) firstLoadUrlAt - activityCreatedAt else JSONObject.NULL)
            .put("page_started_delta_ms", if (webViewPageStartedAt > 0L) webViewPageStartedAt - activityCreatedAt else JSONObject.NULL)
            .put("page_commit_visible_delta_ms", if (webViewPageCommitVisibleAt > 0L) webViewPageCommitVisibleAt - activityCreatedAt else JSONObject.NULL)
            .put("page_finished_delta_ms", if (webViewPageFinishedAt > 0L) webViewPageFinishedAt - activityCreatedAt else JSONObject.NULL)
            .put("backend_probe_started_at", backendProbeStartedAt)
            .put("backend_probe_finished_at", backendProbeFinishedAt)
            .put("backend_probe_result", backendProbeResult)
            .put("backend_probe_selected_origin", backendProbeSelectedOrigin)
            .put("backend_probe_blocks_first_load", false)
            .put("bridge_calls_during_boot", bridgeCallsDuringBoot)
            .put("renderer_diagnostics_during_boot", rendererDiagnosticsDuringBoot)
            .put("diagnostics_writes_during_boot", nativeDiagnosticsWritesDuringBoot)
            .put("console_messages_seen", webViewConsoleSeenCount)
            .put("console_messages_forwarded", webViewConsoleForwardedCount)
            .put("console_messages_dropped", webViewConsoleDroppedCount)
            .put("boot_flags", bootPerformanceFlags())
            .put("age_ms", if (activityCreatedAt > 0L) now - activityCreatedAt else 0)
    }

    private fun resolveBackendLegacyGateDisabled() {
        // Kept as a named breadcrumb for source checks: backend probing is now diagnostics-only.
        scheduleBackendProbeDiagnostics("legacy_gate_disabled")
    }

    private fun identifiesWasmAgent(origin: String): Boolean {
        return listOf("/config.json", "/health", "/healthz").any { path ->
            try {
                val connection = URL(origin.trimEnd('/') + path).openConnection() as HttpURLConnection
                connection.connectTimeout = 2000
                connection.readTimeout = 2500
                connection.requestMethod = "GET"
                connection.setRequestProperty("X-Wasm-Agent-Native-Probe", "wasm-agent")
                val body = connection.inputStream.bufferedReader().use { it.readText() }.lowercase()
                val identified = connection.responseCode in 200..299 &&
                    !body.contains("colmeio admin") &&
                    !body.contains("google_login_client_id") &&
                    (body.contains("\"appid\"") && body.contains("wasm-agent") ||
                        body.contains("\"service\"") && body.contains("wasm-agent") ||
                        body.contains("\"name\"") && body.contains("wasm-agent"))
                logDiagnostic("backend_probe_response", JSONObject()
                    .put("origin", origin)
                    .put("path", path)
                    .put("status_code", connection.responseCode)
                    .put("identified", identified))
                identified
            } catch (error: Exception) {
                logDiagnostic("backend_probe_error", JSONObject()
                    .put("origin", origin)
                    .put("path", path)
                    .put("error", error.javaClass.simpleName))
                false
            }
        }
    }

    private fun pwaHomeUrl(origin: String, authCode: String = ""): String {
        val builder = Uri.parse(origin.trimEnd('/') + "/home").buildUpon()
            .appendQueryParameter("native", "android")
            .appendQueryParameter("shell", "android-webview")
            .appendQueryParameter("android_shell", "android-webview")
            .appendQueryParameter("android_runtime", "user-full")
            .appendQueryParameter("android_startup", "instant")
            .appendQueryParameter("healthProbes", healthProbesMode())
            .appendQueryParameter("wake", wakeStartupMode())
            .appendQueryParameter("bridgeDiagnostics", bridgeDiagnosticsMode())
            .appendQueryParameter("buildId", BuildConfig.NATIVE_BUILD_ID)
            .appendQueryParameter("webBuildHint", BuildConfig.BUILD_GENERATED_AT)
            .appendQueryParameter("native_correlation_id", nativeCorrelationId)
            .appendQueryParameter("android_auth_session", androidAuthSessionId)
            .appendQueryParameter("install_device_hash", installDeviceHash)
        if (pendingPerfSafeMode) {
            builder.appendQueryParameter("perfSafeMode", "1")
        }
        if (pendingDebugScreen.isNotBlank()) {
            builder.appendQueryParameter("native_screen", pendingDebugScreen)
        }
        if (authCode.isNotBlank()) {
            builder.appendQueryParameter("auth_code", authCode)
        }
        return builder.build().toString()
    }

    private fun openRemotePwaWebView(origin: String) {
        openRemotePwaWebView(origin, null)
    }

    private fun openRemotePwaWebView(origin: String, restoreState: Bundle?) {
        selectedOrigin = origin
        val view = if (webView == null || webViewOrigin != origin) {
            webView?.let { container.removeView(it) }
            createConfiguredWebView(origin).also {
                webView = it
                webViewOrigin = origin
                container.addView(it, 0)
            }
        } else {
            webView!!
        }
        hideErrorScreen()
        view.layoutParams = FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT,
        )
        val restored = restoreState != null && view.restoreState(restoreState) != null
        if (restored) {
            latestWebViewUrl = view.url.orEmpty().ifBlank { prefs.getString(PREF_LAST_URL, "").orEmpty() }
            view.alpha = 1f
            hideSplash()
            logDiagnostic("webview_state_restored", JSONObject()
                .put("origin", origin)
                .put("url", latestWebViewUrl))
        } else {
            val url = pwaHomeUrl(origin)
            latestWebViewUrl = url
            webViewPageStartedAt = 0
            webViewPageFinishedAt = 0
            webViewPageCommitVisibleAt = 0
            webViewMainFrameError = null
            lastRendererReadiness = null
            if (firstLoadUrlAt == 0L) firstLoadUrlAt = System.currentTimeMillis()
            prefs.edit().putString(PREF_LAST_URL, url).apply()
            logDiagnostic("webview_load_url", JSONObject()
                .put("url", url)
                .put("deterministic_boot", true)
                .put("first_load_url_at", firstLoadUrlAt)
                .put("activity_created_at", activityCreatedAt)
                .put("delta_ms", firstLoadUrlAt - activityCreatedAt)
                .put("boot_flags", bootPerformanceFlags()))
            view.alpha = 0f
            view.loadUrl(url)
            schedulePostFirstLoadBootDiagnostics("webview_load_url")
        }
    }

    private fun schedulePostFirstLoadBootDiagnostics(reason: String) {
        if (postFirstLoadBootDiagnosticsScheduled) return
        postFirstLoadBootDiagnosticsScheduled = true
        thread(name = "wasm-agent-post-first-load-boot-diagnostics") {
            Thread.sleep(900L)
            val wakeMode = wakeStartupMode()
            if (wakeMode.equals("off", ignoreCase = true)) {
                logDiagnostic("voice_wake_boot_reconciliation_skipped", JSONObject()
                    .put("reason", reason)
                    .put("wake", wakeMode)
                    .put("first_load_url_at", firstLoadUrlAt)
                    .put("status", "wake_disabled"))
                return@thread
            }
            val reconciliation = reconcileStaleVoiceWakeStatus("boot")
            logDiagnostic("voice_wake_boot_reconciliation", JSONObject()
                .put("reason", reason)
                .put("wake", wakeMode)
                .put("first_load_url_at", firstLoadUrlAt)
                .put("reconciliation", reconciliation))
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun createConfiguredWebView(origin: String): WebView {
        WebView.setWebContentsDebuggingEnabled(BuildConfig.ALLOW_LOCAL_DEV)
        val view = WebView(this)
        view.setBackgroundColor(BRAND_BG)
        view.alpha = 0f
        view.layoutParams = FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT,
        )
        view.isFocusable = true
        view.isFocusableInTouchMode = true
        view.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            loadsImagesAutomatically = true
            mediaPlaybackRequiresUserGesture = false
            javaScriptCanOpenWindowsAutomatically = false
            setSupportMultipleWindows(false)
            useWideViewPort = true
            loadWithOverviewMode = true
            builtInZoomControls = false
            displayZoomControls = false
            textZoom = 100
            cacheMode = WebSettings.LOAD_DEFAULT
            allowContentAccess = true
            allowFileAccess = false
            allowFileAccessFromFileURLs = false
            allowUniversalAccessFromFileURLs = false
            setGeolocationEnabled(true)
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            userAgentString = "$userAgentString WASMAgentAndroid/${BuildConfig.NATIVE_BUILD_ID} shell/android-webview"
        }
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(view, true)
        view.addJavascriptInterface(AndroidBridge(origin), "wasmAgentAndroid")
        view.addJavascriptInterface(AndroidNativeBridge(origin), NativeBridgeContract.GENERAL_BRIDGE_OBJECT)
        view.addJavascriptInterface(AndroidVoiceTuningBridge(origin), NativeBridgeContract.VOICE_TUNING_BRIDGE_OBJECT)
        view.addJavascriptInterface(AndroidDiagnosticsBridge(origin), "WasmAgentAndroidDiagnostics")
        logDiagnostic("voice_tuning_bridge_registered", JSONObject()
            .put("voice_tuning_bridge_registered", true)
            .put("bridge_object_name", NativeBridgeContract.VOICE_TUNING_BRIDGE_OBJECT)
            .put("general_bridge_object_name", NativeBridgeContract.GENERAL_BRIDGE_OBJECT)
            .put("methods", JSONArray(NativeBridgeContract.voiceTuningMethods)))
        view.webViewClient = createWebViewClient()
        view.webChromeClient = createWebChromeClient()
        view.setDownloadListener(createDownloadListener())
        return view
    }

    private fun createWebViewClient(): WebViewClient {
        return object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                logDiagnostic("webview_should_override_url_loading", JSONObject()
                    .put("url", request.url.toString())
                    .put("method", request.method)
                    .put("main_frame", request.isForMainFrame)
                    .put("redirect", request.isRedirect)
                    .put("has_gesture", request.hasGesture()))
                return handleUrlLoading(request.url, "navigation", request.isForMainFrame)
            }

            @Deprecated("Deprecated in Java")
            override fun shouldOverrideUrlLoading(view: WebView, url: String): Boolean {
                logDiagnostic("webview_should_override_url_loading_legacy", JSONObject()
                    .put("url", url)
                    .put("main_frame", true))
                return handleUrlLoading(Uri.parse(url), "legacy_navigation", true)
            }

            override fun onPageStarted(view: WebView, url: String, favicon: android.graphics.Bitmap?) {
                latestWebViewUrl = url
                webViewPageStartedAt = System.currentTimeMillis()
                webViewPageFinishedAt = 0
                webViewPageCommitVisibleAt = 0
                webViewMainFrameError = null
                logDiagnostic("webview_page_started", JSONObject().put("url", url))
                if (url.contains("/native/android/auth/return")) {
                    transitionOAuth("NATIVE_RETURN_PAGE_OBSERVED", "webview_page_started")
                }
            }

            override fun onPageCommitVisible(view: WebView, url: String) {
                latestWebViewUrl = url
                webViewPageCommitVisibleAt = System.currentTimeMillis()
                view.alpha = 1f
                hideSplash()
                prefs.edit().putString(PREF_LAST_URL, url).apply()
                logDiagnostic("webview_page_commit_visible", JSONObject().put("url", url))
            }

            override fun onPageFinished(view: WebView, url: String) {
                latestWebViewUrl = url
                webViewPageFinishedAt = System.currentTimeMillis()
                CookieManager.getInstance().flush()
                prefs.edit().putString(PREF_LAST_URL, url).apply()
                logDiagnostic("webview_page_finished", JSONObject()
                    .put("url", url)
                    .put("cookie_present", CookieManager.getInstance().getCookie(url).orEmpty().isNotBlank()))
                if (url.contains("/native/android/auth/return")) {
                    transitionOAuth("NATIVE_RETURN_PAGE_OBSERVED", "webview_page_finished")
                }
                emitRendererEvent("wasm-agent:native-page-finished", JSONObject().put("url", url))
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame) {
                    webViewMainFrameError = JSONObject()
                        .put("url", request.url.toString())
                        .put("error_code", error.errorCode)
                        .put("description", error.description.toString())
                    logDiagnostic("webview_main_frame_error", JSONObject()
                        .put("url", request.url.toString())
                        .put("error_code", error.errorCode)
                        .put("description", error.description.toString()))
                    showErrorScreen(
                        "WASM Agent did not load",
                        "The app could not reach the WASM Agent cloud surface. Retry when your connection is back.",
                    )
                }
            }

            override fun onReceivedHttpError(view: WebView, request: WebResourceRequest, errorResponse: WebResourceResponse) {
                if (request.isForMainFrame && errorResponse.statusCode >= 400) {
                    webViewMainFrameError = JSONObject()
                        .put("url", request.url.toString())
                        .put("status_code", errorResponse.statusCode)
                        .put("reason", errorResponse.reasonPhrase.orEmpty())
                    logDiagnostic("webview_main_frame_http_error", JSONObject()
                        .put("url", request.url.toString())
                        .put("status_code", errorResponse.statusCode)
                        .put("reason", errorResponse.reasonPhrase.orEmpty()))
                    showErrorScreen(
                        "WASM Agent returned an error",
                        "The cloud app answered with ${errorResponse.statusCode}. Retry in a moment.",
                    )
                }
            }

            override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, error: SslError) {
                handler.cancel()
                webViewMainFrameError = JSONObject()
                    .put("url", error.url.orEmpty())
                    .put("primary_error", error.primaryError)
                logDiagnostic("webview_ssl_error", JSONObject()
                    .put("url", error.url.orEmpty())
                    .put("primary_error", error.primaryError))
                showErrorScreen(
                    "Secure connection blocked",
                    "Android blocked the secure WASM Agent connection. Retry after the network issue is fixed.",
                )
            }

            override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
                logDiagnostic("webview_render_process_gone", JSONObject()
                    .put("did_crash", detail.didCrash())
                    .put("priority", detail.rendererPriorityAtExit()))
                showErrorScreen(
                    "WASM Agent needs a restart",
                    "The Android WebView process stopped. Tap retry to reopen the app surface.",
                )
                webView = null
                return true
            }
        }
    }

    private fun createWebChromeClient(): WebChromeClient {
        return object : WebChromeClient() {
            override fun onPermissionRequest(request: PermissionRequest) {
                runOnUiThread { handleWebPermissionRequest(request) }
            }

            override fun onPermissionRequestCanceled(request: PermissionRequest) {
                if (pendingWebPermissionRequest == request) pendingWebPermissionRequest = null
                logDiagnostic("webview_permission_request_canceled", JSONObject()
                    .put("origin", request.origin.toString())
                    .put("resources", JSONArray(request.resources.toList())))
            }

            override fun onShowFileChooser(
                webView: WebView,
                filePathCallback: ValueCallback<Array<Uri>>,
                fileChooserParams: WebChromeClient.FileChooserParams,
            ): Boolean {
                this@MainActivity.filePathCallback?.onReceiveValue(null)
                this@MainActivity.filePathCallback = filePathCallback
                logDiagnostic("file_picker_open_requested", JSONObject()
                    .put("accept_types", JSONArray(fileChooserParams.acceptTypes.toList()))
                    .put("mode", fileChooserParams.mode)
                    .put("capture_enabled", fileChooserParams.isCaptureEnabled))
                return try {
                    startActivityForResult(fileChooserParams.createIntent(), REQUEST_FILE_CHOOSER)
                    true
                } catch (error: ActivityNotFoundException) {
                    this@MainActivity.filePathCallback = null
                    filePathCallback.onReceiveValue(null)
                    logDiagnostic("file_picker_open_failed", JSONObject()
                        .put("error", error.javaClass.simpleName))
                    false
                }
            }

            override fun onGeolocationPermissionsShowPrompt(origin: String, callback: GeolocationPermissions.Callback) {
                if (permissionGranted(Manifest.permission.ACCESS_FINE_LOCATION) ||
                    permissionGranted(Manifest.permission.ACCESS_COARSE_LOCATION)) {
                    callback.invoke(origin, true, false)
                    logDiagnostic("geolocation_permission_granted", JSONObject().put("origin", origin))
                    return
                }
                pendingGeolocationOrigin = origin
                pendingGeolocationCallback = callback
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    requestPermissions(
                        arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION),
                        REQUEST_GEOLOCATION_PERMISSION,
                    )
                } else {
                    callback.invoke(origin, false, false)
                }
                logDiagnostic("geolocation_permission_requested", JSONObject().put("origin", origin))
            }

            override fun onConsoleMessage(consoleMessage: android.webkit.ConsoleMessage): Boolean {
                val level = consoleMessage.messageLevel().name.lowercase()
                if (bridgeDiagnosticsMode() != "off" && shouldForwardConsoleDiagnostic(level)) {
                    logDiagnostic("webview_console_message", JSONObject()
                        .put("level", level)
                        .put("message", consoleMessage.message().take(500))
                        .put("source", consoleMessage.sourceId().orEmpty())
                        .put("line", consoleMessage.lineNumber())
                        .put("console_messages_seen", webViewConsoleSeenCount)
                        .put("console_messages_forwarded", webViewConsoleForwardedCount)
                        .put("console_messages_dropped", webViewConsoleDroppedCount))
                } else {
                    webViewConsoleSeenCount += if (bridgeDiagnosticsMode() == "off") 1 else 0
                    webViewConsoleDroppedCount += if (bridgeDiagnosticsMode() == "off") 1 else 0
                }
                return super.onConsoleMessage(consoleMessage)
            }
        }
    }

    private fun createDownloadListener(): DownloadListener {
        return DownloadListener { url, userAgent, contentDisposition, mimeType, contentLength ->
            handleDownload(url, userAgent, contentDisposition, mimeType, contentLength)
        }
    }

    private fun handleUrlLoading(uri: Uri, reason: String, isMainFrame: Boolean): Boolean {
        val scheme = uri.scheme.orEmpty().lowercase()
        if (scheme == "http" || scheme == "https") {
            if (isInternalUrl(uri)) {
                logDiagnostic("internal_url_allowed", JSONObject()
                    .put("url", uri.toString())
                    .put("reason", reason)
                    .put("main_frame", isMainFrame))
                return false
            }
            openExternalUrl(uri, "external_${reason}")
            return true
        }
        if (scheme == "about" || scheme == "data" || scheme == "blob") return false
        openExternalUrl(uri, "external_scheme_${reason}")
        return true
    }

    private fun isInternalUrl(uri: Uri): Boolean {
        val host = uri.host.orEmpty().lowercase()
        val selectedHost = Uri.parse(selectedOrigin.ifBlank { BuildConfig.DEFAULT_SERVER_URL }).host.orEmpty().lowercase()
        return host.isNotBlank() && host == selectedHost
    }

    private fun openExternalUrl(uri: Uri, reason: String) {
        logDiagnostic("external_url_open_requested", JSONObject()
            .put("url", uri.toString())
            .put("reason", reason))
        emitRendererEvent("wasm-agent:native-external-url", JSONObject()
            .put("url", uri.toString())
            .put("reason", reason))
        try {
            val intent = Intent(Intent.ACTION_VIEW, uri)
            intent.addCategory(Intent.CATEGORY_BROWSABLE)
            logDiagnostic("intent_launch_requested", JSONObject()
                .put("url", uri.toString())
                .put("action", intent.action.orEmpty())
                .put("reason", reason))
            startActivity(intent)
            logDiagnostic("intent_launch_succeeded", JSONObject()
                .put("url", uri.toString())
                .put("reason", reason))
        } catch (error: Exception) {
            rememberException("external_url_open_failed", error)
            logDiagnostic("external_url_open_failed", JSONObject()
                .put("url", uri.toString())
                .put("reason", reason)
                .put("error", error.javaClass.simpleName))
            Toast.makeText(this, "No app can open this link.", Toast.LENGTH_SHORT).show()
        }
    }

    private fun handleDownload(
        url: String,
        userAgent: String,
        contentDisposition: String,
        mimeType: String,
        contentLength: Long,
    ) {
        logDiagnostic("download_requested", JSONObject()
            .put("url", url)
            .put("mime_type", mimeType)
            .put("content_length", contentLength))
        val uri = Uri.parse(url)
        if (!listOf("http", "https").contains(uri.scheme.orEmpty().lowercase())) {
            openExternalUrl(uri, "download_non_http")
            return
        }
        try {
            val filename = URLUtil.guessFileName(url, contentDisposition, mimeType)
            val request = DownloadManager.Request(uri)
                .setTitle(filename)
                .setMimeType(mimeType)
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, filename)
            if (userAgent.isNotBlank()) request.addRequestHeader("User-Agent", userAgent)
            val cookies = CookieManager.getInstance().getCookie(url).orEmpty()
            if (cookies.isNotBlank()) request.addRequestHeader("Cookie", cookies)
            val manager = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
            val id = manager.enqueue(request)
            logDiagnostic("download_enqueued", JSONObject()
                .put("id", id)
                .put("filename", filename))
            Toast.makeText(this, "Downloading $filename", Toast.LENGTH_SHORT).show()
        } catch (error: Exception) {
            logDiagnostic("download_enqueue_failed", JSONObject()
                .put("url", url)
                .put("error", error.javaClass.simpleName))
            openExternalUrl(uri, "download_manager_failed")
        }
    }

    private fun handleWebPermissionRequest(request: PermissionRequest) {
        val grantableResources = request.resources.filter { resource ->
            resource == PermissionRequest.RESOURCE_AUDIO_CAPTURE ||
                resource == PermissionRequest.RESOURCE_VIDEO_CAPTURE ||
                resource == PermissionRequest.RESOURCE_PROTECTED_MEDIA_ID
        }.toTypedArray()
        if (grantableResources.isEmpty()) {
            request.deny()
            logDiagnostic("webview_permission_denied_unsupported", JSONObject()
                .put("origin", request.origin.toString())
                .put("resources", JSONArray(request.resources.toList())))
            return
        }
        val neededPermissions = request.resources.mapNotNull { resource ->
            when (resource) {
                PermissionRequest.RESOURCE_AUDIO_CAPTURE -> Manifest.permission.RECORD_AUDIO
                PermissionRequest.RESOURCE_VIDEO_CAPTURE -> Manifest.permission.CAMERA
                else -> null
            }
        }.distinct().filter { permission -> !permissionGranted(permission) }
        if (neededPermissions.isEmpty()) {
            request.grant(grantableResources)
            logDiagnostic("webview_permission_granted", JSONObject()
                .put("origin", request.origin.toString())
                .put("resources", JSONArray(grantableResources.toList())))
            emitRendererEvent("wasm-agent:native-permission", JSONObject()
                .put("granted", true)
                .put("resources", JSONArray(grantableResources.toList())))
            return
        }
        pendingWebPermissionRequest = request
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            requestPermissions(neededPermissions.toTypedArray(), REQUEST_WEB_PERMISSIONS)
        } else {
            request.deny()
            pendingWebPermissionRequest = null
        }
        logDiagnostic("webview_permission_requested", JSONObject()
            .put("origin", request.origin.toString())
            .put("permissions", JSONArray(neededPermissions)))
    }

    private fun finishPendingWebPermissionRequest(permissions: Array<out String>, grantResults: IntArray) {
        val request = pendingWebPermissionRequest ?: return
        pendingWebPermissionRequest = null
        val grantedPermissions = permissions.zip(grantResults.toTypedArray())
            .filter { (_, result) -> result == PackageManager.PERMISSION_GRANTED }
            .map { (permission, _) -> permission }
            .toSet()
        val resources = request.resources.filter { resource ->
            when (resource) {
                PermissionRequest.RESOURCE_AUDIO_CAPTURE -> Manifest.permission.RECORD_AUDIO in grantedPermissions || permissionGranted(Manifest.permission.RECORD_AUDIO)
                PermissionRequest.RESOURCE_VIDEO_CAPTURE -> Manifest.permission.CAMERA in grantedPermissions || permissionGranted(Manifest.permission.CAMERA)
                PermissionRequest.RESOURCE_PROTECTED_MEDIA_ID -> true
                else -> false
            }
        }.toTypedArray()
        if (resources.isNotEmpty()) {
            request.grant(resources)
            logDiagnostic("webview_permission_result_granted", JSONObject()
                .put("resources", JSONArray(resources.toList())))
            emitRendererEvent("wasm-agent:native-permission", JSONObject()
                .put("granted", true)
                .put("resources", JSONArray(resources.toList())))
        } else {
            request.deny()
            logDiagnostic("webview_permission_result_denied")
            emitRendererEvent("wasm-agent:native-permission", JSONObject().put("granted", false))
        }
    }

    private fun finishPendingGeolocationRequest(permissions: Array<out String>, grantResults: IntArray) {
        val callback = pendingGeolocationCallback ?: return
        val origin = pendingGeolocationOrigin
        pendingGeolocationCallback = null
        pendingGeolocationOrigin = ""
        val granted = grantResults.any { result -> result == PackageManager.PERMISSION_GRANTED } ||
            permissionGranted(Manifest.permission.ACCESS_FINE_LOCATION) ||
            permissionGranted(Manifest.permission.ACCESS_COARSE_LOCATION)
        callback.invoke(origin, granted, false)
        logDiagnostic("geolocation_permission_result", JSONObject()
            .put("origin", origin)
            .put("granted", granted))
    }

    private fun finishVoiceWakePermissionRequest(permissions: Array<out String>, grantResults: IntArray) {
        val granted = permissionGranted(Manifest.permission.RECORD_AUDIO)
        logDiagnostic("voice_wake_permission_result", JSONObject().put("granted", granted))
        emitRendererEvent("wasm-agent:native-voice-wake-status", voiceWakeStatus().put("permission_record_audio", granted))
        if (granted && prefs.getBoolean(HermesVoiceWakeService.PREF_ENABLED, false)) {
            HermesVoiceWakeService.start(this, selectedOrigin.ifBlank { BuildConfig.DEFAULT_SERVER_URL })
        }
    }

    private fun permissionGranted(permission: String): Boolean {
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.M ||
            checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
    }

    private fun startGoogleLogin(origin: String) {
        rotateNativeCorrelationId()
        transitionOAuth("AUTH_START_TAPPED", "native_start_google_login")
        val attemptSessionId = rotateAndroidAuthSessionId()
        transitionOAuth("AUTH_SESSION_CREATED", "native_session_rotated")
        val session = URLEncoder.encode(attemptSessionId, "UTF-8")
        val correlation = URLEncoder.encode(nativeCorrelationId, "UTF-8")
        val buildId = URLEncoder.encode(BuildConfig.NATIVE_BUILD_ID, "UTF-8")
        val deviceHash = URLEncoder.encode(installDeviceHash, "UTF-8")
        val loginUrl = origin.trimEnd('/') + "/native/android/auth/start?session=$session&native_correlation_id=$correlation&build_id=$buildId&device_hash=$deviceHash"
        waitingForAndroidAuth = true
        logDiagnostic("android_google_login_start_requested", JSONObject()
            .put("login_url", loginUrl)
            .put("session", attemptSessionId)
            .put("native_correlation_id", nativeCorrelationId))
        postNativeAndroidAuthEvent(origin, "android_oauth_start_activity_requested", "/native/android/auth/start", 0, "")
        thread(name = "wasm-agent-android-auth-start") {
            try {
                val googleLoginUrl = resolveNativeAndroidAuthStartUrl(loginUrl)
                runOnUiThread {
                    try {
                        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(googleLoginUrl))
                        intent.addCategory(Intent.CATEGORY_BROWSABLE)
                        logDiagnostic("intent_launch_requested", JSONObject()
                            .put("url", googleLoginUrl)
                            .put("action", intent.action.orEmpty())
                            .put("reason", "android_google_login"))
                        startActivity(intent)
                        transitionOAuth("EXTERNAL_BROWSER_OPENED", "google_oauth_intent_started", JSONObject()
                            .put("oauth_host", Uri.parse(googleLoginUrl).host.orEmpty()))
                        postNativeAndroidAuthEvent(origin, "android_oauth_start_activity_succeeded", "/native/android/auth/start", 0, "")
                        logDiagnostic("android_google_login_start_succeeded", JSONObject()
                            .put("login_url", loginUrl)
                            .put("oauth_host", Uri.parse(googleLoginUrl).host.orEmpty()))
                        pollAndroidAuth(origin, "start_activity")
                    } catch (error: Exception) {
                        failAndroidGoogleLoginStart(origin, error)
                    }
                }
            } catch (error: Exception) {
                runOnUiThread {
                    failAndroidGoogleLoginStart(origin, error)
                }
            }
        }
    }

    private fun resolveNativeAndroidAuthStartUrl(loginUrl: String): String {
        val connection = (URL(loginUrl).openConnection() as HttpURLConnection).apply {
            instanceFollowRedirects = false
            connectTimeout = 5000
            readTimeout = 5000
            requestMethod = "GET"
        }
        try {
            val statusCode = connection.responseCode
            val location = connection.getHeaderField("Location").orEmpty()
            if (statusCode !in 300..399 || location.isBlank()) {
                throw IllegalStateException("auth_begin_missing_google_redirect_$statusCode")
            }
            val resolved = URL(URL(loginUrl), location).toString()
            val host = Uri.parse(resolved).host.orEmpty().lowercase()
            if (host != "accounts.google.com") {
                throw IllegalStateException("auth_begin_unexpected_redirect_host_$host")
            }
            logDiagnostic("android_google_login_redirect_resolved", JSONObject()
                .put("status_code", statusCode)
                .put("oauth_url", resolved)
                .put("oauth_host", host))
            return resolved
        } finally {
            connection.disconnect()
        }
    }

    private fun failAndroidGoogleLoginStart(origin: String, error: Exception) {
        waitingForAndroidAuth = false
        rememberException("android_google_login_start_failed", error)
        transitionOAuth("AUTH_ERROR", error.javaClass.simpleName)
        postNativeAndroidAuthEvent(origin, "android_oauth_start_activity_failed", "/native/android/auth/start", 0, error.javaClass.simpleName)
        logDiagnostic("android_google_login_start_failed", JSONObject()
            .put("error", error.javaClass.simpleName)
            .put("message", error.message.orEmpty()))
        emitRendererEvent("wasm-agent:native-android-auth-canceled", JSONObject()
            .put("reason", "start_google_login_failed")
            .put("session", androidAuthSessionId))
        Toast.makeText(this, "Could not open Google sign-in.", Toast.LENGTH_SHORT).show()
    }

    private fun bringNativeTaskToFront(reason: String) {
        try {
            val intent = Intent(this, MainActivity::class.java)
            intent.addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            startActivity(intent)
            logDiagnostic("native_task_foreground_requested", JSONObject().put("reason", reason))
        } catch (error: Exception) {
            logDiagnostic("native_task_foreground_failed", JSONObject()
                .put("reason", reason)
                .put("error", error.javaClass.simpleName))
        }
    }

    private fun pollAndroidAuth(origin: String, reason: String) {
        val token = androidAuthPollToken + 1
        androidAuthPollToken = token
        transitionOAuth("AUTH_POLLING", reason)
        logDiagnostic("android_auth_poll_started", JSONObject()
            .put("reason", reason)
            .put("session", androidAuthSessionId))
        postNativeAndroidAuthEvent(origin, "android_auth_poll_started", "/native/android/auth/poll", 0, reason)
        thread(name = "wasm-agent-android-auth-poll") {
            val session = URLEncoder.encode(androidAuthSessionId, "UTF-8")
            repeat(90) {
                if (androidAuthPollToken != token) return@thread
                try {
                    val url = URL(origin.trimEnd('/') + "/native/android/auth/poll?session=$session")
                    val connection = url.openConnection() as HttpURLConnection
                    connection.connectTimeout = 3000
                    connection.readTimeout = 3000
                    connection.requestMethod = "GET"
                    val statusCode = connection.responseCode
                    val body = if (statusCode in 200..299) {
                        connection.inputStream.bufferedReader().use { reader -> reader.readText() }
                    } else {
                        connection.errorStream?.bufferedReader()?.use { reader -> reader.readText() } ?: ""
                    }
                    if (it == 0 || it % 5 == 0 || statusCode !in 200..299) {
                        postNativeAndroidAuthEvent(origin, "android_auth_poll_response", "/native/android/auth/poll", statusCode, "")
                        logDiagnostic("android_auth_poll_response", JSONObject()
                            .put("status_code", statusCode)
                            .put("attempt", it + 1))
                    }
                    if (statusCode in 200..299) {
                        val payload = JSONObject(body)
                        val authCode = payload.optString("auth_code", "")
                        if (authCode.isNotBlank()) {
                            val nativeReturnReceived = lastAndroidReturnSessionId == androidAuthSessionId && lastAndroidReturnIntentAt > 0
                            if (!nativeReturnReceived) {
                                if (it == 0 || it % 5 == 0) {
                                    transitionOAuth("NATIVE_RETURN_INTENT_MISSING", "auth_code_waiting_for_native_return")
                                    postNativeAndroidAuthEvent(origin, "native_return_intent_missing", "/native/android/auth/poll", statusCode, "")
                                    logDiagnostic("native_return_intent_missing", JSONObject()
                                        .put("status_code", statusCode)
                                        .put("attempt", it + 1)
                                        .put("session", androidAuthSessionId)
                                        .put("last_return_session", lastAndroidReturnSessionId))
                                }
                            } else {
                                waitingForAndroidAuth = false
                                transitionOAuth("GOOGLE_CALLBACK_OBSERVED", "poll_auth_code_received_after_native_return")
                                postNativeAndroidAuthEvent(origin, "android_auth_poll_auth_code_received", "/native/android/auth/poll", statusCode, "")
                                logDiagnostic("android_auth_poll_auth_code_received", JSONObject()
                                    .put("status_code", statusCode)
                                    .put("native_return_intent_received", true)
                                    .put("return_intent_at", lastAndroidReturnIntentAt))
                                runOnUiThread {
                                    bringNativeTaskToFront("android_auth_code_received")
                                    transitionOAuth("WEBVIEW_RELOADED", "auth_code_received_after_native_return")
                                    logDiagnostic("webview_reload_after_auth_return", JSONObject()
                                        .put("origin", origin)
                                        .put("reason", "auth_code_received_after_native_return"))
                                    webView?.loadUrl(pwaHomeUrl(origin, authCode))
                                }
                                return@thread
                            }
                        }
                        if (authCode.isBlank() && (!payload.optBoolean("pending", true) || payload.optBoolean("expired", false) || payload.has("error"))) {
                            waitingForAndroidAuth = false
                            val failureReason = payload.optString(
                                "error",
                                if (payload.optBoolean("expired", false)) "expired" else "auth_not_completed",
                            )
                            transitionOAuth(if (payload.optBoolean("expired", false)) "AUTH_EXPIRED" else "AUTH_CANCELED", failureReason)
                            postNativeAndroidAuthEvent(origin, "android_auth_poll_finished_without_code", "/native/android/auth/poll", statusCode, failureReason)
                            logDiagnostic("android_auth_poll_finished_without_code", JSONObject()
                                .put("status_code", statusCode)
                                .put("reason", failureReason))
                            runOnUiThread {
                                emitRendererEvent("wasm-agent:native-android-auth-canceled", JSONObject()
                                    .put("reason", failureReason)
                                    .put("session", androidAuthSessionId))
                            }
                            return@thread
                        }
                    }
                } catch (error: Exception) {
                    if (it == 0 || it % 5 == 0) {
                        rememberException("android_auth_poll_error", error)
                        postNativeAndroidAuthEvent(origin, "android_auth_poll_error", "/native/android/auth/poll", 0, error.javaClass.simpleName)
                        logDiagnostic("android_auth_poll_error", JSONObject()
                            .put("attempt", it + 1)
                            .put("error", error.javaClass.simpleName))
                    }
                    // Poll again while the user finishes Google sign-in in the browser.
                }
                Thread.sleep(2000)
            }
            waitingForAndroidAuth = false
            val timeoutReason = if (lastAndroidReturnSessionId == androidAuthSessionId) "poll_timeout" else "native_return_intent_missing"
            transitionOAuth("AUTH_EXPIRED", timeoutReason)
            postNativeAndroidAuthEvent(origin, "android_auth_poll_timeout", "/native/android/auth/poll", 0, timeoutReason)
            logDiagnostic("android_auth_poll_timeout", JSONObject()
                .put("session", androidAuthSessionId)
                .put("reason", timeoutReason)
                .put("native_return_intent_received", lastAndroidReturnSessionId == androidAuthSessionId))
        }
    }

    private fun postNativeAndroidAuthEvent(origin: String, kind: String, path: String, statusCode: Int, failureReason: String) {
        thread(name = "wasm-agent-android-auth-event") {
            try {
                val url = URL(origin.trimEnd('/') + "/native/events")
                val connection = url.openConnection() as HttpURLConnection
                connection.connectTimeout = 2500
                connection.readTimeout = 2500
                connection.requestMethod = "POST"
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                connection.doOutput = true
                val payload = JSONObject()
                    .put("kind", kind)
                    .put("device_id", "android-${BuildConfig.NATIVE_BUILD_ID}")
                    .put("platform", "android")
                    .put("session", androidAuthSessionId)
                    .put("android_auth_session", androidAuthSessionId)
                    .put("native_correlation_id", nativeCorrelationId)
                    .put("build_id", BuildConfig.NATIVE_BUILD_ID)
                    .put("install_device_hash", installDeviceHash)
                    .put("timestamp", System.currentTimeMillis())
                    .put("path", path)
                    .put("status_code", statusCode)
                    .put("failure_reason", failureReason)
                connection.outputStream.use { stream ->
                    stream.write(payload.toString().toByteArray(Charsets.UTF_8))
                }
                connection.inputStream.close()
            } catch (_: Exception) {
                // Auth telemetry must never block sign-in.
            }
        }
    }

    private fun uploadHermesWakeDataset(dataset: File): JSONObject {
        if (!dataset.isFile || dataset.length() <= 0L) {
            return JSONObject().put("ok", false).put("error", "dataset_export_missing")
        }
        val maxBytes = 256L * 1024L * 1024L
        if (dataset.length() > maxBytes) {
            return JSONObject()
                .put("ok", false)
                .put("error", "dataset_export_too_large")
                .put("bytes", dataset.length())
                .put("max_bytes", maxBytes)
        }
        val origin = selectedOrigin.ifBlank { BuildConfig.DEFAULT_SERVER_URL }.trimEnd('/')
        return try {
            val bytes = dataset.readBytes()
            val sha256 = sha256Bytes(bytes)
            val connection = (URL("$origin/native/android/hermes-wake-dataset").openConnection() as HttpURLConnection).apply {
                connectTimeout = 15000
                readTimeout = 60000
                requestMethod = "POST"
                setRequestProperty("Content-Type", "application/zip")
                setRequestProperty("X-Wasm-Agent-Dataset-Source", "android-native-export")
                setRequestProperty("X-Wasm-Agent-Native-Device-Id", "android-${BuildConfig.NATIVE_BUILD_ID}-${installDeviceHash}")
                setRequestProperty("X-Wasm-Agent-Dataset-Sha256", sha256)
                doOutput = true
            }
            connection.outputStream.use { stream -> stream.write(bytes) }
            val responseText = runCatching {
                (if (connection.responseCode in 200..299) connection.inputStream else connection.errorStream)
                    ?.bufferedReader()
                    ?.use { it.readText() }
            }.getOrNull().orEmpty()
            val response = runCatching { JSONObject(responseText) }.getOrElse { JSONObject().put("raw", responseText.take(2000)) }
            JSONObject()
                .put("ok", connection.responseCode in 200..299)
                .put("status_code", connection.responseCode)
                .put("origin", origin)
                .put("sha256", sha256)
                .put("response", response)
        } catch (error: Exception) {
            JSONObject()
                .put("ok", false)
                .put("error", error.javaClass.simpleName)
                .put("message", error.message ?: "")
        }
    }

    private fun triggerHermesDatasetExport(reason: String) {
        thread(name = "hermes-dataset-export-$reason") {
            try {
                Thread.sleep(1200)
                val event = voiceTuningStore.exportDataset(File(filesDir, "voice/exports"))
                val upload = uploadHermesWakeDataset(File(event.optString("path")))
                event.put("upload", upload)
                    .put("trigger", reason)
                    .put("status", voiceTuningStatus())
                logDiagnostic("voice_tuning_dataset_exported", event)
                emitRendererEvent("wasm-agent:native-voice-tuning", event)
            } catch (error: Exception) {
                logDiagnostic("voice_tuning_dataset_export_failed", JSONObject()
                    .put("ok", false)
                    .put("trigger", reason)
                    .put("error", error.message ?: error.javaClass.simpleName))
            }
        }
    }

    private fun installHermesWakeModel(modelUrl: String, expectedSha256: String = ""): JSONObject {
        val origin = selectedOrigin.ifBlank { BuildConfig.DEFAULT_SERVER_URL }.trimEnd('/')
        val resolved = try {
            URL(URL("$origin/"), modelUrl)
        } catch (error: Exception) {
            return JSONObject().put("ok", false).put("error", "invalid_model_url").put("message", error.message ?: "")
        }
        val expectedHost = Uri.parse(origin).host.orEmpty().lowercase()
        val allowedProtocol = resolved.protocol == "https" || (BuildConfig.ALLOW_LOCAL_DEV && resolved.protocol == "http")
        if (!allowedProtocol || resolved.host.lowercase() != expectedHost) {
            return JSONObject()
                .put("ok", false)
                .put("error", "model_url_not_allowed")
                .put("message", "Hermes wake models must be downloaded from the selected wasm-agent backend.")
        }
        val targetDir = File(filesDir, "voice")
        val target = File(targetDir, "hermes.onnx")
        val temp = File(targetDir, "hermes.onnx.tmp")
        return try {
            targetDir.mkdirs()
            val connection = (resolved.openConnection() as HttpURLConnection).apply {
                connectTimeout = 15000
                readTimeout = 120000
                requestMethod = "GET"
            }
            if (connection.responseCode !in 200..299) {
                return JSONObject()
                    .put("ok", false)
                    .put("error", "model_download_failed")
                    .put("status_code", connection.responseCode)
            }
            val maxBytes = 32L * 1024L * 1024L
            var total = 0L
            MessageDigest.getInstance("SHA-256").let { digest ->
                connection.inputStream.use { input ->
                    FileOutputStream(temp).use { output ->
                        val buffer = ByteArray(64 * 1024)
                        while (true) {
                            val read = input.read(buffer)
                            if (read < 0) break
                            total += read
                            if (total > maxBytes) throw IllegalStateException("model_too_large")
                            digest.update(buffer, 0, read)
                            output.write(buffer, 0, read)
                        }
                    }
                }
                val actualSha256 = digest.digest().joinToString("") { "%02x".format(it) }
                if (expectedSha256.isNotBlank() && !actualSha256.equals(expectedSha256, ignoreCase = true)) {
                    temp.delete()
                    return JSONObject()
                        .put("ok", false)
                        .put("error", "model_sha256_mismatch")
                        .put("expected_sha256", expectedSha256)
                        .put("actual_sha256", actualSha256)
                }
                if (!temp.renameTo(target)) {
                    temp.copyTo(target, overwrite = true)
                    temp.delete()
                }
                logDiagnostic("hermes_wake_model_installed", JSONObject()
                    .put("bytes", total)
                    .put("sha256", actualSha256)
                    .put("path", "files/voice/hermes.onnx"))
                JSONObject()
                    .put("ok", true)
                    .put("type", "hermes_wake_model_installed")
                    .put("path", "files/voice/hermes.onnx")
                    .put("bytes", total)
                    .put("sha256", actualSha256)
                    .put("status", voiceWakeStatus())
            }
        } catch (error: Exception) {
            temp.delete()
            JSONObject()
                .put("ok", false)
                .put("error", error.message ?: error.javaClass.simpleName)
                .put("message", error.javaClass.simpleName)
        }
    }

    private fun installOpenWakeWordBundle(bundleUrl: String, expectedSha256: String = ""): JSONObject {
        val origin = selectedOrigin.ifBlank { BuildConfig.DEFAULT_SERVER_URL }.trimEnd('/')
        val resolved = try {
            URL(URL("$origin/"), bundleUrl)
        } catch (error: Exception) {
            return JSONObject().put("ok", false).put("error", "invalid_bundle_url").put("message", error.message ?: "")
        }
        val expectedHost = Uri.parse(origin).host.orEmpty().lowercase()
        val allowedProtocol = resolved.protocol == "https" || (BuildConfig.ALLOW_LOCAL_DEV && resolved.protocol == "http")
        if (!allowedProtocol || resolved.host.lowercase() != expectedHost) {
            return JSONObject()
                .put("ok", false)
                .put("error", "bundle_url_not_allowed")
                .put("message", "OpenWakeWord bundles must be downloaded from the selected wasm-agent backend.")
        }
        val voiceDir = File(filesDir, "voice")
        val tempZip = File(voiceDir, "openwakeword.zip.tmp")
        val targetDir = File(voiceDir, "openwakeword")
        val tempDir = File(voiceDir, "openwakeword.tmp")
        return try {
            voiceDir.mkdirs()
            val connection = (resolved.openConnection() as HttpURLConnection).apply {
                connectTimeout = 15000
                readTimeout = 120000
                requestMethod = "GET"
            }
            if (connection.responseCode !in 200..299) {
                return JSONObject()
                    .put("ok", false)
                    .put("error", "bundle_download_failed")
                    .put("status_code", connection.responseCode)
            }
            val maxBytes = 96L * 1024L * 1024L
            var total = 0L
            val digest = MessageDigest.getInstance("SHA-256")
            connection.inputStream.use { input ->
                FileOutputStream(tempZip).use { output ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        total += read
                        if (total > maxBytes) throw IllegalStateException("bundle_too_large")
                        digest.update(buffer, 0, read)
                        output.write(buffer, 0, read)
                    }
                }
            }
            val actualSha256 = digest.digest().joinToString("") { "%02x".format(it) }
            if (expectedSha256.isNotBlank() && !actualSha256.equals(expectedSha256, ignoreCase = true)) {
                tempZip.delete()
                return JSONObject()
                    .put("ok", false)
                    .put("error", "bundle_sha256_mismatch")
                    .put("expected_sha256", expectedSha256)
                    .put("actual_sha256", actualSha256)
            }
            tempDir.deleteRecursively()
            tempDir.mkdirs()
            val required = setOf(
                OpenWakeWordBundleEngine.MEL_MODEL_NAME,
                OpenWakeWordBundleEngine.EMBEDDING_MODEL_NAME,
                OpenWakeWordBundleEngine.CLASSIFIER_MODEL_NAME,
            )
            val extracted = mutableSetOf<String>()
            ZipInputStream(tempZip.inputStream()).use { zip ->
                while (true) {
                    val entry = zip.nextEntry ?: break
                    val name = entry.name.substringAfterLast('/').trim()
                    if (!entry.isDirectory && name in required) {
                        val outFile = File(tempDir, name)
                        FileOutputStream(outFile).use { output ->
                            val buffer = ByteArray(64 * 1024)
                            while (true) {
                                val read = zip.read(buffer)
                                if (read < 0) break
                                output.write(buffer, 0, read)
                            }
                        }
                        extracted.add(name)
                    }
                    zip.closeEntry()
                }
            }
            if (!extracted.containsAll(required)) {
                tempDir.deleteRecursively()
                tempZip.delete()
                return JSONObject()
                    .put("ok", false)
                    .put("error", "bundle_missing_required_models")
                    .put("required", JSONArray(required))
                    .put("extracted", JSONArray(extracted))
            }
            targetDir.deleteRecursively()
            if (!tempDir.renameTo(targetDir)) {
                tempDir.copyRecursively(targetDir, overwrite = true)
                tempDir.deleteRecursively()
            }
            tempZip.delete()
            logDiagnostic("openwakeword_bundle_installed", JSONObject()
                .put("bytes", total)
                .put("sha256", actualSha256)
                .put("path", OpenWakeWordBundleEngine.BUNDLE_DIR)
                .put("files", JSONArray(extracted)))
            JSONObject()
                .put("ok", true)
                .put("type", "openwakeword_bundle_installed")
                .put("path", OpenWakeWordBundleEngine.BUNDLE_DIR)
                .put("bytes", total)
                .put("sha256", actualSha256)
                .put("status", voiceWakeStatus())
        } catch (error: Exception) {
            tempZip.delete()
            tempDir.deleteRecursively()
            JSONObject()
                .put("ok", false)
                .put("error", error.message ?: error.javaClass.simpleName)
                .put("message", error.javaClass.simpleName)
        }
    }

    private fun playWakePhraseProbe(
        phrase: String,
        languageTag: String = "en-US",
        rate: Float = 0.9f,
        pitch: Float = 1.0f,
        timeoutMs: Long = 7000L,
    ): JSONObject {
        val text = phrase.trim().ifBlank { HermesVoiceWakeService.configuredWakePhrase(this) }.ifBlank { HermesVoiceWakeService.DEFAULT_WAKE_PHRASE }.take(80)
        val boundedTimeout = timeoutMs.coerceIn(1000L, 15000L)
        val latch = CountDownLatch(1)
        val utteranceId = "wake-phrase-probe-${UUID.randomUUID()}"
        var tts: TextToSpeech? = null
        var done = false
        var error = ""
        runOnUiThread {
            tts = TextToSpeech(this) { status ->
                if (status != TextToSpeech.SUCCESS) {
                    error = "tts_init_failed:$status"
                    latch.countDown()
                    return@TextToSpeech
                }
                val active = tts
                if (active == null) {
                    error = "tts_unavailable"
                    latch.countDown()
                    return@TextToSpeech
                }
                val languageResult = active.setLanguage(Locale.forLanguageTag(languageTag.ifBlank { "en-US" }))
                if (languageResult == TextToSpeech.LANG_MISSING_DATA || languageResult == TextToSpeech.LANG_NOT_SUPPORTED) {
                    error = "tts_language_unavailable:$languageTag"
                    latch.countDown()
                    return@TextToSpeech
                }
                active.setSpeechRate(rate.coerceIn(0.5f, 1.5f))
                active.setPitch(pitch.coerceIn(0.5f, 1.5f))
                active.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                    override fun onStart(id: String?) {}
                    override fun onDone(id: String?) {
                        if (id == utteranceId) {
                            done = true
                            latch.countDown()
                        }
                    }
                    @Deprecated("Deprecated in Java")
                    override fun onError(id: String?) {
                        if (id == utteranceId) {
                            error = "tts_error"
                            latch.countDown()
                        }
                    }
                    override fun onError(id: String?, errorCode: Int) {
                        if (id == utteranceId) {
                            error = "tts_error:$errorCode"
                            latch.countDown()
                        }
                    }
                })
                val result = active.speak(text, TextToSpeech.QUEUE_FLUSH, Bundle(), utteranceId)
                if (result != TextToSpeech.SUCCESS) {
                    error = "tts_speak_failed:$result"
                    latch.countDown()
                }
            }
        }
        val completed = latch.await(boundedTimeout, TimeUnit.MILLISECONDS)
        runOnUiThread {
            try {
                tts?.stop()
                tts?.shutdown()
            } catch (_: Exception) {
            }
        }
        val timedOut = !completed
        if (timedOut && error.isBlank()) error = "tts_timeout"
        val result = JSONObject()
            .put("ok", done && error.isBlank())
            .put("type", "wake_phrase_probe_playback")
            .put("phrase", text)
            .put("language", languageTag.ifBlank { "en-US" })
            .put("completed", completed)
            .put("spoken", done)
            .put("timeoutMs", boundedTimeout)
            .put("status", voiceWakeStatus())
        if (error.isNotBlank()) result.put("error", error)
        logDiagnostic("wake_phrase_probe_playback", result)
        return result
    }

    private fun scoreWakePhraseProbe(
        durationMs: Long = 3500L,
        restartListener: Boolean = true,
        stopListenerFirst: Boolean = true,
        includePcmBase64: Boolean = false,
    ): JSONObject {
        if (!permissionGranted(Manifest.permission.RECORD_AUDIO)) {
            return JSONObject()
                .put("ok", false)
                .put("type", "wake_phrase_score_probe")
                .put("error", "record_audio_permission_denied")
                .put("status", voiceWakeStatus())
        }
        val origin = selectedOrigin.ifBlank {
            prefs.getString(HermesVoiceWakeService.PREF_ORIGIN, "").orEmpty()
        }.ifBlank { BuildConfig.DEFAULT_SERVER_URL }
        val boundedDuration = durationMs.coerceIn(1000L, 8000L)
        val sampleRate = OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ
        val rawMinBuffer = AudioRecord.getMinBufferSize(
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        if (rawMinBuffer <= 0) {
            return JSONObject()
                .put("ok", false)
                .put("type", "wake_phrase_score_probe")
                .put("error", "audio_record_min_buffer_failed:$rawMinBuffer")
                .put("status", voiceWakeStatus())
        }
        if (stopListenerFirst) {
            HermesVoiceWakeService.stop(this)
            Thread.sleep(350L)
        }
        val selection = WakeModelSelector.select(
            personalizedModelFile = File(filesDir, OpenWakeWordOnnxEngine.APP_PRIVATE_PERSONALIZED_MODEL_PATH.removePrefix("files/")),
            baseModelFile = File(filesDir, OpenWakeWordOnnxEngine.APP_PRIVATE_BASE_MODEL_PATH.removePrefix("files/")),
            threshold = HermesVoiceWakeService.configuredWakeThreshold(this),
        )
        val engine = selection.engine
        val frames = JSONArray()
        var recorder: AudioRecord? = null
        var maxConfidence = 0.0
        var lastConfidence = 0.0
        var detectedFrames = 0
        var inferenceFrames = 0
        var readCalls = 0
        var readErrors = 0
        var samplesRead = 0L
        var peak = 0
        var energy = 0.0
        var energySamples = 0L
        var error = ""
        val captured = if (includePcmBase64) ArrayList<Short>() else null
        val startedAt = System.currentTimeMillis()
        try {
            val bufferSize = rawMinBuffer.coerceAtLeast(sampleRate)
            recorder = AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION,
                sampleRate,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufferSize,
            )
            if (recorder.state != AudioRecord.STATE_INITIALIZED) {
                error = "audio_record_state:${recorder.state}"
            } else if (!engine.ready) {
                error = "wake_engine_not_ready:${engine.diagnosticReason}"
            } else {
                recorder.startRecording()
                if (recorder.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
                    error = "audio_record_not_recording"
                } else {
                    val frame = ShortArray(1024)
                    val deadline = startedAt + boundedDuration
                    while (System.currentTimeMillis() < deadline) {
                        val count = recorder.read(frame, 0, frame.size)
                        if (count <= 0) {
                            readErrors += 1
                            continue
                        }
                        readCalls += 1
                        samplesRead += count.toLong()
                        val chunk = frame.copyOf(count)
                        captured?.addAll(chunk.toList())
                        for (sample in chunk) {
                            val value = sample.toInt()
                            val absolute = if (value == Short.MIN_VALUE.toInt()) Short.MAX_VALUE.toInt() else abs(value)
                            peak = maxOf(peak, absolute)
                            val normalized = value.toDouble() / Short.MAX_VALUE.toDouble()
                            energy += normalized * normalized
                            energySamples += 1
                        }
                        val wake = engine.processPcm16(chunk, sampleRate)
                        inferenceFrames += 1
                        lastConfidence = wake.confidence.coerceIn(0.0, 1.0)
                        maxConfidence = maxOf(maxConfidence, lastConfidence)
                        if (wake.detected) detectedFrames += 1
                        if (frames.length() < 80 || wake.detected || lastConfidence >= maxConfidence) {
                            frames.put(JSONObject()
                                .put("index", inferenceFrames)
                                .put("confidence", lastConfidence)
                                .put("detected", wake.detected))
                        }
                    }
                }
            }
        } catch (caught: Exception) {
            error = caught.message ?: caught.javaClass.simpleName
        } finally {
            try {
                recorder?.stop()
            } catch (_: Exception) {
            }
            recorder?.release()
            if (restartListener) {
                HermesVoiceWakeService.start(this, origin)
            }
        }
        val rms = if (energySamples <= 0L) 0.0 else sqrt(energy / energySamples.toDouble())
        val result = JSONObject()
            .put("ok", error.isBlank())
            .put("type", "wake_phrase_score_probe")
            .put("durationMs", System.currentTimeMillis() - startedAt)
            .put("requestedDurationMs", boundedDuration)
            .put("sampleRateHz", sampleRate)
            .put("readCalls", readCalls)
            .put("readErrors", readErrors)
            .put("samplesRead", samplesRead)
            .put("audioPeak", peak)
            .put("audioRms", rms)
            .put("engine", engine.name)
            .put("modelSource", selection.source)
            .put("engineReady", engine.ready)
            .put("diagnosticReason", engine.diagnosticReason)
            .put("lastConfidence", lastConfidence)
            .put("maxConfidence", maxConfidence)
            .put("detectedFrames", detectedFrames)
            .put("inferenceFrames", inferenceFrames)
            .put("frames", frames)
            .put("threshold", HermesVoiceWakeService.configuredWakeThreshold(this))
            .put("restartedListener", restartListener)
            .put("pcmIncluded", includePcmBase64)
        if (error.isNotBlank()) result.put("error", error)
        if (includePcmBase64 && captured != null) {
            val bytes = ByteArray(captured.size * 2)
            for ((index, sample) in captured.withIndex()) {
                val value = sample.toInt()
                bytes[index * 2] = (value and 0xff).toByte()
                bytes[index * 2 + 1] = ((value ushr 8) and 0xff).toByte()
            }
            result
                .put("pcmEncoding", "pcm_s16le_mono_16khz")
                .put("pcmSamples", captured.size)
                .put("pcmBase64", Base64.encodeToString(bytes, Base64.NO_WRAP))
        }
        result.put("status", voiceWakeStatus())
        logDiagnostic("wake_phrase_score_probe", result)
        return result
    }

    private inner class AndroidBridge(private val origin: String) {
        @JavascriptInterface
        fun authSessionId(): String {
            noteBridgeCall("authSessionId")
            return androidAuthSessionId
        }

        @JavascriptInterface
        fun shellInfo(): String {
            noteBridgeCall("shellInfo")
            return nativeShellConfig(origin).toString()
        }

        @JavascriptInterface
        fun logDiagnostic(kind: String, payloadJson: String?) {
            noteBridgeCall("logDiagnostic:$kind")
            val payload = parseJsonPayload(payloadJson)
            rememberRendererReadiness(kind, payload)
            logDiagnostic("renderer_$kind", payload)
        }

        @JavascriptInterface
        fun appReady(payloadJson: String?) {
            noteBridgeCall("appReady")
            val payload = parseJsonPayload(payloadJson)
            logDiagnostic("renderer_app_ready", payload)
            runOnUiThread {
                webView?.alpha = 1f
                hideSplash()
            }
            if (pendingDebugScreen == "train-hermes-wake") {
                collectTrainHermesWakeDiagnostics(true, "renderer_app_ready")
            }
        }

        @JavascriptInterface
        fun openExternal(url: String, reason: String) {
            runOnUiThread {
                openExternalUrl(Uri.parse(url), reason.ifBlank { "renderer_request" })
            }
        }

        @JavascriptInterface
        fun startGoogleLogin() {
            runOnUiThread {
                transitionOAuth("AUTH_START_TAPPED", "renderer_start_google_login")
                startGoogleLogin(origin)
            }
        }
    }

    private inner class AndroidNativeBridge(private val origin: String) {
        @JavascriptInterface
        fun config(): String {
            noteBridgeCall("config")
            return nativeShellConfig(origin).toString()
        }

        @JavascriptInterface
        fun getKernelStatus(): String {
            noteBridgeCall("getKernelStatus")
            return this@MainActivity.nativeKernelStatus().toString()
        }

        @JavascriptInterface
        fun syncDownloadedRuntime(manifestJson: String?): String =
            this@MainActivity.syncDownloadedRuntimeFromManifest(manifestJson, force = false).toString()

        @JavascriptInterface
        fun forceSyncDownloadedRuntime(manifestJson: String?): String =
            this@MainActivity.syncDownloadedRuntimeFromManifest(manifestJson, force = true).toString()

        @JavascriptInterface
        fun rollbackDownloadedRuntime(): String =
            this@MainActivity.rollbackDownloadedRuntime().toString()

        @JavascriptInterface
        fun runDownloadedOperation(operationManifestJson: String?, inputsJson: String?): String =
            this@MainActivity.runDownloadedOperation(operationManifestJson, inputsJson).toString()

	        @JavascriptInterface
	        fun getWakeWordState(): String {
            noteBridgeCall("getWakeWordState")
            return this@MainActivity.wakeWordState().toString()
        }

	        @JavascriptInterface
	        fun noteUserInteraction(reason: String?): String {
            noteBridgeCall("noteUserInteraction")
	            this@MainActivity.markVoiceWakeUiActivity(reason?.take(80) ?: "renderer_input")
	            return JSONObject()
	                .put("ok", true)
	                .put("voiceWakeUiActiveUntil", prefs.getLong(HermesVoiceWakeService.PREF_FOREGROUND_UI_ACTIVE_UNTIL, 0L))
	                .toString()
	        }

	        @JavascriptInterface
	        fun reload() {
            runOnUiThread {
                logDiagnostic("renderer_reload_requested")
                webView?.reload()
            }
        }

        @JavascriptInterface
        fun logAuthDiagnostic(kind: String, payloadJson: String?) {
            val payload = parseJsonPayload(payloadJson)
            rememberRendererReadiness(kind, payload)
            logDiagnostic("renderer_auth_$kind", payload)
        }

        @JavascriptInterface
        fun logDiagnostic(kind: String, payloadJson: String?) {
            noteBridgeCall("nativeBridgeDiagnostic:$kind")
            val payload = parseJsonPayload(payloadJson)
            rememberRendererReadiness(kind, payload)
            this@MainActivity.logDiagnostic("renderer_$kind", payload)
        }

        @JavascriptInterface
        fun uploadAuthDiagnostics(): String {
            logDiagnostic("renderer_auth_upload_requested")
            return JSONObject().put("ok", true).put("path", diagnostics.path()).toString()
        }

        @JavascriptInterface
        fun flushAuthCookies(payloadJson: String?): String {
            val payload = parseJsonPayload(payloadJson)
            val before = safeCookieSummary()
            thread(name = "wasm-agent-cookie-flush") {
                try {
                    CookieManager.getInstance().flush()
                    val cookies = CookieManager.getInstance().getCookie(origin).orEmpty()
                    logDiagnostic("renderer_auth_cookie_flush_finished", payload
                        .put("cookie_count", if (cookies.isBlank()) 0 else cookies.split(";").size)
                        .put("has_wa_uid", cookies.contains("wa_uid=")))
                    if (cookies.contains("wa_uid=")) {
                        transitionOAuth("COOKIE_FLUSHED", "renderer_flush_auth_cookies")
                    }
                } catch (error: Exception) {
                    logDiagnostic("renderer_auth_cookie_flush_failed", JSONObject()
                        .put("error", error.message ?: error.javaClass.simpleName))
                }
            }
            logDiagnostic("renderer_auth_cookie_flush_requested", payload
                .put("async", true)
                .put("cookie_count", before.optInt("cookie_count", 0))
                .put("has_wa_uid", before.optBoolean("has_wa_uid", false)))
            return JSONObject()
                .put("ok", true)
                .put("async", true)
                .put("cookieCount", before.optInt("cookie_count", 0))
                .put("hasWaUid", before.optBoolean("has_wa_uid", false))
                .toString()
        }

        @JavascriptInterface
        fun getNativeState(): String {
            noteBridgeCall("getNativeState")
            return diagnosticsSnapshot().toString()
        }

        @JavascriptInterface
        fun exportLatest(): String = diagnostics.latestString()

        @JavascriptInterface
        fun clearWebViewData(): String {
            return this@MainActivity.clearWebViewData("renderer_native_bridge")
        }

        @JavascriptInterface
        fun resetAuth(): String {
            return resetNativeAuth("renderer_native_bridge")
        }

        @JavascriptInterface
        fun packageInfo(): String = nativePackageInfo().toString()

        @JavascriptInterface
        fun canRequestPackageInstalls(): Boolean {
            return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) packageManager.canRequestPackageInstalls() else true
        }

        @JavascriptInterface
        fun openInstallUnknownAppsSettings(): String {
            runOnUiThread {
                val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName"))
                } else {
                    Intent(Settings.ACTION_SECURITY_SETTINGS)
                }
                try {
                    startActivity(intent)
                    logDiagnostic("update_install_unknown_apps_settings_opened")
                } catch (exc: Exception) {
                    logDiagnostic("update_install_unknown_apps_settings_failed", JSONObject()
                        .put("message", exc.message.orEmpty()))
                }
            }
            return JSONObject()
                .put("ok", true)
                .put("requiresOsConfirmation", true)
                .toString()
        }

        @JavascriptInterface
        fun voiceWakeStatus(): String = voiceWakeStatus().toString()

        @JavascriptInterface
        fun voiceTuningStatus(): String = voiceTuningStatus().toString()

        @JavascriptInterface
        fun getTrainHermesWakeDiagnostics(): String = collectTrainHermesWakeDiagnostics(false, "android_bridge").toString()

        @JavascriptInterface
        fun openTrainHermesWake(): String = collectTrainHermesWakeDiagnostics(true, "android_bridge").toString()

        @JavascriptInterface
        fun startVoiceTuningSample(categoryId: String): String = startVoiceTuningSample(categoryId, null)

        @JavascriptInterface
        fun startVoiceTuningSample(categoryId: String, source: String?): String {
            val request = runCatching { JSONObject(categoryId) }.getOrNull()
            val categoryIdFromRequest = request?.optString("category").orEmpty()
            val kind = request?.optString("kind").orEmpty()
            val label = request?.optString("label").orEmpty()
            val resolvedCategoryId = when {
                categoryIdFromRequest.isNotBlank() -> categoryIdFromRequest
                kind == "hermes" && label == "positive" -> "positive"
                kind == "silence" && label == "negative" -> "negative/silence"
                kind == "speech" && label == "negative" -> "negative/speech"
                kind == "noise" && label == "negative" -> "negative/noise"
                else -> categoryId
            }
            val resolvedSource = request?.optString("source").takeUnless { it.isNullOrBlank() } ?: source
            val category = VoiceTuningCategory.fromId(resolvedCategoryId)
                ?: return JSONObject().put("ok", false).put("error", "unknown_voice_tuning_category").toString()
            logDiagnostic("native_record_request_received", JSONObject()
                .put("kind", category.kind)
                .put("label", category.label)
                .put("duration_ms", VoiceTuningStore.SAMPLE_DURATION_MS)
                .put("prompt", request?.optString("prompt") ?: ""))
            if (!permissionGranted(Manifest.permission.RECORD_AUDIO)) {
                runOnUiThread {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                        requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), REQUEST_VOICE_WAKE_PERMISSION)
                    }
                }
                return JSONObject()
                    .put("ok", false)
                    .put("requested", true)
                    .put("kind", category.kind)
                    .put("label", category.label)
                    .put("error", "permission_denied")
                    .put("message", "Microphone permission is required to record training samples.")
                    .put("status", this@MainActivity.voiceTuningStatus())
                    .toString()
            }
            val result = voiceTuningRecorder.record(category, resolvedSource) { event ->
                logDiagnostic(event.optString("type", "voice_tuning_event"), event)
                when (event.optString("type")) {
                    "voice_tuning_sample_recorded" -> logDiagnostic("native_record_result", event)
                    "voice_tuning_recording_failed" -> logDiagnostic("native_record_error", event)
                    "native_record_started" -> logDiagnostic("native_record_started", event)
                    "native_record_finished" -> logDiagnostic("native_record_finished", event)
                }
                emitRendererEvent("wasm-agent:native-voice-tuning", event)
            }
            return result.put("status", this@MainActivity.voiceTuningStatus()).toString()
        }

        @JavascriptInterface
        fun deleteLastVoiceTuningSample(categoryId: String): String {
            val category = VoiceTuningCategory.fromId(categoryId)
                ?: return JSONObject().put("ok", false).put("error", "unknown_voice_tuning_category").toString()
            val event = voiceTuningStore.deleteLast(category)
            logDiagnostic("voice_tuning_sample_deleted", event)
            emitRendererEvent("wasm-agent:native-voice-tuning", event)
            emitRendererEvent("wasm-agent:native-voice-tuning", this@MainActivity.voiceTuningStatus().put("type", "voice_tuning_counts_updated"))
            return JSONObject().put("ok", true).put("status", this@MainActivity.voiceTuningStatus()).toString()
        }

        @JavascriptInterface
        fun resetVoiceTuningRecordings(): String {
            val event = voiceTuningStore.resetRecordings(File(filesDir, "voice/exports"))
            logDiagnostic("voice_tuning_recordings_reset", event)
            emitRendererEvent("wasm-agent:native-voice-tuning", event)
            emitRendererEvent("wasm-agent:native-voice-tuning", this@MainActivity.voiceTuningStatus().put("type", "voice_tuning_counts_updated"))
            runOnUiThread {
                Toast.makeText(this@MainActivity, "Hermes wake recordings reset.", Toast.LENGTH_SHORT).show()
            }
            return event.put("status", this@MainActivity.voiceTuningStatus()).toString()
        }

        @JavascriptInterface
        fun cancelVoiceTuning(): String {
            val event = voiceTuningRecorder.cancel()
            logDiagnostic("voice_tuning_cancelled", event)
            emitRendererEvent("wasm-agent:native-voice-tuning", event)
            return event.put("status", this@MainActivity.voiceTuningStatus()).toString()
        }

        @JavascriptInterface
        fun exportHermesDataset(): String {
            return try {
                val event = voiceTuningStore.exportDataset(File(filesDir, "voice/exports"))
                val upload = uploadHermesWakeDataset(File(event.optString("path")))
                event.put("upload", upload)
                logDiagnostic("voice_tuning_dataset_exported", event)
                emitRendererEvent("wasm-agent:native-voice-tuning", event)
                runOnUiThread {
                    val message = if (upload.optBoolean("ok", false)) "Hermes dataset exported and uploaded." else "Hermes dataset exported."
                    Toast.makeText(this@MainActivity, message, Toast.LENGTH_SHORT).show()
                }
                event.put("status", this@MainActivity.voiceTuningStatus()).toString()
            } catch (error: Exception) {
                val event = JSONObject()
                    .put("ok", false)
                    .put("type", "voice_tuning_dataset_export_failed")
                    .put("error", error.message ?: error.javaClass.simpleName)
                logDiagnostic("voice_tuning_dataset_export_failed", event)
                event.toString()
            }
        }

        @JavascriptInterface
        fun installHermesWakeModel(modelUrl: String, sha256: String?): String =
            this@MainActivity.installHermesWakeModel(modelUrl, sha256.orEmpty()).toString()

        @JavascriptInterface
        fun installOpenWakeWordBundle(bundleUrl: String, sha256: String?): String =
            this@MainActivity.installOpenWakeWordBundle(bundleUrl, sha256.orEmpty()).toString()

        @JavascriptInterface
        fun playWakePhraseProbe(payloadJson: String?): String {
            val payload = parseJsonPayload(payloadJson)
            return this@MainActivity.playWakePhraseProbe(
                phrase = payload.optString("phrase", payload.optString("wakePhrase", "")),
                languageTag = payload.optString("language", payload.optString("lang", "en-US")),
                rate = payload.optDouble("rate", 0.9).toFloat(),
                pitch = payload.optDouble("pitch", 1.0).toFloat(),
                timeoutMs = payload.optLong("timeoutMs", 7000L),
            ).toString()
        }

        @JavascriptInterface
        fun scoreWakePhraseProbe(payloadJson: String?): String {
            val payload = parseJsonPayload(payloadJson)
            return this@MainActivity.scoreWakePhraseProbe(
                durationMs = payload.optLong("durationMs", payload.optLong("duration_ms", 3500L)),
                restartListener = payload.optBoolean("restartListener", true),
                stopListenerFirst = payload.optBoolean("stopListenerFirst", true),
                includePcmBase64 = payload.optBoolean("includePcmBase64", payload.optBoolean("include_pcm_base64", false)),
            ).toString()
        }

        @JavascriptInterface
        fun requestVoiceWakePermission(): String {
            return try {
                val needed = voiceWakeRuntimePermissions().filter { permission -> !permissionGranted(permission) }
                prefs.edit()
                    .putBoolean(HermesVoiceWakeService.PREF_ENABLED, true)
                    .putString(HermesVoiceWakeService.PREF_ORIGIN, origin)
                    .apply()
                if (needed.isEmpty()) {
                    runOnUiThread { HermesVoiceWakeService.start(this@MainActivity, origin) }
                    JSONObject().put("ok", true).put("granted", true).put("status", voiceWakeStatus()).toString()
                } else {
                    runOnUiThread {
                        try {
                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                                requestPermissions(needed.toTypedArray(), REQUEST_VOICE_WAKE_PERMISSION)
                            }
                        } catch (error: Exception) {
                            logDiagnostic("voice_wake_permission_request_failed", JSONObject()
                                .put("error", error.message ?: error.javaClass.simpleName))
                        }
                    }
                    JSONObject().put("ok", true).put("requested", true).put("missingRuntimePermissions", JSONArray(needed)).put("status", voiceWakeStatus()).toString()
                }
            } catch (error: Exception) {
                JSONObject()
                    .put("ok", false)
                    .put("error", error.message ?: error.javaClass.simpleName)
                    .put("status", voiceWakeStatus())
                    .toString()
            }
        }

        @JavascriptInterface
        fun enableVoiceWake(): String {
            if (!permissionGranted(Manifest.permission.RECORD_AUDIO)) {
                return JSONObject()
                    .put("ok", false)
                    .put("error", "record_audio_permission_missing")
                    .put("status", voiceWakeStatus())
                    .toString()
            }
            prefs.edit()
                .putBoolean(HermesVoiceWakeService.PREF_ENABLED, true)
                .putString(HermesVoiceWakeService.PREF_ORIGIN, origin)
                .apply()
            runOnUiThread {
                HermesVoiceWakeService.start(this@MainActivity, origin)
                logDiagnostic("voice_wake_enable_requested", JSONObject().put("origin", origin))
            }
            return JSONObject().put("ok", true).put("status", voiceWakeStatus()).toString()
        }

        @JavascriptInterface
        fun beginHermesWakeProof(): String = this@MainActivity.beginHermesWakeProof("native_bridge").toString()

        @JavascriptInterface
        fun getHermesWakeProof(): String = this@MainActivity.voiceWakeStatus().toString()

        @JavascriptInterface
        fun getFalseWakeBatch(): String = FalseWakeStore.batch(this@MainActivity).toString()

        @JavascriptInterface
        fun confirmFalseWakeBatchUploaded(idsJson: String?): String =
            this@MainActivity.confirmFalseWakeBatchUploaded(idsJson).toString()

        @JavascriptInterface
        fun disableVoiceWake(): String {
            prefs.edit().putBoolean(HermesVoiceWakeService.PREF_ENABLED, false).apply()
            runOnUiThread {
                HermesVoiceWakeService.stop(this@MainActivity)
                logDiagnostic("voice_wake_disable_requested")
            }
            return JSONObject().put("ok", true).put("status", voiceWakeStatus()).toString()
        }
    }

    private inner class AndroidVoiceTuningBridge(private val origin: String) {
        private fun nativeBridge(): AndroidNativeBridge = AndroidNativeBridge(origin)

        @JavascriptInterface
        fun getStatus(): String = nativeBridge().voiceTuningStatus()

        @JavascriptInterface
        fun getKernelStatus(): String = this@MainActivity.nativeKernelStatus().toString()

        @JavascriptInterface
        fun syncDownloadedRuntime(manifestJson: String?): String =
            this@MainActivity.syncDownloadedRuntimeFromManifest(manifestJson, force = false).toString()

        @JavascriptInterface
        fun forceSyncDownloadedRuntime(manifestJson: String?): String =
            this@MainActivity.syncDownloadedRuntimeFromManifest(manifestJson, force = true).toString()

        @JavascriptInterface
        fun rollbackDownloadedRuntime(): String =
            this@MainActivity.rollbackDownloadedRuntime().toString()

        @JavascriptInterface
        fun runDownloadedOperation(operationManifestJson: String?, inputsJson: String?): String =
            this@MainActivity.runDownloadedOperation(operationManifestJson, inputsJson).toString()

        @JavascriptInterface
        fun getWakeWordState(): String = this@MainActivity.wakeWordState().toString()

        @JavascriptInterface
        fun getBuildInfo(): String = this@MainActivity.voiceTuningBridgeBuildInfo().toString()

        @JavascriptInterface
        fun isRecordingSupported(): Boolean = permissionGranted(Manifest.permission.RECORD_AUDIO)

        @JavascriptInterface
        fun voiceTuningStatus(): String = nativeBridge().voiceTuningStatus()

        @JavascriptInterface
        fun getVoiceTuningDiagnostics(): String = this@MainActivity.voiceTuningBridgeDiagnostics().toString()

        @JavascriptInterface
        fun startVoiceTuningSample(payloadJson: String): String = nativeBridge().startVoiceTuningSample(payloadJson)

        @JavascriptInterface
        fun stopVoiceTuningSample(): String = nativeBridge().cancelVoiceTuning()

        @JavascriptInterface
        fun deleteLastVoiceTuningSample(categoryId: String): String = nativeBridge().deleteLastVoiceTuningSample(categoryId)

        @JavascriptInterface
        fun resetVoiceTuningRecordings(): String = nativeBridge().resetVoiceTuningRecordings()

        @JavascriptInterface
        fun cancelVoiceTuning(): String = nativeBridge().cancelVoiceTuning()

        @JavascriptInterface
        fun exportHermesDataset(): String = nativeBridge().exportHermesDataset()

        @JavascriptInterface
        fun installHermesWakeModel(modelUrl: String, sha256: String?): String =
            this@MainActivity.installHermesWakeModel(modelUrl, sha256.orEmpty()).toString()

        @JavascriptInterface
        fun installOpenWakeWordBundle(bundleUrl: String, sha256: String?): String =
            this@MainActivity.installOpenWakeWordBundle(bundleUrl, sha256.orEmpty()).toString()

        @JavascriptInterface
        fun playWakePhraseProbe(payloadJson: String?): String = nativeBridge().playWakePhraseProbe(payloadJson)

        @JavascriptInterface
        fun scoreWakePhraseProbe(payloadJson: String?): String = nativeBridge().scoreWakePhraseProbe(payloadJson)

        @JavascriptInterface
        fun beginHermesWakeProof(): String = this@MainActivity.beginHermesWakeProof("voice_tuning_bridge").toString()

        @JavascriptInterface
        fun getHermesWakeProof(): String = this@MainActivity.voiceWakeStatus().toString()

        @JavascriptInterface
        fun getFalseWakeBatch(): String = FalseWakeStore.batch(this@MainActivity).toString()

        @JavascriptInterface
        fun confirmFalseWakeBatchUploaded(idsJson: String?): String =
            this@MainActivity.confirmFalseWakeBatchUploaded(idsJson).toString()

        @JavascriptInterface
        fun getTrainHermesWakeDiagnostics(): String = collectTrainHermesWakeDiagnostics(false, "voice_tuning_bridge").toString()

        @JavascriptInterface
        fun openTrainHermesWake(): String = collectTrainHermesWakeDiagnostics(true, "voice_tuning_bridge").toString()
    }

    private inner class AndroidDiagnosticsBridge(private val origin: String) {
        @JavascriptInterface
        fun record(eventName: String, payloadJson: String?): String {
            val cleanName = eventName.take(120)
            val payload = parseJsonPayload(payloadJson)
            rememberRendererReadiness(cleanName, payload)
            mapRendererDiagnosticToOAuthStage(cleanName, payload)
            logDiagnostic("android_diagnostics_bridge_record", JSONObject()
                .put("event_name", cleanName)
                .put("payload", payload))
            return JSONObject()
                .put("ok", true)
                .put("stage", oauthStage)
                .put("android_auth_session", androidAuthSessionId)
                .put("native_correlation_id", nativeCorrelationId)
                .toString()
        }

        @JavascriptInterface
        fun getNativeState(): String = diagnosticsSnapshot().toString()

        @JavascriptInterface
        fun getKernelStatus(): String = this@MainActivity.nativeKernelStatus().toString()

        @JavascriptInterface
        fun syncDownloadedRuntime(manifestJson: String?): String =
            this@MainActivity.syncDownloadedRuntimeFromManifest(manifestJson, force = false).toString()

        @JavascriptInterface
        fun forceSyncDownloadedRuntime(manifestJson: String?): String =
            this@MainActivity.syncDownloadedRuntimeFromManifest(manifestJson, force = true).toString()

        @JavascriptInterface
        fun rollbackDownloadedRuntime(): String =
            this@MainActivity.rollbackDownloadedRuntime().toString()

        @JavascriptInterface
        fun runDownloadedOperation(operationManifestJson: String?, inputsJson: String?): String =
            this@MainActivity.runDownloadedOperation(operationManifestJson, inputsJson).toString()

        @JavascriptInterface
        fun exportLatest(): String = diagnostics.latestString()

        @JavascriptInterface
        fun clearDiagnostics(): String {
            diagnostics.clear(diagnosticsSnapshot())
            logDiagnostic("android_diagnostics_cleared")
            return JSONObject().put("ok", true).toString()
        }

        @JavascriptInterface
        fun clearWebViewData(): String = this@MainActivity.clearWebViewData("diagnostics_bridge")

        @JavascriptInterface
        fun resetAuth(): String = this@MainActivity.resetNativeAuth("diagnostics_bridge")

        @JavascriptInterface
        fun voiceWakeStatus(): String = this@MainActivity.voiceWakeStatus().toString()

        @JavascriptInterface
        fun voiceTuningStatus(): String = this@MainActivity.voiceTuningStatus().toString()

        @JavascriptInterface
        fun getTrainHermesWakeDiagnostics(): String = collectTrainHermesWakeDiagnostics(false, "diagnostics_bridge").toString()

        @JavascriptInterface
        fun openTrainHermesWake(): String = collectTrainHermesWakeDiagnostics(true, "diagnostics_bridge").toString()

        @JavascriptInterface
        fun startVoiceTuningSample(categoryId: String): String = AndroidNativeBridge(origin).startVoiceTuningSample(categoryId)

        @JavascriptInterface
        fun startVoiceTuningSample(categoryId: String, source: String?): String = AndroidNativeBridge(origin).startVoiceTuningSample(categoryId, source)

        @JavascriptInterface
        fun deleteLastVoiceTuningSample(categoryId: String): String = AndroidNativeBridge(origin).deleteLastVoiceTuningSample(categoryId)

        @JavascriptInterface
        fun cancelVoiceTuning(): String = AndroidNativeBridge(origin).cancelVoiceTuning()

        @JavascriptInterface
        fun exportHermesDataset(): String = AndroidNativeBridge(origin).exportHermesDataset()

        @JavascriptInterface
        fun requestVoiceWakePermission(): String = AndroidNativeBridge(origin).requestVoiceWakePermission()

        @JavascriptInterface
        fun enableVoiceWake(): String = AndroidNativeBridge(origin).enableVoiceWake()

        @JavascriptInterface
        fun disableVoiceWake(): String = AndroidNativeBridge(origin).disableVoiceWake()

        @JavascriptInterface
        fun beginHermesWakeProof(): String = this@MainActivity.beginHermesWakeProof("diagnostics_bridge").toString()

        @JavascriptInterface
        fun getHermesWakeProof(): String = this@MainActivity.voiceWakeStatus().toString()

        @JavascriptInterface
        fun getFalseWakeBatch(): String = FalseWakeStore.batch(this@MainActivity).toString()

        @JavascriptInterface
        fun confirmFalseWakeBatchUploaded(idsJson: String?): String =
            this@MainActivity.confirmFalseWakeBatchUploaded(idsJson).toString()

        @JavascriptInterface
        fun retryGoogleLogin(): String {
            runOnUiThread { startGoogleLogin(origin) }
            return JSONObject().put("ok", true).toString()
        }

        @JavascriptInterface
        fun shareLatest(): String {
            val latest = diagnostics.latestString()
            runOnUiThread {
                try {
                    val intent = Intent(Intent.ACTION_SEND)
                        .setType("application/json")
                        .putExtra(Intent.EXTRA_SUBJECT, "WASM Agent Android diagnostics")
                        .putExtra(Intent.EXTRA_TEXT, latest)
                    startActivity(Intent.createChooser(intent, "Share diagnostics"))
                    logDiagnostic("android_diagnostics_share_requested")
                } catch (error: Exception) {
                    rememberException("android_diagnostics_share_failed", error)
                    Toast.makeText(this@MainActivity, "Could not share diagnostics.", Toast.LENGTH_SHORT).show()
                }
            }
            return JSONObject().put("ok", true).toString()
        }
    }

    private fun jsonArray(values: List<String>): JSONArray {
        val array = JSONArray()
        values.forEach { value -> array.put(value) }
        return array
    }

    private fun jsonStringList(array: JSONArray?): List<String> {
        if (array == null) return emptyList()
        return (0 until array.length()).mapNotNull { index ->
            array.optString(index, "").takeIf { it.isNotBlank() }
        }
    }

    private fun activeDownloadedRuntimeStatus(): JSONObject {
        val activeId = prefs.getString(PREF_ACTIVE_RUNTIME_ID, "").orEmpty()
        val activeSha = prefs.getString(PREF_ACTIVE_RUNTIME_SHA, "").orEmpty()
        val lastGoodId = prefs.getString(PREF_LAST_GOOD_RUNTIME_ID, "").orEmpty()
        val lastGoodSha = prefs.getString(PREF_LAST_GOOD_RUNTIME_SHA, "").orEmpty()
        val syncStatus = prefs.getString(PREF_LAST_RUNTIME_SYNC_STATUS, "").orEmpty()
            .ifBlank { if (activeId.isBlank()) "not_synced" else "cached" }
        return JSONObject()
            .put("supported", true)
            .put("protocol", 1)
            .put("runtimeLoaderProtocolVersion", 1)
            .put("storage", "shared-preferences-and-webview-cache")
            .put("activeRuntimeId", activeId)
            .put("activeRuntimeSha", activeSha)
            .put("activeDownloadedRuntimeId", activeId)
            .put("activeDownloadedRuntimeSha", activeSha)
            .put("activeManifestSha", prefs.getString(PREF_ACTIVE_RUNTIME_MANIFEST_SHA, "").orEmpty())
            .put("activeRuntimeActivatedAt", prefs.getString(PREF_ACTIVE_RUNTIME_SYNCED_AT, "").orEmpty())
            .put("lastKnownGoodRuntimeId", lastGoodId)
            .put("lastKnownGoodRuntimeSha", lastGoodSha)
            .put("syncStatus", syncStatus)
            .put("stale", syncStatus.contains("stale", ignoreCase = true))
            .put("staleReason", if (syncStatus.contains("stale", ignoreCase = true)) syncStatus else "")
    }

    private fun activeHotOpStatus(): JSONObject {
        return JSONObject()
            .put("supported", true)
            .put("protocol", 1)
            .put("activeHotOpBundleId", prefs.getString(PREF_ACTIVE_HOT_OP_ID, "").orEmpty())
            .put("activeHotOpSha", prefs.getString(PREF_ACTIVE_HOT_OP_SHA, "").orEmpty())
            .put("source", "downloaded-runtime-webview-bridge")
    }

    private fun nativeKernelStatus(): JSONObject {
        val supported = NativeBridgeContract.androidKernelCapabilities
        val unsupported = NativeBridgeContract.allKernelCapabilities.filter { capability -> capability !in supported }
        val runtime = activeDownloadedRuntimeStatus()
        val hotOps = activeHotOpStatus()
        return JSONObject()
            .put("schema", "hermes.wasm_agent.native_kernel_status.v1")
            .put("native.kernel.version", NativeBridgeContract.KERNEL_CONTRACT_VERSION)
            .put("nativeKernelVersion", NativeBridgeContract.KERNEL_CONTRACT_VERSION)
            .put("kernelContractVersion", NativeBridgeContract.KERNEL_CONTRACT_VERSION)
            .put("platform", "android")
            .put("runtime", "android-webview")
            .put("installedNativeBuildId", BuildConfig.NATIVE_BUILD_ID)
            .put("nativeBuildId", BuildConfig.NATIVE_BUILD_ID)
            .put("installedNativeVersion", nativePackageInfo().optString("versionName"))
            .put("supportedCapabilities", jsonArray(supported))
            .put("missingCapabilities", JSONArray())
            .put("unsupportedCapabilities", jsonArray(unsupported))
            .put("bridgeProtocolCapabilities", jsonArray(NativeBridgeContract.nativeKernelMethods + NativeBridgeContract.voiceTuningMethods))
            .put("downloadedRuntime", runtime)
            .put("hotOperations", hotOps)
            .put("activeDownloadedRuntimeId", runtime.optString("activeRuntimeId"))
            .put("activeDownloadedRuntimeSha", runtime.optString("activeRuntimeSha"))
            .put("activeHotOpBundleId", hotOps.optString("activeHotOpBundleId"))
            .put("activeHotOpSha", hotOps.optString("activeHotOpSha"))
            .put("syncStatus", JSONObject()
                .put("runtime", runtime.optString("syncStatus"))
                .put("hotOps", if (hotOps.optString("activeHotOpBundleId").isBlank()) "not_synced" else "cached"))
            .put("stale", runtime.optBoolean("stale", false))
            .put("staleReason", runtime.optString("staleReason"))
    }

    private fun syncDownloadedRuntimeFromManifest(payloadJson: String?, force: Boolean): JSONObject {
        val manifest = parseJsonPayload(payloadJson)
        val bundleId = manifest.optString("bundleId", manifest.optString("runtimeId", manifest.optString("id", "")))
        val bundleSha = manifest.optString("bundleSha", manifest.optString("sha256", manifest.optString("trustedSha256", "")))
        val manifestSha = manifest.optString("manifestSha", "")
        if (bundleId.isBlank() || bundleSha.isBlank()) {
            prefs.edit().putString(PREF_LAST_RUNTIME_SYNC_STATUS, "runtime_manifest_invalid").apply()
            return JSONObject()
                .put("ok", false)
                .put("operation", if (force) "forceSyncDownloadedRuntime" else "syncDownloadedRuntime")
                .put("error", "runtime_manifest_invalid")
                .put("failureClassification", "runtime_manifest_invalid")
                .put("downloadedRuntime", activeDownloadedRuntimeStatus())
        }
        val required = jsonStringList(manifest.optJSONArray("requiredNativeCapabilities"))
        val missing = required.filter { capability -> capability !in NativeBridgeContract.androidKernelCapabilities }
        if (missing.isNotEmpty()) {
            prefs.edit().putString(PREF_LAST_RUNTIME_SYNC_STATUS, "runtime_missing_capability").apply()
            return JSONObject()
                .put("ok", false)
                .put("operation", if (force) "forceSyncDownloadedRuntime" else "syncDownloadedRuntime")
                .put("error", "runtime_missing_capability")
                .put("failureClassification", "native_capability_missing")
                .put("missingNativeCapabilities", jsonArray(missing))
                .put("downloadedRuntime", activeDownloadedRuntimeStatus())
        }
        val previousId = prefs.getString(PREF_ACTIVE_RUNTIME_ID, "").orEmpty()
        val previousSha = prefs.getString(PREF_ACTIVE_RUNTIME_SHA, "").orEmpty()
        val changed = force || previousId != bundleId || previousSha != bundleSha
        val editor = prefs.edit()
        if (changed && previousId.isNotBlank() && previousSha.isNotBlank()) {
            editor.putString(PREF_LAST_GOOD_RUNTIME_ID, previousId)
            editor.putString(PREF_LAST_GOOD_RUNTIME_SHA, previousSha)
        }
        editor.putString(PREF_ACTIVE_RUNTIME_ID, bundleId)
            .putString(PREF_ACTIVE_RUNTIME_SHA, bundleSha)
            .putString(PREF_ACTIVE_RUNTIME_MANIFEST_SHA, manifestSha)
            .putString(PREF_ACTIVE_RUNTIME_SYNCED_AT, System.currentTimeMillis().toString())
            .putString(PREF_LAST_RUNTIME_SYNC_STATUS, if (changed) "activated" else "current")
            .apply()
        return JSONObject()
            .put("ok", true)
            .put("operation", if (force) "forceSyncDownloadedRuntime" else "syncDownloadedRuntime")
            .put("changed", changed)
            .put("bundleId", bundleId)
            .put("bundleSha", bundleSha)
            .put("downloadedRuntime", activeDownloadedRuntimeStatus())
            .put("kernel", nativeKernelStatus())
    }

    private fun rollbackDownloadedRuntime(): JSONObject {
        val lastGoodId = prefs.getString(PREF_LAST_GOOD_RUNTIME_ID, "").orEmpty()
        val lastGoodSha = prefs.getString(PREF_LAST_GOOD_RUNTIME_SHA, "").orEmpty()
        if (lastGoodId.isBlank() || lastGoodSha.isBlank()) {
            return JSONObject()
                .put("ok", false)
                .put("operation", "rollbackDownloadedRuntime")
                .put("error", "last_known_good_missing")
                .put("downloadedRuntime", activeDownloadedRuntimeStatus())
        }
        val activeId = prefs.getString(PREF_ACTIVE_RUNTIME_ID, "").orEmpty()
        val activeSha = prefs.getString(PREF_ACTIVE_RUNTIME_SHA, "").orEmpty()
        prefs.edit()
            .putString(PREF_ACTIVE_RUNTIME_ID, lastGoodId)
            .putString(PREF_ACTIVE_RUNTIME_SHA, lastGoodSha)
            .putString(PREF_LAST_GOOD_RUNTIME_ID, activeId)
            .putString(PREF_LAST_GOOD_RUNTIME_SHA, activeSha)
            .putString(PREF_LAST_RUNTIME_SYNC_STATUS, "rolled_back_to_last_known_good")
            .apply()
        return JSONObject()
            .put("ok", true)
            .put("operation", "rollbackDownloadedRuntime")
            .put("downloadedRuntime", activeDownloadedRuntimeStatus())
            .put("kernel", nativeKernelStatus())
    }

    private fun runDownloadedOperation(operationJson: String?, inputsJson: String?): JSONObject {
        val manifest = parseJsonPayload(operationJson)
        val inputs = parseJsonPayload(inputsJson)
        val operationId = manifest.optString("operationId", manifest.optString("name", ""))
        val required = jsonStringList(manifest.optJSONArray("requiredNativeCapabilities"))
        val missing = required.filter { capability -> capability !in NativeBridgeContract.androidKernelCapabilities }
        val timeoutMs = manifest.optLong("timeoutMs", 5000L).coerceIn(250L, 180000L)
        if (missing.isNotEmpty()) {
            return JSONObject()
                .put("ok", false)
                .put("stable", false)
                .put("operation", operationId)
                .put("timeoutMs", timeoutMs)
                .put("error", "native_capability_missing")
                .put("failureClassification", "native_capability_missing")
                .put("missingNativeCapabilities", jsonArray(missing))
                .put("kernel", nativeKernelStatus())
        }
        return when (operationId) {
            "get_native_kernel_status", "native.status", "android_native_status" -> JSONObject()
                .put("ok", true)
                .put("stable", true)
                .put("operation", operationId)
                .put("timeoutMs", timeoutMs)
                .put("kernel", nativeKernelStatus())
                .put("inputs", inputs)
                .put("failureClassification", "pass")
            "fetch_wake_word_state", "android.wake_word.state", LEGACY_FETCH_WAKE_WORD_STATE_OPERATION -> wakeWordState()
                .put("ok", true)
                .put("stable", true)
                .put("operation", operationId)
                .put("timeoutMs", timeoutMs)
                .put("failureClassification", "pass")
            "apply_wake_word_policy", "android.wake_word.apply_policy" -> applyWakeWordPolicy(inputs)
                .put("stable", true)
                .put("operation", operationId)
                .put("timeoutMs", timeoutMs)
                .put("failureClassification", "pass")
            "run_android_hermes_wake_proof" -> {
                val requestedThreshold = HermesVoiceWakeService.normalizedWakeThreshold(
                    inputs.optDouble("wake_threshold", inputs.optDouble("wakeThreshold", Double.NaN)),
                )
                val origin = inputs.optString("origin", selectedOrigin)
                    .ifBlank { prefs.getString(HermesVoiceWakeService.PREF_ORIGIN, "").orEmpty() }
                    .ifBlank { BuildConfig.DEFAULT_SERVER_URL }
                val needed = voiceWakeRuntimePermissions().filter { permission -> !permissionGranted(permission) }
                if (requestedThreshold != null) {
                    prefs.edit()
                        .putFloat(HermesVoiceWakeService.PREF_WAKE_THRESHOLD, requestedThreshold.toFloat())
                        .putString(HermesVoiceWakeService.PREF_WAKE_THRESHOLD_SOURCE, HermesVoiceWakeService.THRESHOLD_SOURCE_REMOTE_CONFIG)
                        .apply()
                }
                prefs.edit()
                    .putBoolean(HermesVoiceWakeService.PREF_ENABLED, true)
                    .putString(HermesVoiceWakeService.PREF_ORIGIN, origin)
                    .apply()
                if (needed.isEmpty()) {
                    runOnUiThread {
                        HermesVoiceWakeService.start(this, origin, proofSession = true, wakeThreshold = requestedThreshold)
                    }
                } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    runOnUiThread { requestPermissions(needed.toTypedArray(), REQUEST_VOICE_WAKE_PERMISSION) }
                }
                JSONObject()
                    .put("ok", needed.isEmpty())
                    .put("stable", false)
                    .put("operation", operationId)
                    .put("timeoutMs", timeoutMs)
                    .put("started", needed.isEmpty())
                    .put("missingRuntimePermissions", JSONArray(needed))
                    .put("wakeThreshold", HermesVoiceWakeService.configuredWakeThreshold(this))
                    .put("thresholdPolicySource", normalizedThresholdPolicySource())
                    .put("status", voiceWakeStatus())
                    .put("kernel", nativeKernelStatus())
                    .put("failureClassification", if (needed.isEmpty()) "proof_started" else "record_audio_permission_missing")
            }
            "prove_wake_word_loop", LEGACY_PROVE_WAKE_WORD_LOOP_OPERATION -> {
                val proof = beginHermesWakeProof("wake_word_operation", HermesVoiceWakeService.normalizedWakeThreshold(
                    inputs.optDouble("wake_threshold", inputs.optDouble("wakeThreshold", Double.NaN)),
                ))
                JSONObject()
                    .put("ok", proof.optBoolean("ok", false))
                    .put("stable", false)
                    .put("operation", operationId)
                    .put("timeoutMs", timeoutMs)
                    .put("proof", proof)
                    .put("state", wakeWordState())
                    .put("failureClassification", if (proof.optBoolean("ok", false)) "proof_started" else proof.optString("failureClassification", "record_audio_permission_missing"))
            }
            "get_android_false_wake_batch", "android.false_wake.batch" -> FalseWakeStore.batch(this)
                .put("stable", true)
                .put("operation", operationId)
                .put("timeoutMs", timeoutMs)
                .put("failureClassification", "pass")
            "confirm_android_false_wake_batch_uploaded", "android.false_wake.confirm_uploaded" -> {
                val ids = jsonStringList(inputs.optJSONArray("ids"))
                confirmFalseWakeBatchUploaded(ids)
                    .put("stable", true)
                    .put("operation", operationId)
                    .put("timeoutMs", timeoutMs)
                    .put("failureClassification", "pass")
            }
            "canary_echo" -> JSONObject()
                .put("ok", true)
                .put("stable", true)
                .put("operation", operationId)
                .put("message", "downloaded operation manifest accepted")
                .put("failureClassification", "pass")
            else -> JSONObject()
                .put("ok", false)
                .put("stable", false)
                .put("operation", operationId)
                .put("timeoutMs", timeoutMs)
                .put("error", "downloaded_operation_not_supported")
                .put("failureClassification", "downloaded_operation_not_supported")
                .put("nextAction", "Run product logic from the downloaded WebView/runtime bundle and call stable native bridge primitives.")
                .put("kernel", nativeKernelStatus())
        }
    }

    private fun nativeShellConfig(origin: String): JSONObject {
        return JSONObject()
            .put("schema", "hermes.wasm_agent.android_native_shell.v1")
            .put("appId", "wasm-agent")
            .put("service", "wasm-agent")
            .put("serverUrl", origin)
            .put("serverUrlCandidates", JSONArray(candidates))
            .put("mode", if (BuildConfig.ALLOW_LOCAL_DEV) "debug" else "production")
            .put("allowLocalDev", BuildConfig.ALLOW_LOCAL_DEV)
            .put("platform", "android")
            .put("buildPlatform", "android")
            .put("shell", "android-webview")
            .put("nativeShell", "android-webview")
            .put("buildId", BuildConfig.NATIVE_BUILD_ID)
            .put("buildGeneratedAt", BuildConfig.BUILD_GENERATED_AT)
            .put("packageInfo", nativePackageInfo())
            .put("androidAuthSession", androidAuthSessionId)
            .put("nativeCorrelationId", nativeCorrelationId)
            .put("installDeviceHash", installDeviceHash)
            .put("deviceId", "android-${BuildConfig.NATIVE_BUILD_ID}")
            .put("nativeKernel", nativeKernelStatus())
            .put("downloadedRuntime", activeDownloadedRuntimeStatus())
            .put("hotOperations", activeHotOpStatus())
            .put("voiceWake", voiceWakeStatusLightweight())
            .put("nativeWebViewBoot", nativeWebViewBootTiming())
            .put("diagnosticsPath", diagnostics.path())
    }

    private fun nativeWebViewBootTiming(): JSONObject {
        val base = activityCreatedAt.takeIf { it > 0L } ?: webViewPageStartedAt
        fun delta(value: Long): Long = if (base > 0L && value > 0L) value - base else 0L
        return JSONObject()
            .put("activity_created_at", activityCreatedAt)
            .put("page_started_at", webViewPageStartedAt)
            .put("page_commit_visible_at", webViewPageCommitVisibleAt)
            .put("page_finished_at", webViewPageFinishedAt)
            .put("activity_to_page_started_ms", delta(webViewPageStartedAt))
            .put("activity_to_page_commit_visible_ms", delta(webViewPageCommitVisibleAt))
            .put("activity_to_page_finished_ms", delta(webViewPageFinishedAt))
            .put("page_started_to_commit_visible_ms", if (webViewPageStartedAt > 0L && webViewPageCommitVisibleAt > 0L) webViewPageCommitVisibleAt - webViewPageStartedAt else 0L)
            .put("page_started_to_finished_ms", if (webViewPageStartedAt > 0L && webViewPageFinishedAt > 0L) webViewPageFinishedAt - webViewPageStartedAt else 0L)
            .put("latest_url", latestWebViewUrl)
            .put("main_frame_error", webViewMainFrameError ?: JSONObject.NULL)
    }

    private fun nativePackageInfo(): JSONObject {
        val packageInfo = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            packageManager.getPackageInfo(packageName, PackageManager.PackageInfoFlags.of(0))
        } else {
            @Suppress("DEPRECATION")
            packageManager.getPackageInfo(packageName, 0)
        }
        val versionCode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            packageInfo.longVersionCode
        } else {
            @Suppress("DEPRECATION")
            packageInfo.versionCode.toLong()
        }
        return JSONObject()
            .put("packageName", packageName)
            .put("versionName", packageInfo.versionName.orEmpty())
            .put("versionCode", versionCode)
            .put("buildId", BuildConfig.NATIVE_BUILD_ID)
            .put("buildGeneratedAt", BuildConfig.BUILD_GENERATED_AT)
            .put("canRequestPackageInstalls", if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) packageManager.canRequestPackageInstalls() else true)
    }

    private fun parseJsonPayload(payloadJson: String?): JSONObject {
        val payload = payloadJson.orEmpty()
        if (payload.isBlank()) return JSONObject()
        return try {
            JSONObject(payload)
        } catch (_: Exception) {
            JSONObject().put("raw", payload.take(1000))
        }
    }

    private fun retrySelectedOrResolve() {
        hideErrorScreen()
        if (selectedOrigin.isNotBlank()) {
            openRemotePwaWebView(selectedOrigin)
            return
        }
        resolveBackend()
    }

    private fun showSplash(title: String, message: String) {
        val existing = splashView
        if (existing != null) {
            existing.findViewWithTag<TextView>("title")?.text = title
            existing.findViewWithTag<TextView>("message")?.text = message
            existing.visibility = View.VISIBLE
            return
        }
        val layout = brandedLayout()
        val mark = brandMark()
        val titleView = TextView(this)
        titleView.tag = "title"
        titleView.text = title
        titleView.setTextColor(BRAND_TEXT)
        titleView.textSize = 28f
        titleView.typeface = Typeface.DEFAULT_BOLD
        titleView.gravity = Gravity.CENTER
        val messageView = TextView(this)
        messageView.tag = "message"
        messageView.text = message
        messageView.setTextColor(BRAND_MUTED)
        messageView.textSize = 15f
        messageView.gravity = Gravity.CENTER
        val progress = ProgressBar(this)
        progress.isIndeterminate = true
        layout.addView(mark)
        layout.addView(titleView, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT,
            ViewGroup.LayoutParams.WRAP_CONTENT,
        ).apply { topMargin = dp(18) })
        layout.addView(messageView, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT,
        ).apply { topMargin = dp(8) })
        layout.addView(progress, LinearLayout.LayoutParams(dp(42), dp(42)).apply { topMargin = dp(22) })
        splashView = layout
        container.addView(layout)
    }

    private fun hideSplash() {
        splashView?.visibility = View.GONE
    }

    private fun showErrorScreen(title: String, message: String) {
        hideSplash()
        val previous = errorView
        if (previous != null) container.removeView(previous)
        val layout = brandedLayout()
        val mark = brandMark()
        val titleView = TextView(this)
        titleView.text = title
        titleView.setTextColor(BRAND_TEXT)
        titleView.textSize = 24f
        titleView.typeface = Typeface.DEFAULT_BOLD
        titleView.gravity = Gravity.CENTER
        val messageView = TextView(this)
        messageView.text = message
        messageView.setTextColor(BRAND_MUTED)
        messageView.textSize = 15f
        messageView.gravity = Gravity.CENTER
        val retry = Button(this)
        retry.text = "Retry"
        retry.setTextColor(BRAND_BG)
        retry.typeface = Typeface.DEFAULT_BOLD
        retry.background = GradientDrawable().apply {
            cornerRadius = dp(8).toFloat()
            setColor(BRAND_ACCENT)
        }
        retry.setOnClickListener { retrySelectedOrResolve() }
        layout.addView(mark)
        layout.addView(titleView, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT,
        ).apply { topMargin = dp(18) })
        layout.addView(messageView, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT,
        ).apply { topMargin = dp(10) })
        layout.addView(retry, LinearLayout.LayoutParams(dp(148), dp(46)).apply { topMargin = dp(24) })
        errorView = layout
        container.addView(layout)
    }

    private fun hideErrorScreen() {
        errorView?.let { container.removeView(it) }
        errorView = null
    }

    private fun brandedLayout(): LinearLayout {
        val layout = LinearLayout(this)
        layout.orientation = LinearLayout.VERTICAL
        layout.gravity = Gravity.CENTER
        layout.setPadding(dp(28), dp(28), dp(28), dp(28))
        layout.setBackgroundColor(BRAND_BG)
        layout.layoutParams = FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT,
        )
        return layout
    }

    private fun brandMark(): TextView {
        val mark = TextView(this)
        mark.text = "WA"
        mark.gravity = Gravity.CENTER
        mark.setTextColor(BRAND_TEXT)
        mark.textSize = 20f
        mark.typeface = Typeface.DEFAULT_BOLD
        mark.background = GradientDrawable(GradientDrawable.Orientation.TL_BR, intArrayOf(BRAND_PANEL, 0xFF123A4A.toInt())).apply {
            cornerRadius = dp(18).toFloat()
            setStroke(dp(1), BRAND_ACCENT)
        }
        mark.layoutParams = LinearLayout.LayoutParams(dp(82), dp(82))
        return mark
    }

    private fun emitRendererEvent(name: String, payload: JSONObject = JSONObject()) {
        runOnUiThread {
            val script = """
                (() => {
                  try {
                    window.dispatchEvent(new CustomEvent(${JSONObject.quote(name)}, { detail: $payload }));
                  } catch (_) {}
                })();
            """.trimIndent()
            webView?.evaluateJavascript(script, null)
        }
    }

    private fun collectTrainHermesWakeDiagnostics(openModal: Boolean, source: String): JSONObject {
        val result = JSONObject()
            .put("ok", false)
            .put("source", source)
            .put("open_requested", openModal)
        val latch = CountDownLatch(1)
        runOnUiThread {
            val script = """
                (() => {
                  try {
                    const api = window.__wasmAgentTuneVoice;
                    if (!api || typeof api.diagnostics !== "function") {
                      return JSON.stringify({ ok: false, error: "tune_voice_api_missing" });
                    }
                    const payload = ${if (openModal) "api.open(" else "api.diagnostics("}${JSONObject.quote(source)}${if (openModal) ")" else ")"};
                    return JSON.stringify({ ok: true, payload });
                  } catch (error) {
                    return JSON.stringify({ ok: false, error: String(error && error.message ? error.message : error) });
                  }
                })();
            """.trimIndent()
            webView?.evaluateJavascript(script) { raw ->
                try {
                    val clean = raw.orEmpty().trim().removeSurrounding("\"").replace("\\\"", "\"").replace("\\\\", "\\")
                    val parsed = if (clean.isBlank() || clean == "null") JSONObject() else JSONObject(clean)
                    result.put("ok", parsed.optBoolean("ok", false))
                    result.put("error", parsed.optString("error", ""))
                    result.put("payload", parsed.optJSONObject("payload") ?: JSONObject())
                } catch (error: Exception) {
                    result.put("ok", false)
                    result.put("error", error.javaClass.simpleName)
                } finally {
                    latch.countDown()
                }
            } ?: latch.countDown()
        }
        latch.await(5, TimeUnit.SECONDS)
        logDiagnostic("train_hermes_wake_runtime_probe", result)
        return result
    }

    private fun mapRendererDiagnosticToOAuthStage(eventName: String, payload: JSONObject = JSONObject()) {
        val normalized = eventName.lowercase()
        when {
            normalized.contains("login_clicked") || normalized.contains("google_login_start_requested") ->
                transitionOAuth("AUTH_START_TAPPED", eventName, payload)
            normalized.contains("session_created") || normalized.contains("auth_session_created") ->
                transitionOAuth("AUTH_SESSION_CREATED", eventName, payload)
            normalized.contains("external_browser_opened") || normalized.contains("oauth_start") ->
                transitionOAuth("EXTERNAL_BROWSER_OPENED", eventName, payload)
            normalized.contains("native_return") ->
                transitionOAuth("NATIVE_RETURN_PAGE_OBSERVED", eventName, payload)
            normalized.contains("poll") ->
                transitionOAuth("AUTH_POLLING", eventName, payload)
            normalized.contains("cookie_flush") ->
                transitionOAuth("COOKIE_FLUSHED", eventName, payload)
            normalized.contains("webview_reload") ->
                transitionOAuth("WEBVIEW_RELOADED", eventName, payload)
            normalized.contains("authenticated_ui_visible") || normalized.contains("authenticated_app_ready") ->
                transitionOAuth("AUTHENTICATED_UI_SEEN", eventName, payload)
            normalized.contains("expired") ->
                transitionOAuth("AUTH_EXPIRED", eventName, payload)
            normalized.contains("cancel") ->
                transitionOAuth("AUTH_CANCELED", eventName, payload)
            normalized.contains("error") || normalized.contains("failed") ->
                transitionOAuth("AUTH_ERROR", eventName, payload)
            normalized.contains("reset") ->
                transitionOAuth("IDLE", eventName, payload)
        }
    }

    private fun rememberRendererReadiness(eventName: String, payload: JSONObject = JSONObject()) {
        val normalized = eventName.lowercase()
        if (
            normalized.contains("first_screen_readiness") ||
            normalized.contains("login_screen_visible") ||
            normalized.contains("google_signin_button_visible") ||
            payload.optBoolean("login_screen_visible", false) ||
            payload.optBoolean("google_signin_button_visible", false)
        ) {
            augmentRendererGoogleTapTarget(payload)
            lastRendererReadiness = JSONObject()
                .put("event_name", eventName)
                .put("timestamp", System.currentTimeMillis())
                .put("payload", payload)
        }
    }

    private fun webViewMetrics(): JSONObject {
        val metrics = JSONObject()
        val collect = {
            val view = webView
            val location = IntArray(2)
            if (view != null) {
                try {
                    view.getLocationOnScreen(location)
                } catch (_: Exception) {
                    location[0] = 0
                    location[1] = 0
                }
            }
            val display = resources.displayMetrics
            metrics
                .put("screen_x_px", location[0])
                .put("screen_y_px", location[1])
                .put("width_px", view?.width ?: 0)
                .put("height_px", view?.height ?: 0)
                .put("container_width_px", container.width)
                .put("container_height_px", container.height)
                .put("density", display.density)
                .put("density_dpi", display.densityDpi)
                .put("display_width_px", display.widthPixels)
                .put("display_height_px", display.heightPixels)
                .put("boot", webViewBootMetrics())
        }
        if (Looper.myLooper() == Looper.getMainLooper()) {
            collect()
        } else {
            val latch = CountDownLatch(1)
            runOnUiThread {
                try {
                    collect()
                } finally {
                    latch.countDown()
                }
            }
            latch.await(750, TimeUnit.MILLISECONDS)
        }
        return metrics
    }

    private fun augmentRendererGoogleTapTarget(payload: JSONObject) {
        val target = payload.optJSONObject("google_signin_tap_target") ?: return
        val rect = target.optJSONObject("rect") ?: return
        val viewport = target.optJSONObject("viewport") ?: JSONObject()
        val centerX = rect.optDouble("center_x", Double.NaN)
        val centerY = rect.optDouble("center_y", Double.NaN)
        val innerWidth = viewport.optDouble("inner_width", 0.0)
        val innerHeight = viewport.optDouble("inner_height", 0.0)
        val metrics = webViewMetrics()
        target.put("native_webview_metrics", metrics)
        val widthPx = metrics.optDouble("width_px", 0.0)
        val heightPx = metrics.optDouble("height_px", 0.0)
        if (!centerX.isFinite() || !centerY.isFinite() || innerWidth <= 0.0 || innerHeight <= 0.0 || widthPx <= 0.0 || heightPx <= 0.0) {
            return
        }
        val tapX = (metrics.optDouble("screen_x_px", 0.0) + (centerX / innerWidth) * widthPx).roundToInt()
        val tapY = (metrics.optDouble("screen_y_px", 0.0) + (centerY / innerHeight) * heightPx).roundToInt()
        target.put("adb_tap_target", JSONObject()
            .put("x", tapX.coerceIn(0, metrics.optInt("display_width_px", tapX).coerceAtLeast(tapX)))
            .put("y", tapY.coerceIn(0, metrics.optInt("display_height_px", tapY).coerceAtLeast(tapY)))
            .put("source", "renderer_readiness_google_signin_tap_target"))
    }

    private fun transitionOAuth(stage: String, result: String = "", payload: JSONObject = JSONObject()) {
        oauthStage = stage
        oauthResult = result
        logDiagnostic("oauth_state_transition", JSONObject()
            .put("stage", stage)
            .put("result", result)
            .put("details", payload))
    }

    private fun rememberException(kind: String, error: Exception) {
        lastExceptionSummary = JSONObject()
            .put("kind", kind)
            .put("class", error.javaClass.simpleName)
            .put("message", error.message.orEmpty().take(500))
    }

    private fun logDiagnostic(kind: String, payload: JSONObject = JSONObject()) {
        if (kind.contains("error", ignoreCase = true) ||
            kind.contains("failed", ignoreCase = true) ||
            kind.contains("exception", ignoreCase = true)) {
            lastExceptionSummary = JSONObject()
                .put("kind", kind)
                .put("error", payload.optString("error", ""))
                .put("message", payload.optString("message", "").take(500))
        }
        val enriched = JSONObject()
            .put("kind", kind)
            .put("timestamp", System.currentTimeMillis())
            .put("platform", "android")
            .put("shell", "android-webview")
            .put("build_id", BuildConfig.NATIVE_BUILD_ID)
            .put("native_correlation_id", nativeCorrelationId)
            .put("android_auth_session", androidAuthSessionId)
            .put("install_device_hash", installDeviceHash)
            .put("selected_origin", selectedOrigin)
            .put("url", latestWebViewUrl)
            .put("android_auth_session_persisted", androidAuthSessionId.isNotBlank())
            .put("oauth_stage", oauthStage)
            .put("oauth_result", oauthResult)
            .put("payload", payload)
        diagnostics.remember(kind, enriched)
        Log.i(LOG_TAG, "${kind} ${NativeDiagnostics.safeJsonString(payload).take(3000)}")
        scheduleDiagnosticsSnapshot(kind)
    }

    private fun diagnosticsUploadImportant(kind: String): Boolean {
        return kind.contains("auth", ignoreCase = true) ||
            kind.contains("intent", ignoreCase = true) ||
            kind.contains("return", ignoreCase = true) ||
            kind.contains("app_ready", ignoreCase = true) ||
            kind.contains("voice_wake", ignoreCase = true) ||
            kind.contains("error", ignoreCase = true) ||
            kind.contains("failed", ignoreCase = true)
    }

    private fun scheduleDiagnosticsSnapshot(kind: String) {
        val important = diagnosticsUploadImportant(kind)
        var shouldStartWorker = false
        synchronized(diagnosticsSnapshotLock) {
            diagnosticsSnapshotReason = kind
            if (important) diagnosticsUploadReason = kind
            diagnosticsSnapshotPending = true
            if (!diagnosticsSnapshotScheduled) {
                val deferRoutineSnapshot = !important &&
                    (firstLoadUrlAt == 0L || webViewPageCommitVisibleAt == 0L)
                if (!deferRoutineSnapshot) {
                    diagnosticsSnapshotScheduled = true
                    shouldStartWorker = true
                }
            }
        }
        if (!shouldStartWorker) return
        thread(name = "wasm-agent-native-diagnostics-snapshot") {
            while (true) {
                Thread.sleep(450L)
                val reason: String
                val uploadReason: String
                synchronized(diagnosticsSnapshotLock) {
                    reason = diagnosticsSnapshotReason.ifBlank { kind }
                    uploadReason = diagnosticsUploadReason
                    diagnosticsUploadReason = ""
                    diagnosticsSnapshotPending = false
                }
                try {
                    diagnostics.writeSnapshot(reason, diagnosticsSnapshot())
                    if (webViewPageCommitVisibleAt == 0L) {
                        nativeDiagnosticsWritesDuringBoot += 1
                    }
                    if (uploadReason.isNotBlank()) maybeUploadNativeDiagnostics(uploadReason)
                } catch (_: Exception) {
                    // Diagnostics are best-effort and must never block app input.
                }
                val shouldContinue = synchronized(diagnosticsSnapshotLock) {
                    if (diagnosticsSnapshotPending) {
                        true
                    } else {
                        diagnosticsSnapshotScheduled = false
                        false
                    }
                }
                if (!shouldContinue) break
            }
        }
    }

    private fun diagnosticsSnapshot(): JSONObject {
        val webViewPackage = try {
            WebView.getCurrentWebViewPackage()
        } catch (_: Exception) {
            null
        }
        val appPackage = try {
            packageManager.getPackageInfo(packageName, 0)
        } catch (_: Exception) {
            null
        }
        val versionCode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            appPackage?.longVersionCode ?: 0L
        } else {
            @Suppress("DEPRECATION")
            appPackage?.versionCode?.toLong() ?: 0L
        }
        return JSONObject()
            .put("build", JSONObject()
                .put("build_id", BuildConfig.NATIVE_BUILD_ID)
                .put("build_generated_at", BuildConfig.BUILD_GENERATED_AT)
                .put("allow_local_dev", BuildConfig.ALLOW_LOCAL_DEV)
                .put("default_server_url", BuildConfig.DEFAULT_SERVER_URL))
            .put("package", JSONObject()
                .put("name", packageName)
                .put("version_name", appPackage?.versionName.orEmpty())
                .put("version_code", versionCode))
            .put("device", JSONObject()
                .put("manufacturer", Build.MANUFACTURER.orEmpty())
                .put("brand", Build.BRAND.orEmpty())
                .put("model", Build.MODEL.orEmpty())
                .put("device", Build.DEVICE.orEmpty())
                .put("install_device_hash", installDeviceHash))
            .put("android", JSONObject()
                .put("sdk_int", Build.VERSION.SDK_INT)
                .put("release", Build.VERSION.RELEASE.orEmpty()))
            .put("webview", JSONObject()
                .put("package_name", webViewPackage?.packageName.orEmpty())
                .put("version_name", webViewPackage?.versionName.orEmpty())
                .put("current_url", latestWebViewUrl)
                .put("selected_origin", selectedOrigin)
                .put("page_started", webViewPageStartedAt > 0)
                .put("page_started_at", webViewPageStartedAt)
                .put("page_commit_visible", webViewPageCommitVisibleAt > 0)
                .put("page_commit_visible_at", webViewPageCommitVisibleAt)
                .put("page_finished", webViewPageFinishedAt > 0)
                .put("page_finished_at", webViewPageFinishedAt)
                .put("alpha", webView?.alpha ?: 0f)
                .put("splash_visible", splashView?.visibility == View.VISIBLE)
                .put("error_visible", errorView?.visibility == View.VISIBLE)
                .put("main_frame_error", webViewMainFrameError ?: JSONObject.NULL)
                .put("metrics", webViewMetrics())
                .put("renderer_readiness", lastRendererReadiness ?: JSONObject.NULL))
            .put("current_webview_url", latestWebViewUrl)
            .put("selected_origin", selectedOrigin)
            .put("last_intent", lastIntentSummary ?: JSONObject.NULL)
            .put("last_deep_link", lastDeepLinkSummary ?: JSONObject.NULL)
            .put("android_auth_session", androidAuthSessionId)
            .put("native_correlation_id", nativeCorrelationId)
            .put("nativeKernel", nativeKernelStatus())
            .put("downloadedRuntime", activeDownloadedRuntimeStatus())
            .put("hotOperations", activeHotOpStatus())
            .put("false_wake_buffer", FalseWakeStore.diagnostics(this))
            .put("safe_cookie_session_summary", safeCookieSummary())
            .put("oauth", JSONObject()
                .put("stage", oauthStage)
                .put("result", oauthResult))
            .put("voice_wake", voiceWakeStatusLightweight())
            .put("voice_tuning", voiceTuningStatus())
            .put("last_exception", lastExceptionSummary ?: JSONObject.NULL)
    }

    private fun voiceTuningStatus(): JSONObject {
        val wakeStatus = voiceWakeStatusLightweight()
        val modelStatus = when {
            wakeStatus.optBoolean("wake_engine_ready", false) -> "validated_model"
            wakeStatus.optJSONObject("wake_model")?.optBoolean("wake_model_exists", false) == true -> "candidate_model"
            else -> "no_model"
        }
        val nextAction = "Export uploads the dataset to wasm-agent, then train/verify hermes.onnx and install it with installHermesWakeModel('/native/android/hermes-wake-model/latest', sha256). APK rebuild is not required for model iteration."
        return voiceTuningStore.status(modelStatus = modelStatus, nextAction = nextAction)
            .put("bridge_name", NativeBridgeContract.VOICE_TUNING_BRIDGE_OBJECT)
            .put("bridge_ready", true)
            .put("bridge_connected", true)
            .put("bridge_build_id", BuildConfig.NATIVE_BUILD_ID)
            .put("bridge_methods", JSONArray(NativeBridgeContract.voiceTuningMethods))
            .put("direct_dataset_upload", true)
            .put("direct_model_install", true)
            .put("model_install_path", "files/voice/hermes.onnx")
            .put("bridge_status", if (permissionGranted(Manifest.permission.RECORD_AUDIO)) "connected_ready" else "connected_recording_disabled")
            .put("recording_active", voiceTuningRecorder.isRecording())
            .put("permission_record_audio", permissionGranted(Manifest.permission.RECORD_AUDIO))
            .put("permission_state", JSONObject()
                .put("record_audio", if (permissionGranted(Manifest.permission.RECORD_AUDIO)) "granted" else "missing"))
            .put("recording_supported", permissionGranted(Manifest.permission.RECORD_AUDIO))
            .put("always_on_wake_service_started", false)
            .put("wake_service_enabled", prefs.getBoolean(HermesVoiceWakeService.PREF_ENABLED, false))
            .put("message", if (permissionGranted(Manifest.permission.RECORD_AUDIO)) {
                "Android bridge connected. Samples can be recorded manually."
            } else {
                "Android bridge connected. Recording not enabled yet."
            })
    }

    private fun voiceTuningBridgeBuildInfo(): JSONObject {
        return JSONObject()
            .put("bridge_name", NativeBridgeContract.VOICE_TUNING_BRIDGE_OBJECT)
            .put("bridge_build_id", BuildConfig.NATIVE_BUILD_ID)
            .put("apk_build_id", BuildConfig.NATIVE_BUILD_ID)
            .put("build_generated_at", BuildConfig.BUILD_GENERATED_AT)
            .put("package_name", packageName)
            .put("bridge_methods", JSONArray(NativeBridgeContract.voiceTuningMethods))
            .put("direct_dataset_upload", true)
            .put("direct_model_install", true)
            .put("model_install_path", "files/voice/hermes.onnx")
    }

    private fun voiceTuningBridgeDiagnostics(): JSONObject {
        return voiceTuningStatus()
            .put("build", voiceTuningBridgeBuildInfo())
            .put("bridge_present", true)
    }

    private fun nativeDeviceLabel(): String {
        val manufacturer = Build.MANUFACTURER.orEmpty().trim()
        val model = Build.MODEL.orEmpty().trim()
        return listOf(manufacturer, model)
            .filter { it.isNotBlank() }
            .distinctBy { it.lowercase() }
            .joinToString(" ")
            .ifBlank { "Android device" }
            .take(120)
    }

    private fun voiceWakeStatusLightweight(): JSONObject {
        reconcileStaleVoiceWakeStatus("lightweight_status")
        val enabled = prefs.getBoolean(HermesVoiceWakeService.PREF_ENABLED, false)
        val personalizedModelFile = File(filesDir, "voice/hermes.onnx")
        val baseModelFile = File(filesDir, "voice/base_hermes.onnx")
        val openWakeWordBundleDir = File(filesDir, "voice/openwakeword")
        val personalizedModelExists = personalizedModelFile.exists() && personalizedModelFile.isFile && personalizedModelFile.length() > 0L
        val baseModelExists = baseModelFile.exists() && baseModelFile.isFile && baseModelFile.length() > 0L
        val openWakeWordBundleExists = openWakeWordBundleExists(openWakeWordBundleDir)
        val falseWakeDiagnostics = FalseWakeStore.diagnostics(this)
        val base = try {
            val file = HermesVoiceWakeService.statusFile(this)
            if (file.exists()) JSONObject(file.readText()) else JSONObject()
        } catch (_: Exception) {
            JSONObject()
        }
        if (!base.has("schema")) base.put("schema", "hermes.wasm_agent.android_voice_wake.v1")
        if (!base.has("visible_state")) {
            val fallbackState = base.optString("state", if (enabled) "enabled" else "disabled")
            base.put("visible_state", when (fallbackState) {
                "listening" -> "Listening for Hermes"
                "capturing" -> "Capturing"
                "transcribing" -> "Transcribing"
                "sent" -> "Sent"
                "error" -> "Error"
                "enabled" -> "Enabled"
                else -> "Disabled"
            })
        }
        val selectedModelPath = when {
            openWakeWordBundleExists -> OpenWakeWordBundleEngine.BUNDLE_DIR
            personalizedModelExists -> "files/voice/hermes.onnx"
            baseModelExists -> "files/voice/base_hermes.onnx"
            else -> "files/voice/hermes.onnx"
        }
        val wakeModelExists = openWakeWordBundleExists || personalizedModelExists || baseModelExists
        val personalizedModelSha = sha256FileOrBlank(personalizedModelFile)
        val baseModelSha = sha256FileOrBlank(baseModelFile)
        val modelSha = when (selectedModelPath) {
            "files/voice/base_hermes.onnx" -> baseModelSha
            OpenWakeWordBundleEngine.BUNDLE_DIR -> ""
            else -> personalizedModelSha
        }
        val modelShaMatch = modelSha.equals(HERMES_WAKE_ACCEPTANCE_MODEL_SHA256, ignoreCase = true)
        val liveStatusMissing = !base.has("wake_engine_ready")
        val wakeThreshold = HermesVoiceWakeService.configuredWakeThreshold(this)
        val thresholdPolicySource = normalizedThresholdPolicySource()
        val computedDisabledReason = when {
            !permissionGranted(Manifest.permission.RECORD_AUDIO) -> "record_audio_permission_missing"
            !enabled -> "voice_wake_disabled"
            liveStatusMissing -> "live_service_status_unavailable"
            !base.optBoolean("onnx_runtime_available", false) -> "onnx_runtime_unavailable"
            !wakeModelExists -> "wake_model_missing"
            !base.optBoolean("wake_engine_ready", false) -> "wake_engine_not_ready"
            else -> ""
        }
        val staleDisabledReason = base.optString("disabled_reason", "")
        val disabledReason = if (
            staleDisabledReason in setOf("personalized_model_path_mismatch", "personalized_model_missing", "model_sha_mismatch")
            && computedDisabledReason.isBlank()
        ) "" else staleDisabledReason.ifBlank { computedDisabledReason }
        return base
            .put("enabled", enabled)
            .put("disabled_reason", disabledReason)
            .put("wake_word", HermesVoiceWakeService.configuredWakePhrase(this))
            .put("permission_record_audio", permissionGranted(Manifest.permission.RECORD_AUDIO))
            .put("permission_post_notifications", if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) permissionGranted(Manifest.permission.POST_NOTIFICATIONS) else true)
            .put("wake_engine", base.optString("wake_engine", "deferred_until_voice_wake_enabled"))
            .put("wake_engine_ready", base.optBoolean("wake_engine_ready", false))
            .put("wake_engine_state", base.optString("wake_engine_state", if (wakeModelExists) "model_diagnostics_deferred" else "hermes_wake_model_missing"))
            .put("model_source", base.optString("model_source", if (personalizedModelExists) "personalized" else if (baseModelExists) "base" else "none"))
            .put("wake_model_path", base.optString("wake_model_path", selectedModelPath))
            .put("selected_model_path", base.optString("selected_model_path", selectedModelPath))
            .put("asset_model_path", "assets/voice/base_hermes.onnx")
            .put("base_model_exists", base.optBoolean("base_model_exists", baseModelExists))
            .put("personalized_model_exists", base.optBoolean("personalized_model_exists", personalizedModelExists))
            .put("openwakeword_bundle_exists", base.optBoolean("openwakeword_bundle_exists", openWakeWordBundleExists))
            .put("wake_model_exists", base.optBoolean("wake_model_exists", wakeModelExists))
            .put("model_path", base.optString("model_path", selectedModelPath))
            .put("model_exists", base.optBoolean("model_exists", wakeModelExists))
            .put("model_sha", base.optString("model_sha", modelSha))
            .put("model_sha256", base.optString("model_sha256", modelSha))
            .put("personalized_model_sha256", base.optString("personalized_model_sha256", personalizedModelSha))
            .put("base_model_sha256", base.optString("base_model_sha256", baseModelSha))
            .put("expected_model_sha256", HERMES_WAKE_ACCEPTANCE_MODEL_SHA256)
            .put("model_sha_match", base.optBoolean("model_sha_match", modelShaMatch))
            .put("acceptance_model_sha256_match", base.optBoolean("acceptance_model_sha256_match", modelShaMatch))
            .put("wake_threshold", base.optDouble("wake_threshold", wakeThreshold))
            .put("threshold", base.optDouble("threshold", wakeThreshold))
            .put("proof_threshold_override", base.opt("proof_threshold_override") ?: JSONObject.NULL)
            .put("effective_wake_threshold", base.optDouble("effective_wake_threshold", wakeThreshold))
            .put("threshold_margin", base.optDouble("threshold_margin", base.optDouble("max_observed_confidence", 0.0) - base.optDouble("threshold", wakeThreshold)))
            .put("threshold_policy_source", base.optString("threshold_policy_source", thresholdPolicySource))
            .put("policy_source", base.optString("policy_source", thresholdPolicySource))
            .put("model_asset_found", hermesWakeModelAssetFound())
            .put("onnx_runtime_available", base.optBoolean("onnx_runtime_available", false))
            .put("foreground_service_started", base.optBoolean("foreground_service_started", false))
            .put("audio_record_permission_granted", base.optBoolean("audio_record_permission_granted", permissionGranted(Manifest.permission.RECORD_AUDIO)))
            .put("audio_record_initialized", base.optBoolean("audio_record_initialized", false))
            .put("audio_record_start_called", base.optBoolean("audio_record_start_called", false))
            .put("audio_record_read_count", base.optLong("audio_record_read_count", base.optLong("audio_read_calls", 0L)))
            .put("audio_record_last_error", base.optString("audio_record_last_error", base.optString("audio_record_error", "")))
            .put("inference_count", base.optLong("inference_count", 0L))
            .put("last_confidence", base.optDouble("last_confidence", base.optDouble("last_wake_confidence", 0.0)))
            .put("wake_detected", base.optBoolean("wake_detected", base.optLong("wake_detection_count", 0L) > 0L || base.optBoolean("wake_detected_event_emitted", false)))
            .put("onnx_runtime_error", base.optString("onnx_runtime_error", if (liveStatusMissing) "live service has not reported ONNX Runtime readiness" else ""))
            .put("wake_engine_error", base.optString("wake_engine_error", if (liveStatusMissing) "live service has not reported WakeEngine readiness" else ""))
            .put("wake_model", JSONObject()
                .put("wake_model_exists", base.optBoolean("wake_model_exists", wakeModelExists))
                .put("base_model_exists", base.optBoolean("base_model_exists", baseModelExists))
                .put("personalized_model_exists", base.optBoolean("personalized_model_exists", personalizedModelExists))
                .put("openwakeword_bundle_exists", base.optBoolean("openwakeword_bundle_exists", openWakeWordBundleExists))
                .put("diagnostics_deferred", true))
            .put("foreground_service_required", true)
            .put("foreground_notification", "WASM Agent listening for Hermes")
            .put("source", "android_native_voice_wake_lightweight")
            .put("status_source", "lightweight_no_model_load")
            .put("model_diagnostics_deferred", true)
            .put("build_id", BuildConfig.NATIVE_BUILD_ID)
            .put("origin", prefs.getString(HermesVoiceWakeService.PREF_ORIGIN, selectedOrigin).orEmpty())
            .put("audio_retained", false)
            .put("continuous_audio_uploaded", false)
            .put("false_wake_buffer_count", falseWakeDiagnostics.optInt("false_wake_buffer_count", 0))
            .put("false_wake_buffer_max", FalseWakeStore.MAX_SAMPLES)
            .put("false_wake_storage_bytes", falseWakeDiagnostics.optLong("false_wake_storage_bytes", 0L))
    }

    private fun reconcileStaleVoiceWakeStatus(source: String): JSONObject {
        val file = HermesVoiceWakeService.statusFile(this)
        if (!file.exists()) {
            return JSONObject().put("ok", true).put("status", "voice_wake_status_missing")
        }
        return try {
            val status = JSONObject(file.readText())
            val state = status.optString("state", "")
            val commandCaptureStarted = status.optBoolean("command_capture_started", false)
            val diagnosticsStartedAt = status
                .optJSONObject("last_asr_diagnostics")
                ?.optLong("started_at", 0L) ?: 0L
            val commandCaptureStartedAt = listOf(
                status.optLong("command_capture_started_at", 0L),
                diagnosticsStartedAt,
            ).filter { it > 0L }.minOrNull() ?: 0L
            val staleCandidate = state == "transcribing" ||
                state == "capturing" ||
                status.optString("listener_mode", "") == "command_capture" ||
                status.optBoolean("command_capture_active", false) ||
                commandCaptureStarted ||
                status.optString("last_transcript_status", "") == "capturing" ||
                status.optString("last_transcript_result", "") == "transcript_attempt_started"
            if (!staleCandidate || commandCaptureStartedAt <= 0L) {
                return JSONObject()
                    .put("ok", true)
                    .put("status", "voice_wake_status_current")
                    .put("state", state)
            }
            val timeoutMs = HermesVoiceWakeService.configuredTranscriptTimeoutMs(this)
            val elapsedMs = System.currentTimeMillis() - commandCaptureStartedAt
            if (elapsedMs < timeoutMs + 2_500L) {
                return JSONObject()
                    .put("ok", true)
                    .put("status", "voice_wake_capture_still_fresh")
                    .put("state", state)
                    .put("elapsed_ms", elapsedMs)
                    .put("timeout_ms", timeoutMs)
            }
            val result = if (source == "boot") {
                "transcript_boot_reconciled_timeout"
            } else {
                "transcript_status_reconciled_timeout"
            }
            val diagnostics = JSONObject()
                .put("schema", "hermes.wasm_agent.transcript_reconciled_timeout.v1")
                .put("elapsed_ms", elapsedMs)
                .put("timeout_ms", timeoutMs)
                .put("previous_state", state)
                .put("previous_listener_mode", status.optString("listener_mode", ""))
                .put("previous_command_capture_active", status.optBoolean("command_capture_active", false))
                .put("previous_command_capture_started_at", status.optLong("command_capture_started_at", 0L))
                .put("previous_diagnostics_started_at", diagnosticsStartedAt)
                .put("previous_last_transcript_result", status.optString("last_transcript_result", ""))
                .put("previous_last_transcript_status", status.optString("last_transcript_status", ""))
                .put("source", source)
                .put("reconciled_at", System.currentTimeMillis())
            status
                .put("state", "listening")
                .put("listener_mode", "standby")
                .put("visible_state", "Listening for Hermes")
                .put("last_transcript_result", result)
                .put("last_transcript_status", "failed")
                .put("last_asr_latency_ms", elapsedMs)
                .put("last_asr_audio_captured_ms", 0L)
                .put("last_asr_partial_transcript", "")
                .put("last_asr_diagnostics", diagnostics)
                .put("last_exception", result)
                .put("command_capture_active", false)
                .put("command_capture_started", false)
                .put("command_capture_started_at", 0L)
                .put("voice_command_event_dispatched", false)
                .put("voice_command_event_dispatched_at", 0L)
                .put("reason", result)
                .put("status_source", "main_activity_${source}_reconciler")
            file.parentFile?.mkdirs()
            file.writeText("${NativeDiagnostics.safeJsonString(status, 2)}\n")
            JSONObject()
                .put("ok", true)
                .put("status", result)
                .put("elapsed_ms", elapsedMs)
                .put("timeout_ms", timeoutMs)
                .put("previous_state", state)
        } catch (error: Exception) {
            JSONObject()
                .put("ok", false)
                .put("status", "voice_wake_reconciliation_failed")
                .put("source", source)
                .put("error", error.javaClass.name)
        }
    }

    private fun voiceWakeStatus(): JSONObject {
        reconcileStaleVoiceWakeStatus("full_status")
        val enabled = prefs.getBoolean(HermesVoiceWakeService.PREF_ENABLED, false)
        val wakeThreshold = HermesVoiceWakeService.configuredWakeThreshold(this)
        val thresholdPolicySource = normalizedThresholdPolicySource()
        val wakeSelection = WakeModelSelector.select(
            File(filesDir, "voice/hermes.onnx"),
            File(filesDir, "voice/base_hermes.onnx"),
            wakeThreshold,
        )
        val wakeEngine = wakeSelection.engine
        val wakeDiagnostics = wakeEngine.diagnostics()
        val base = try {
            val file = HermesVoiceWakeService.statusFile(this)
            if (file.exists()) JSONObject(file.readText()) else JSONObject()
        } catch (_: Exception) {
            JSONObject()
        }
        if (!base.has("schema")) base.put("schema", "hermes.wasm_agent.android_voice_wake.v1")
        if (!base.has("visible_state")) {
            val fallbackState = base.optString("state", if (enabled) "listening" else "disabled")
            base.put("visible_state", when (fallbackState) {
                "listening" -> "Listening for Hermes"
                "capturing" -> "Capturing"
                "transcribing" -> "Transcribing"
                "sent" -> "Sent"
                "error" -> "Error"
                else -> "Disabled"
            })
        }
        val modelPath = base.optString("selected_model_path", wakeDiagnostics.getString("selected_model_path"))
        val modelExists = base.optBoolean("wake_model_exists", wakeDiagnostics.getBoolean("wake_model_exists"))
        val personalizedModelSha = sha256FileOrBlank(File(filesDir, "voice/hermes.onnx"))
        val baseModelSha = sha256FileOrBlank(File(filesDir, "voice/base_hermes.onnx"))
        val modelSha = when (modelPath) {
            "files/voice/base_hermes.onnx" -> baseModelSha
            OpenWakeWordBundleEngine.BUNDLE_DIR -> ""
            else -> personalizedModelSha
        }
        val modelShaMatch = modelSha.equals(HERMES_WAKE_ACCEPTANCE_MODEL_SHA256, ignoreCase = true)
        val computedDisabledReason = when {
            !permissionGranted(Manifest.permission.RECORD_AUDIO) -> "record_audio_permission_missing"
            !enabled -> "voice_wake_disabled"
            !wakeDiagnostics.optBoolean("onnx_runtime_available", false) -> "onnx_runtime_unavailable"
            !modelExists -> "wake_model_missing"
            !base.optBoolean("wake_engine_ready", wakeEngine.ready) -> "wake_engine_not_ready"
            base.optLong("audio_record_started_at", 0L) <= 0L -> "audio_record_not_started"
            base.optLong("inference_count", 0L) <= 0L -> "inference_not_observed"
            else -> ""
        }
        val staleDisabledReason = base.optString("disabled_reason", "")
        val disabledReason = if (
            staleDisabledReason in setOf("personalized_model_path_mismatch", "personalized_model_missing", "model_sha_mismatch")
            && computedDisabledReason.isBlank()
        ) "" else staleDisabledReason.ifBlank { computedDisabledReason }
        return base
            .put("enabled", enabled)
            .put("disabled_reason", disabledReason)
            .put("service_alive", base.optBoolean("service_alive", false))
            .put("wake_word", HermesVoiceWakeService.configuredWakePhrase(this))
            .put("permission_record_audio", permissionGranted(Manifest.permission.RECORD_AUDIO))
            .put("permission_foreground_service", hasManifestPermission(Manifest.permission.FOREGROUND_SERVICE))
            .put("permission_foreground_service_microphone", if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) hasManifestPermission(Manifest.permission.FOREGROUND_SERVICE_MICROPHONE) else true)
            .put("permission_post_notifications", if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) permissionGranted(Manifest.permission.POST_NOTIFICATIONS) else true)
            .put("wake_engine", base.optString("wake_engine", wakeEngine.name))
            .put("wake_engine_ready", if (base.has("wake_engine_ready")) base.optBoolean("wake_engine_ready") else wakeEngine.ready)
            .put("wake_engine_state", if (base.optBoolean("wake_engine_ready", wakeEngine.ready)) "ready" else wakeEngine.diagnosticReason)
            .put("model_source", base.optString("model_source", wakeSelection.source))
            .put("wake_model_path", base.optString("wake_model_path", wakeDiagnostics.getString("wake_model_path")))
            .put("model_path", modelPath)
            .put("selected_model_path", modelPath)
            .put("asset_model_path", "assets/voice/base_hermes.onnx")
            .put("base_model_exists", base.optBoolean("base_model_exists", wakeSelection.baseModelExists))
            .put("personalized_model_exists", base.optBoolean("personalized_model_exists", wakeSelection.personalizedModelExists))
            .put("openwakeword_bundle_exists", base.optBoolean("openwakeword_bundle_exists", wakeSelection.openWakeWordBundleExists))
            .put("model_exists", modelExists)
            .put("wake_model_exists", modelExists)
            .put("model_sha", base.optString("model_sha", modelSha))
            .put("model_sha256", base.optString("model_sha256", modelSha))
            .put("personalized_model_sha256", base.optString("personalized_model_sha256", personalizedModelSha))
            .put("base_model_sha256", base.optString("base_model_sha256", baseModelSha))
            .put("expected_model_sha256", HERMES_WAKE_ACCEPTANCE_MODEL_SHA256)
            .put("wake_threshold", base.optDouble("wake_threshold", wakeThreshold))
            .put("threshold", base.optDouble("threshold", wakeThreshold))
            .put("proof_threshold_override", base.opt("proof_threshold_override") ?: JSONObject.NULL)
            .put("effective_wake_threshold", base.optDouble("effective_wake_threshold", wakeThreshold))
            .put("threshold_margin", base.optDouble("threshold_margin", base.optDouble("max_observed_confidence", 0.0) - base.optDouble("threshold", wakeThreshold)))
            .put("threshold_policy_source", base.optString("threshold_policy_source", thresholdPolicySource))
            .put("policy_source", base.optString("policy_source", thresholdPolicySource))
            .put("foreground_service_started", base.optBoolean("foreground_service_started", base.optBoolean("foreground_service_running", false)))
            .put("proof_session_active", base.optBoolean("proof_session_active", false))
            .put("audio_record_permission_granted", base.optBoolean("audio_record_permission_granted", permissionGranted(Manifest.permission.RECORD_AUDIO)))
            .put("audio_record_initialized", base.optBoolean("audio_record_initialized", false))
            .put("audio_record_start_called", base.optBoolean("audio_record_start_called", false))
            .put("audio_record_started", base.optBoolean("audio_record_started", false))
            .put("audio_capture_alive", base.optBoolean("audio_capture_alive", base.optBoolean("audio_record_active", false)))
            .put("audio_record_read_count", base.optLong("audio_record_read_count", base.optLong("audio_read_calls", 0L)))
            .put("audio_record_last_error", base.optString("audio_record_last_error", base.optString("audio_record_error", "")))
            .put("onnx_model_ready", base.optBoolean("onnx_model_ready", false))
            .put("inference_running", base.optBoolean("inference_running", base.optLong("inference_count", 0L) > 0L))
            .put("inference_count", base.optLong("inference_count", 0L))
            .put("last_confidence", base.optDouble("last_confidence", base.optDouble("last_wake_confidence", 0.0)))
            .put("wake_detected", base.optBoolean("wake_detected", base.optLong("wake_detection_count", 0L) > 0L || base.optBoolean("wake_detected_event_emitted", false)))
            .put("failure_reason", base.optString("failure_reason", disabledReason))
            .put("last_exception", base.opt("last_exception") ?: JSONObject.NULL)
            .put("status_source", base.optString("status_source", if (base.has("wake_engine_ready")) "live_service" else "activity_fallback"))
            .put("model_sha_match", base.optBoolean("model_sha_match", modelShaMatch))
            .put("acceptance_model_sha256_match", base.optBoolean("acceptance_model_sha256_match", modelShaMatch))
            .put("model_asset_found", hermesWakeModelAssetFound())
            .put("onnx_runtime_available", wakeDiagnostics.getBoolean("onnx_runtime_available"))
            .put("onnx_runtime_error", wakeDiagnostics.getString("onnx_runtime_error"))
            .put("wake_engine_error", wakeDiagnostics.getString("wake_engine_error"))
            .put("wake_model", wakeDiagnostics
                .put("base_model_exists", wakeSelection.baseModelExists)
                .put("personalized_model_exists", wakeSelection.personalizedModelExists)
                .put("openwakeword_bundle_exists", wakeSelection.openWakeWordBundleExists))
            .put("foreground_service_required", true)
            .put("foreground_notification", "WASM Agent listening for Hermes")
            .put("source", "android_native_voice_wake")
            .put("build_id", BuildConfig.NATIVE_BUILD_ID)
            .put("origin", prefs.getString(HermesVoiceWakeService.PREF_ORIGIN, selectedOrigin).orEmpty())
            .put("audio_retained", false)
            .put("continuous_audio_uploaded", false)
            .put("false_wake_buffer_count", FalseWakeStore.diagnostics(this).optInt("false_wake_buffer_count", 0))
            .put("false_wake_buffer_max", FalseWakeStore.MAX_SAMPLES)
            .put("false_wake_last_uploaded_at", FalseWakeStore.diagnostics(this).optLong("false_wake_last_uploaded_at", 0L))
            .put("false_wake_last_deleted_count", FalseWakeStore.diagnostics(this).optInt("false_wake_last_deleted_count", 0))
            .put("false_wake_storage_bytes", FalseWakeStore.diagnostics(this).optLong("false_wake_storage_bytes", 0L))
    }

    private fun wakeWordState(): JSONObject {
        val voice = voiceWakeStatusLightweight()
        val recentEvents = voice.optJSONArray("recent_events") ?: JSONArray()
        val permissionState = voice.optJSONObject("permission_state") ?: JSONObject()
            .put("record_audio", if (permissionGranted(Manifest.permission.RECORD_AUDIO)) "granted" else "missing")
            .put("post_notifications", if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && !permissionGranted(Manifest.permission.POST_NOTIFICATIONS)) "missing" else "granted")
        return JSONObject()
            .put("schema", "hermes.wasm_agent.android_wake_word_state.v1")
            .put("ok", true)
            .put("build_id", BuildConfig.NATIVE_BUILD_ID)
            .put("app_version", packageManager.getPackageInfo(packageName, 0).versionName.orEmpty())
            .put("android_build_id", BuildConfig.NATIVE_BUILD_ID)
            .put("loaded_model_sha", voice.optString("loaded_model_sha", voice.optString("model_sha", "")))
            .put("expected_model_sha", voice.optString("expected_model_sha", voice.optString("expected_model_sha256", HERMES_WAKE_ACCEPTANCE_MODEL_SHA256)))
            .put("model_source", voice.optString("model_source", "unknown"))
            .put("threshold", voice.optDouble("threshold", HermesVoiceWakeService.configuredWakeThreshold(this)))
            .put("vad_rms_threshold", voice.optDouble("vad_rms_threshold", HermesVoiceWakeService.configuredVadRmsThreshold(this)))
            .put("vad_peak_threshold", voice.optInt("vad_peak_threshold", HermesVoiceWakeService.configuredVadPeakThreshold(this)))
            .put("transcript_timeout_ms", voice.optLong("transcript_timeout_ms", HermesVoiceWakeService.configuredTranscriptTimeoutMs(this)))
            .put("transcript_min_length_ms", voice.optLong("transcript_min_length_ms", HermesVoiceWakeService.configuredTranscriptPolicy(this).minimumLengthMs))
            .put("transcript_complete_silence_ms", voice.optLong("transcript_complete_silence_ms", HermesVoiceWakeService.configuredTranscriptPolicy(this).completeSilenceMs))
            .put("transcript_possible_silence_ms", voice.optLong("transcript_possible_silence_ms", HermesVoiceWakeService.configuredTranscriptPolicy(this).possiblyCompleteSilenceMs))
            .put("transcript_accept_partial", voice.optBoolean("transcript_accept_partial", HermesVoiceWakeService.configuredTranscriptPolicy(this).acceptPartialResults))
            .put("transcript_engine", voice.optString("transcript_engine", HermesVoiceWakeService.configuredTranscriptEngine(this)))
            .put("local_asr_engine", voice.optString("local_asr_engine", ""))
            .put("local_asr_preferred_engine", voice.optString("local_asr_preferred_engine", HermesVoiceWakeService.configuredTranscriptEngine(this)))
            .put("local_asr_vosk_ready", voice.optBoolean("local_asr_vosk_ready", false))
            .put("local_asr_vosk_model_path", voice.optString("local_asr_vosk_model_path", "files/${LocalCommandTranscriptionEngine.MODEL_PATH}"))
            .put("local_asr_vosk_error", voice.optString("local_asr_vosk_error", ""))
            .put("last_asr_engine", voice.optString("last_asr_engine", ""))
            .put("last_asr_latency_ms", voice.optLong("last_asr_latency_ms", 0L))
            .put("last_asr_audio_captured_ms", voice.optLong("last_asr_audio_captured_ms", 0L))
            .put("last_asr_partial_transcript", voice.optString("last_asr_partial_transcript", ""))
            .put("wake_cooldown_ms", voice.optLong("wake_cooldown_ms", 0L))
            .put("wake_cooldown_until", voice.optLong("wake_cooldown_until", 0L))
            .put("wake_confirmation_frames", voice.optInt("wake_confirmation_frames", HermesVoiceWakeService.configuredWakeConfirmationFrames(this)))
            .put("wake_confirmation_required_frames", voice.optInt("wake_confirmation_required_frames", HermesVoiceWakeService.configuredWakeConfirmationFrames(this)))
            .put("wake_confirmation_window_ms", voice.optLong("wake_confirmation_window_ms", HermesVoiceWakeService.configuredWakeConfirmationWindowMs(this)))
            .put("wake_confirmation", voice.optJSONObject("wake_confirmation") ?: JSONObject()
                .put("required_frames", HermesVoiceWakeService.configuredWakeConfirmationFrames(this))
                .put("window_ms", HermesVoiceWakeService.configuredWakeConfirmationWindowMs(this)))
            .put("tuning_session_id", voice.optString("tuning_session_id", prefs.getString(HermesVoiceWakeService.PREF_TUNING_SESSION_ID, "").orEmpty()))
            .put("prototype_threshold", voice.opt("prototype_threshold") ?: voice.opt("proof_threshold_override") ?: JSONObject.NULL)
            .put("wake_engine_ready", voice.optBoolean("wake_engine_ready", false))
            .put("wake_service_ready", voice.optBoolean("wake_service_ready", voice.optBoolean("foreground_service_started", false) && permissionGranted(Manifest.permission.RECORD_AUDIO)))
            .put("foreground_service_active", voice.optBoolean("foreground_service_active", voice.optBoolean("foreground_service_started", false)))
            .put("listener_lane", voice.optString("listener_lane", if (voice.optBoolean("foreground_service_started", false)) "foreground_service" else "off"))
            .put("listener_mode", voice.optString("listener_mode", if (voice.optBoolean("command_capture_active", false)) "command_capture" else if (voice.optBoolean("foreground_service_started", false)) "standby" else "off"))
            .put("app_visible", true)
            .put("screen_locked", voice.opt("screen_locked") ?: JSONObject.NULL)
            .put("service_bound_to_app", true)
            .put("wake_event_delivery", voice.optString("wake_event_delivery", "backend"))
            .put("duplicate_listener_guard_active", voice.optBoolean("duplicate_listener_guard_active", true))
            .put("permission_state", permissionState)
            .put("battery_optimization_state", voice.optString("battery_optimization_state", "unknown"))
            .put("inference_count", voice.optLong("inference_count", 0L))
            .put("last_confidence", voice.optDouble("last_confidence", 0.0))
            .put("max_confidence_since_start", voice.optDouble("max_confidence_since_start", voice.optDouble("max_observed_confidence", 0.0)))
            .put("raw_wake_detection_count", voice.optLong("raw_wake_detection_count", 0L))
            .put("last_raw_wake_detection_at", voice.optLong("last_raw_wake_detection_at", 0L))
            .put("wake_hit_count", voice.optLong("wake_hit_count", voice.optLong("wake_detection_count", 0L)))
            .put("false_wake_count", voice.optLong("false_wake_count", 0L))
            .put("false_wake_buffer_count", voice.optInt("false_wake_buffer_count", 0))
            .put("false_wake_buffer_max", FalseWakeStore.MAX_SAMPLES)
            .put("false_wake_storage_bytes", voice.optLong("false_wake_storage_bytes", 0L))
            .put("command_capture_active", voice.optBoolean("command_capture_active", false))
            .put("transcript_gate_last_result", voice.optString("transcript_gate_last_result", voice.optString("last_transcript_result", "")))
            .put("last_rejection_reason", voice.optString("last_rejection_reason", voice.optString("rejection_reason", "")))
            .put("last_wake_at", voice.optLong("last_wake_at", voice.optLong("last_wake_detection_at", 0L)))
            .put("last_false_wake_at", voice.optLong("last_false_wake_at", 0L))
            .put("last_error", voice.optString("last_error", voice.optString("failure_reason", "")))
            .put("recent_events", recentEvents)
            .put("voice_wake", voice)
    }

    private fun applyWakeWordPolicy(inputs: JSONObject): JSONObject {
        val wakeThreshold = HermesVoiceWakeService.normalizedWakeThreshold(
            inputs.optDouble("wake_threshold", inputs.optDouble("wakeThreshold", Double.NaN)),
        )
        val vadRms = inputs.optDouble("vad_rms_threshold", inputs.optDouble("vadRmsThreshold", Double.NaN))
            .takeIf { it.isFinite() }
            ?.coerceIn(0.001, 0.2)
        val vadPeak = if (inputs.has("vad_peak_threshold") || inputs.has("vadPeakThreshold")) {
            inputs.optInt("vad_peak_threshold", inputs.optInt("vadPeakThreshold", HermesVoiceWakeService.DEFAULT_VAD_PEAK_THRESHOLD))
                .coerceIn(100, 30000)
        } else null
        fun longPolicy(snake: String, camel: String, fallback: Long, min: Long, max: Long): Long? {
            if (!inputs.has(snake) && !inputs.has(camel)) return null
            val raw = inputs.opt(snake) ?: inputs.opt(camel)
            val value = when (raw) {
                is Number -> raw.toLong()
                is String -> raw.toLongOrNull() ?: fallback
                else -> fallback
            }
            return value.coerceIn(min, max)
        }
        fun intPolicy(snake: String, camel: String, fallback: Int, min: Int, max: Int, alias: String = ""): Int? {
            if (!inputs.has(snake) && !inputs.has(camel) && (alias.isBlank() || !inputs.has(alias))) return null
            val raw = inputs.opt(snake) ?: inputs.opt(camel) ?: if (alias.isNotBlank()) inputs.opt(alias) else null
            val value = when (raw) {
                is Number -> raw.toInt()
                is String -> raw.toIntOrNull() ?: fallback
                else -> fallback
            }
            return value.coerceIn(min, max)
        }
        fun booleanPolicy(snake: String, camel: String): Boolean? {
            if (!inputs.has(snake) && !inputs.has(camel)) return null
            val raw = inputs.opt(snake) ?: inputs.opt(camel)
            return when (raw) {
                is Boolean -> raw
                is Number -> raw.toInt() != 0
                is String -> raw.equals("true", ignoreCase = true) || raw == "1"
                else -> null
            }
        }
        val transcriptTimeoutMs = longPolicy("transcript_timeout_ms", "transcriptTimeoutMs", HermesVoiceWakeService.DEFAULT_TRANSCRIPT_TIMEOUT_MS, 2_000L, 30_000L)
        val transcriptMinLengthMs = longPolicy("transcript_min_length_ms", "transcriptMinLengthMs", HermesVoiceWakeService.DEFAULT_TRANSCRIPT_MIN_LENGTH_MS, 250L, 10_000L)
        val transcriptCompleteSilenceMs = longPolicy("transcript_complete_silence_ms", "transcriptCompleteSilenceMs", HermesVoiceWakeService.DEFAULT_TRANSCRIPT_COMPLETE_SILENCE_MS, 250L, 10_000L)
        val transcriptPossibleSilenceMs = longPolicy("transcript_possible_silence_ms", "transcriptPossibleSilenceMs", HermesVoiceWakeService.DEFAULT_TRANSCRIPT_POSSIBLE_SILENCE_MS, 250L, 10_000L)
        val transcriptAcceptPartial = booleanPolicy("transcript_accept_partial", "transcriptAcceptPartial")
        val wakeCooldownMs = longPolicy("wake_cooldown_ms", "wakeCooldownMs", HermesVoiceWakeService.DEFAULT_WAKE_COOLDOWN_MS, 500L, 60_000L)
        val wakeConfirmationFrames = intPolicy(
            "wake_confirmation_frames",
            "wakeConfirmationFrames",
            HermesVoiceWakeService.DEFAULT_WAKE_CONFIRMATION_FRAMES,
            1,
            5,
            "wakeVerificationFrames",
        )
        val wakeConfirmationWindowMs = longPolicy(
            "wake_confirmation_window_ms",
            "wakeConfirmationWindowMs",
            HermesVoiceWakeService.DEFAULT_WAKE_CONFIRMATION_WINDOW_MS,
            150L,
            2_000L,
        ) ?: longPolicy(
            "wake_verification_window_ms",
            "wakeVerificationWindowMs",
            HermesVoiceWakeService.DEFAULT_WAKE_CONFIRMATION_WINDOW_MS,
            150L,
            2_000L,
        )
        val transcriptAttemptPlan = normalizeTranscriptAttemptPlan(inputs.opt("transcript_attempt_plan") ?: inputs.opt("transcriptAttemptPlan") ?: inputs.opt("transcriptPlan"))
        val transcriptEngine = inputs.optString("transcript_engine", inputs.optString("transcriptEngine", ""))
            .takeIf { it.isNotBlank() }
            ?.let { raw ->
                when (raw) {
                    LocalCommandTranscriptionEngine.PREF_ENGINE_ANDROID,
                    LocalCommandTranscriptionEngine.PREF_ENGINE_AUTO,
                    LocalCommandTranscriptionEngine.PREF_ENGINE_VOSK -> raw
                    else -> null
                }
            }
        val wakePhrase = inputs.optString("wake_phrase", inputs.optString("wakePhrase", ""))
            .trim()
            .lowercase()
            .take(40)
            .takeIf { it.isNotBlank() }
        val sessionId = inputs.optString("tuning_session_id", inputs.optString("tuningSessionId", "")).take(120)
        val origin = inputs.optString("origin", selectedOrigin)
            .ifBlank { prefs.getString(HermesVoiceWakeService.PREF_ORIGIN, "").orEmpty() }
            .ifBlank { BuildConfig.DEFAULT_SERVER_URL }
        val editor = prefs.edit()
        wakeThreshold?.let {
            editor.putFloat(HermesVoiceWakeService.PREF_WAKE_THRESHOLD, it.toFloat())
                .putString(HermesVoiceWakeService.PREF_WAKE_THRESHOLD_SOURCE, HermesVoiceWakeService.THRESHOLD_SOURCE_REMOTE_CONFIG)
        }
        vadRms?.let { editor.putFloat(HermesVoiceWakeService.PREF_VAD_RMS_THRESHOLD, it.toFloat()) }
        vadPeak?.let { editor.putInt(HermesVoiceWakeService.PREF_VAD_PEAK_THRESHOLD, it) }
        transcriptTimeoutMs?.let { editor.putLong(HermesVoiceWakeService.PREF_TRANSCRIPT_TIMEOUT_MS, it) }
        transcriptMinLengthMs?.let { editor.putLong(HermesVoiceWakeService.PREF_TRANSCRIPT_MIN_LENGTH_MS, it) }
        transcriptCompleteSilenceMs?.let { editor.putLong(HermesVoiceWakeService.PREF_TRANSCRIPT_COMPLETE_SILENCE_MS, it) }
        transcriptPossibleSilenceMs?.let { editor.putLong(HermesVoiceWakeService.PREF_TRANSCRIPT_POSSIBLE_SILENCE_MS, it) }
        transcriptAcceptPartial?.let { editor.putBoolean(HermesVoiceWakeService.PREF_TRANSCRIPT_ACCEPT_PARTIAL, it) }
        wakeCooldownMs?.let { editor.putLong(HermesVoiceWakeService.PREF_WAKE_COOLDOWN_MS, it) }
        wakeConfirmationFrames?.let { editor.putInt(HermesVoiceWakeService.PREF_WAKE_CONFIRMATION_FRAMES, it) }
        wakeConfirmationWindowMs?.let { editor.putLong(HermesVoiceWakeService.PREF_WAKE_CONFIRMATION_WINDOW_MS, it) }
        transcriptAttemptPlan?.let { editor.putString(HermesVoiceWakeService.PREF_TRANSCRIPT_ATTEMPT_PLAN, it.toString()) }
        transcriptEngine?.let { editor.putString(HermesVoiceWakeService.PREF_TRANSCRIPT_ENGINE, it) }
        wakePhrase?.let { editor.putString(HermesVoiceWakeService.PREF_WAKE_PHRASE, it) }
        if (sessionId.isNotBlank()) editor.putString(HermesVoiceWakeService.PREF_TUNING_SESSION_ID, sessionId)
        val preferencesCommitted = editor.commit()
        runOnUiThread {
            val intent = Intent(this, HermesVoiceWakeService::class.java)
                .setAction(HermesVoiceWakeService.ACTION_STATUS)
                .putExtra(HermesVoiceWakeService.EXTRA_ORIGIN, origin)
            wakeThreshold?.let { intent.putExtra(HermesVoiceWakeService.EXTRA_WAKE_THRESHOLD, it) }
            vadRms?.let { intent.putExtra("vad_rms_threshold", it) }
            vadPeak?.let { intent.putExtra("vad_peak_threshold", it) }
            transcriptTimeoutMs?.let { intent.putExtra("transcript_timeout_ms", it) }
            transcriptMinLengthMs?.let { intent.putExtra("transcript_min_length_ms", it) }
            transcriptCompleteSilenceMs?.let { intent.putExtra("transcript_complete_silence_ms", it) }
            transcriptPossibleSilenceMs?.let { intent.putExtra("transcript_possible_silence_ms", it) }
            transcriptAcceptPartial?.let { intent.putExtra("transcript_accept_partial", it) }
            wakeCooldownMs?.let { intent.putExtra("wake_cooldown_ms", it) }
            wakeConfirmationFrames?.let { intent.putExtra("wake_confirmation_frames", it) }
            wakeConfirmationWindowMs?.let { intent.putExtra("wake_confirmation_window_ms", it) }
            transcriptAttemptPlan?.let { intent.putExtra("transcript_attempt_plan", it.toString()) }
            transcriptEngine?.let { intent.putExtra("transcript_engine", it) }
            if (sessionId.isNotBlank()) intent.putExtra("tuning_session_id", sessionId)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent) else startService(intent)
        }
        val transcriptPolicy = HermesVoiceWakeService.configuredTranscriptPolicy(this)
        return JSONObject()
            .put("ok", true)
            .put("applied", JSONObject()
                .put("wakeThreshold", wakeThreshold ?: HermesVoiceWakeService.configuredWakeThreshold(this))
                .put("wakePhrase", wakePhrase ?: HermesVoiceWakeService.configuredWakePhrase(this))
                .put("vadRmsThreshold", vadRms ?: HermesVoiceWakeService.configuredVadRmsThreshold(this))
                .put("vadPeakThreshold", vadPeak ?: HermesVoiceWakeService.configuredVadPeakThreshold(this))
                .put("wakeCooldownMs", wakeCooldownMs ?: HermesVoiceWakeService.configuredWakeCooldownMs(this))
                .put("wakeConfirmationFrames", wakeConfirmationFrames ?: HermesVoiceWakeService.configuredWakeConfirmationFrames(this))
                .put("wakeConfirmationWindowMs", wakeConfirmationWindowMs ?: HermesVoiceWakeService.configuredWakeConfirmationWindowMs(this))
                .put("transcriptTimeoutMs", transcriptTimeoutMs ?: HermesVoiceWakeService.configuredTranscriptTimeoutMs(this))
                .put("transcriptMinLengthMs", transcriptPolicy.minimumLengthMs)
                .put("transcriptCompleteSilenceMs", transcriptPolicy.completeSilenceMs)
                .put("transcriptPossibleSilenceMs", transcriptPolicy.possiblyCompleteSilenceMs)
                .put("transcriptAcceptPartial", transcriptPolicy.acceptPartialResults)
                .put("transcriptPlan", transcriptAttemptPlan ?: HermesVoiceWakeService.configuredTranscriptAttemptPlan(this))
                .put("transcriptEngine", transcriptEngine ?: HermesVoiceWakeService.configuredTranscriptEngine(this))
                .put("tuningSessionId", sessionId.ifBlank { prefs.getString(HermesVoiceWakeService.PREF_TUNING_SESSION_ID, "").orEmpty() }))
            .put("preferencesCommitted", preferencesCommitted)
            .put("stateRefreshDeferred", true)
    }

    private fun normalizeTranscriptAttemptPlan(raw: Any?): JSONObject? {
        return try {
            val parsed = when (raw) {
                null, JSONObject.NULL -> return null
                is JSONObject -> raw
                is String -> if (raw.isBlank()) return null else JSONObject(raw)
                else -> JSONObject(raw.toString())
            }
            if (!parsed.has("attempts") && !parsed.has("androidSpeechLanguages") && !parsed.has("android_speech_languages")) null else parsed
        } catch (_: Exception) {
            null
        }
    }

    private fun confirmFalseWakeBatchUploaded(idsJson: String?): JSONObject {
        val ids = jsonStringList(runCatching { JSONArray(idsJson ?: "[]") }.getOrNull())
        return confirmFalseWakeBatchUploaded(ids)
    }

    private fun confirmFalseWakeBatchUploaded(ids: List<String>): JSONObject {
        val result = FalseWakeStore.deleteConfirmed(this, ids)
        logDiagnostic("false_wake_batch_confirmed", result)
        return result
    }

    private fun normalizedThresholdPolicySource(): String {
        val stored = prefs.getString(HermesVoiceWakeService.PREF_WAKE_THRESHOLD_SOURCE, "").orEmpty()
        return when (stored) {
            HermesVoiceWakeService.THRESHOLD_SOURCE_REMOTE_CONFIG, "downloaded_operation" ->
                HermesVoiceWakeService.THRESHOLD_SOURCE_REMOTE_CONFIG
            else -> HermesVoiceWakeService.THRESHOLD_SOURCE_NATIVE_DEFAULT
        }
    }

    private fun beginHermesWakeProof(reason: String, wakeThresholdOverride: Double? = null): JSONObject {
        val origin = selectedOrigin.ifBlank {
            prefs.getString(HermesVoiceWakeService.PREF_ORIGIN, "").orEmpty()
        }.ifBlank { BuildConfig.DEFAULT_SERVER_URL }
        val needed = voiceWakeRuntimePermissions().filter { permission -> !permissionGranted(permission) }
        prefs.edit()
            .putBoolean(HermesVoiceWakeService.PREF_ENABLED, true)
            .putString(HermesVoiceWakeService.PREF_ORIGIN, origin)
            .apply()
        val proof = JSONObject()
            .put("ok", needed.isEmpty())
            .put("type", "hermes_wake_proof_started")
            .put("reason", reason)
            .put("origin", origin)
            .put("proof_threshold_override", wakeThresholdOverride ?: JSONObject.NULL)
            .put("missing_runtime_permissions", JSONArray(needed))
            .put("status", voiceWakeStatus())
        if (needed.isEmpty()) {
            runOnUiThread { HermesVoiceWakeService.start(this, origin, proofSession = true, wakeThreshold = wakeThresholdOverride) }
            awaitHermesWakeProofAndUpload(origin, reason)
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            runOnUiThread { requestPermissions(needed.toTypedArray(), REQUEST_VOICE_WAKE_PERMISSION) }
        }
        logDiagnostic("voice_wake_proof_started", proof)
        return proof
    }

    private fun thresholdFromIntent(intent: Intent?): Double? =
        HermesVoiceWakeService.normalizedWakeThreshold(
            when {
                intent?.hasExtra(HermesVoiceWakeService.EXTRA_WAKE_THRESHOLD) == true ->
                    numericExtra(intent, HermesVoiceWakeService.EXTRA_WAKE_THRESHOLD)
                intent?.hasExtra("threshold") == true ->
                    numericExtra(intent, "threshold")
                else -> Double.NaN
            },
        )

    private fun thresholdFromData(data: android.net.Uri): Double? =
        HermesVoiceWakeService.normalizedWakeThreshold(
            data.getQueryParameter(HermesVoiceWakeService.EXTRA_WAKE_THRESHOLD)?.toDoubleOrNull()
                ?: data.getQueryParameter("threshold")?.toDoubleOrNull()
                ?: Double.NaN,
        )

    private fun numericExtra(intent: Intent, key: String): Double {
        val raw = intent.extras?.get(key)
        return when (raw) {
            is Number -> raw.toDouble()
            is String -> raw.toDoubleOrNull() ?: Double.NaN
            else -> Double.NaN
        }
    }

    private fun awaitHermesWakeProofAndUpload(origin: String, reason: String) {
        thread(name = "hermes-wake-proof-upload") {
            var latest = voiceWakeStatus()
            val deadline = System.currentTimeMillis() + 15_000L
            while (System.currentTimeMillis() < deadline) {
                HermesVoiceWakeService.requestStatus(this, proofSession = true)
                latest = voiceWakeStatus()
                if (hermesWakeProofAcceptanceReady(latest)) break
                Thread.sleep(250L)
            }
            val accepted = hermesWakeProofAcceptanceReady(latest)
            val payload = JSONObject()
                .put("ok", accepted)
                .put("type", "hermes_wake_proof_live_diagnostics")
                .put("reason", reason)
                .put("acceptance_ready", accepted)
                .put("required", JSONArray(listOf(
                    "status_source=live_service",
                    "proof_session_active=true",
                    "permission_record_audio=true",
                    "foreground_service_started=true",
                    "audio_record_started=true",
                    "personalized_model_exists=true",
                    "model_sha=$HERMES_WAKE_ACCEPTANCE_MODEL_SHA256",
                    "model_sha_match=true",
                    "onnx_runtime_available=true",
                    "wake_engine_ready=true",
                    "inference_count>0",
                    "wake_confidence_observed=true",
                    "threshold_crossed=true",
                    "wake_detection_count>0",
                    "wake_detected_event_emitted=true",
                    "command_capture_started=true",
                )))
                .put("status", latest)
            logDiagnostic(if (accepted) "voice_wake_proof_live_ready" else "voice_wake_proof_live_incomplete", payload)
            forceUploadNativeDiagnostics(origin, if (accepted) "hermes_wake_proof_live_ready" else "hermes_wake_proof_live_incomplete")
        }
    }

    private fun hermesWakeProofAcceptanceReady(status: JSONObject): Boolean {
        return status.optString("status_source") == "live_service" &&
            status.optBoolean("proof_session_active", false) &&
            status.optBoolean("permission_record_audio", false) &&
            status.optBoolean("foreground_service_started", false) &&
            status.optBoolean("audio_record_started", false) &&
            status.optBoolean("personalized_model_exists", false) &&
            status.optString("model_sha").equals(HERMES_WAKE_ACCEPTANCE_MODEL_SHA256, ignoreCase = true) &&
            status.optBoolean("model_sha_match", false) &&
            status.optBoolean("onnx_runtime_available", false) &&
            status.optBoolean("wake_engine_ready", false) &&
            status.optLong("inference_count", 0L) > 0L &&
            status.optBoolean("wake_confidence_observed", false) &&
            status.optBoolean("threshold_crossed", false) &&
            status.optLong("wake_detection_count", 0L) > 0L &&
            status.optBoolean("wake_detected_event_emitted", false) &&
            status.optBoolean("command_capture_started", false)
    }

    private fun voiceWakeRuntimePermissions(): List<String> {
        return buildList {
            add(Manifest.permission.RECORD_AUDIO)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) add(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    private fun hasManifestPermission(permission: String): Boolean {
        return try {
            val info = packageManager.getPackageInfo(packageName, PackageManager.GET_PERMISSIONS)
            info.requestedPermissions?.contains(permission) == true
        } catch (_: Exception) {
            false
        }
    }

    private fun openWakeWordBundleExists(dir: File): Boolean =
        File(dir, OpenWakeWordBundleEngine.MEL_MODEL_NAME).isFile &&
            File(dir, OpenWakeWordBundleEngine.EMBEDDING_MODEL_NAME).isFile &&
            File(dir, OpenWakeWordBundleEngine.CLASSIFIER_MODEL_NAME).isFile

    private fun sha256FileOrBlank(file: File): String {
        if (!file.isFile || file.length() <= 0L) return ""
        val path = file.absolutePath
        val modifiedAt = file.lastModified()
        val size = file.length()
        synchronized(modelShaCacheLock) {
            if (
                cachedModelShaPath == path &&
                cachedModelShaModifiedAt == modifiedAt &&
                cachedModelShaSize == size
            ) {
                return cachedModelSha
            }
        }
        return try {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    digest.update(buffer, 0, read)
                }
            }
            val sha = digest.digest().joinToString("") { "%02x".format(it) }
            synchronized(modelShaCacheLock) {
                cachedModelShaPath = path
                cachedModelShaModifiedAt = modifiedAt
                cachedModelShaSize = size
                cachedModelSha = sha
            }
            sha
        } catch (_: Exception) {
            ""
        }
    }

    private fun hermesWakeModelAssetFound(): Boolean {
        return try {
            assets.open("voice/base_hermes.onnx").use { true }
        } catch (_: Exception) {
            false
        }
    }

    private fun safeCookieSummary(): JSONObject {
        val targetUrl = latestWebViewUrl.ifBlank { selectedOrigin.ifBlank { BuildConfig.DEFAULT_SERVER_URL } }
        return try {
            val cookies = CookieManager.getInstance().getCookie(targetUrl).orEmpty()
            val names = cookies.split(";")
                .mapNotNull { part -> part.split("=", limit = 2).firstOrNull()?.trim() }
                .filter { it.isNotBlank() }
                .distinct()
            JSONObject()
                .put("url_origin", Uri.parse(targetUrl).let { uri -> "${uri.scheme}://${uri.host}" })
                .put("cookie_count", names.size)
                .put("cookie_names", JSONArray(names))
                .put("has_wa_uid", names.contains("wa_uid"))
                .put("has_android_auth_session_cookie", names.contains("wa_android_auth_session"))
        } catch (error: Exception) {
            JSONObject()
                .put("error", error.javaClass.simpleName)
                .put("cookie_count", 0)
                .put("has_wa_uid", false)
                .put("has_android_auth_session_cookie", false)
        }
    }

    private fun summarizeIntent(intent: Intent?, reason: String): JSONObject {
        val data = intent?.data
        return JSONObject()
            .put("reason", reason)
            .put("action", intent?.action.orEmpty())
            .put("data", data?.toString().orEmpty())
            .put("scheme", data?.scheme.orEmpty())
            .put("host", data?.host.orEmpty())
            .put("package", intent?.`package`.orEmpty())
            .put("component", intent?.component?.flattenToShortString().orEmpty())
            .put("package_targeted", intent?.`package` == packageName || intent?.component?.packageName == packageName)
            .put("categories", JSONArray(intent?.categories?.toList() ?: emptyList<String>()))
    }

    private fun clearWebViewData(reason: String): String {
        runOnUiThread {
            try {
                CookieManager.getInstance().removeAllCookies(null)
                CookieManager.getInstance().flush()
                WebStorage.getInstance().deleteAllData()
                webView?.clearCache(true)
                webView?.clearHistory()
                logDiagnostic("webview_data_cleared", JSONObject().put("reason", reason))
            } catch (error: Exception) {
                rememberException("webview_data_clear_failed", error)
                logDiagnostic("webview_data_clear_failed", JSONObject()
                    .put("reason", reason)
                    .put("error", error.javaClass.simpleName))
            }
        }
        return JSONObject().put("ok", true).toString()
    }

    private fun resetNativeAuth(reason: String): String {
        waitingForAndroidAuth = false
        androidAuthPollToken += 1
        lastAndroidReturnIntentAt = 0
        lastAndroidReturnSessionId = ""
        rotateNativeCorrelationId()
        rotateAndroidAuthSessionId()
        transitionOAuth("IDLE", reason)
        runOnUiThread {
            emitRendererEvent("wasm-agent:native-android-auth-reset", JSONObject()
                .put("reason", reason)
                .put("session", androidAuthSessionId)
                .put("native_correlation_id", nativeCorrelationId))
        }
        return JSONObject().put("ok", true).toString()
    }

    private fun maybeUploadNativeDiagnostics(kind: String) {
        val origin = selectedOrigin
        if (origin.isBlank()) return
        val important = kind.contains("auth", ignoreCase = true) ||
            kind.contains("intent", ignoreCase = true) ||
            kind.contains("return", ignoreCase = true) ||
            kind.contains("app_ready", ignoreCase = true) ||
            kind.contains("voice_wake", ignoreCase = true) ||
            kind.contains("error", ignoreCase = true) ||
            kind.contains("failed", ignoreCase = true)
        if (!important) return
        val now = System.currentTimeMillis()
        if (now - lastDiagnosticsUploadAt < 2000 && !kind.contains("error", ignoreCase = true) && !kind.contains("failed", ignoreCase = true)) {
            return
        }
        lastDiagnosticsUploadAt = now
        val latest = diagnostics.latestString()
        thread(name = "wasm-agent-native-diagnostics-upload") {
            try {
                val payload = JSONObject(latest)
                    .put("device_id", "android-${BuildConfig.NATIVE_BUILD_ID}-${installDeviceHash}")
                    .put("build_id", BuildConfig.NATIVE_BUILD_ID)
                    .put("android_auth_session", androidAuthSessionId)
                    .put("native_correlation_id", nativeCorrelationId)
                    .put("install_device_hash", installDeviceHash)
                    .put("reason", kind)
                val connection = (URL(origin.trimEnd('/') + "/native/diagnostics").openConnection() as HttpURLConnection).apply {
                    connectTimeout = 2500
                    readTimeout = 2500
                    requestMethod = "POST"
                    setRequestProperty("Content-Type", "application/json; charset=utf-8")
                    doOutput = true
                }
                connection.outputStream.use { stream ->
                    stream.write(payload.toString().toByteArray(Charsets.UTF_8))
                }
                connection.inputStream.close()
                connection.disconnect()
            } catch (_: Exception) {
                // Diagnostics upload is best-effort and must not affect auth.
            }
        }
    }

    private fun forceUploadNativeDiagnostics(origin: String, reason: String) {
        val latest = diagnostics.latestString()
        thread(name = "wasm-agent-native-diagnostics-force-upload") {
            try {
                val payload = JSONObject(latest)
                    .put("device_id", "android-${BuildConfig.NATIVE_BUILD_ID}-${installDeviceHash}")
                    .put("build_id", BuildConfig.NATIVE_BUILD_ID)
                    .put("android_auth_session", androidAuthSessionId)
                    .put("native_correlation_id", nativeCorrelationId)
                    .put("install_device_hash", installDeviceHash)
                    .put("reason", reason)
                    .put("forced_upload", true)
                val connection = (URL(origin.trimEnd('/') + "/native/diagnostics").openConnection() as HttpURLConnection).apply {
                    connectTimeout = 5000
                    readTimeout = 5000
                    requestMethod = "POST"
                    setRequestProperty("Content-Type", "application/json; charset=utf-8")
                    doOutput = true
                }
                connection.outputStream.use { stream ->
                    stream.write(payload.toString().toByteArray(Charsets.UTF_8))
                }
                connection.inputStream.close()
                connection.disconnect()
            } catch (error: Exception) {
                Log.w(LOG_TAG, "forced diagnostics upload failed: ${error.javaClass.simpleName}")
            }
        }
    }

    private fun sha256Hex(value: String): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { byte -> "%02x".format(byte) }
    }

    private fun sha256Bytes(value: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(value)
        return digest.joinToString("") { byte -> "%02x".format(byte) }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private class NativeDiagnostics(private val file: File) {
        private val events = ArrayDeque<JSONObject>()

        fun path(): String = file.absolutePath

        @Synchronized
        fun remember(kind: String, event: JSONObject) {
            while (events.size >= 160) events.removeFirst()
            events.addLast(redactJsonObject(event))
        }

        @Synchronized
        fun writeSnapshot(kind: String, snapshot: JSONObject) {
            val eventList = JSONArray(events.toList())
            val latest = JSONObject()
                .put("schema", "hermes.wasm_agent.android_native_diagnostics.v1")
                .put("updated_at", System.currentTimeMillis())
                .put("latest_kind", kind)
                .put("build", redactValue(snapshot.opt("build")))
                .put("package", redactValue(snapshot.opt("package")))
                .put("device", redactValue(snapshot.opt("device")))
                .put("android", redactValue(snapshot.opt("android")))
                .put("webview", redactValue(snapshot.opt("webview")))
                .put("current_webview_url", redactValue(snapshot.opt("current_webview_url")))
                .put("selected_origin", redactValue(snapshot.opt("selected_origin")))
                .put("recent_webview_nav_events", filterEvents(eventList, listOf("webview_", "internal_url_", "external_url_", "intent_launch_")))
                .put("console_logs", filterEvents(eventList, listOf("webview_console_")))
                .put("auth_urls", filterAuthUrls(eventList))
                .put("lifecycle_events", filterEvents(eventList, listOf("activity_", "back_button_", "keyboard_")))
                .put("last_intent", redactValue(snapshot.opt("last_intent")))
                .put("last_deep_link", redactValue(snapshot.opt("last_deep_link")))
                .put("android_auth_session", snapshot.optString("android_auth_session", ""))
                .put("native_correlation_id", snapshot.optString("native_correlation_id", ""))
                .put("safe_cookie_session_summary", redactValue(snapshot.opt("safe_cookie_session_summary")))
                .put("oauth", redactValue(snapshot.opt("oauth")))
                .put("voice_wake", redactValue(snapshot.opt("voice_wake")))
                .put("voice_tuning", redactValue(snapshot.opt("voice_tuning")))
                .put("last_exception", redactValue(snapshot.opt("last_exception")))
                .put("events", eventList)
            file.parentFile?.mkdirs()
            file.writeText(safeJsonString(latest, 2))
        }

        @Synchronized
        fun log(kind: String, event: JSONObject, snapshot: JSONObject) {
            remember(kind, event)
            writeSnapshot(kind, snapshot)
        }

        @Synchronized
        fun clear(snapshot: JSONObject) {
            events.clear()
            val latest = JSONObject()
                .put("schema", "hermes.wasm_agent.android_native_diagnostics.v1")
                .put("updated_at", System.currentTimeMillis())
                .put("latest_kind", "cleared")
                .put("build", redactValue(snapshot.opt("build")))
                .put("package", redactValue(snapshot.opt("package")))
                .put("device", redactValue(snapshot.opt("device")))
                .put("android", redactValue(snapshot.opt("android")))
                .put("webview", redactValue(snapshot.opt("webview")))
                .put("current_webview_url", redactValue(snapshot.opt("current_webview_url")))
                .put("android_auth_session", snapshot.optString("android_auth_session", ""))
                .put("native_correlation_id", snapshot.optString("native_correlation_id", ""))
                .put("oauth", redactValue(snapshot.opt("oauth")))
                .put("voice_wake", redactValue(snapshot.opt("voice_wake")))
                .put("voice_tuning", redactValue(snapshot.opt("voice_tuning")))
                .put("events", JSONArray())
            file.parentFile?.mkdirs()
            file.writeText(safeJsonString(latest, 2))
        }

        @Synchronized
        fun latestString(): String {
            return try {
                if (file.exists()) file.readText() else JSONObject()
                    .put("schema", "hermes.wasm_agent.android_native_diagnostics.v1")
                    .put("available", false)
                    .toString(2)
            } catch (_: Exception) {
                JSONObject().put("available", false).toString()
            }
        }

        companion object {
            private val sensitiveKeyPattern = Regex(
                "(access.?token|auth.?code|authorization|client.?secret|credential|cookie|id.?token|password|refresh.?token|secret|token|wa.?uid)",
                RegexOption.IGNORE_CASE,
            )
            private val sensitiveParamPattern = Regex(
                "([?&#;]|\\b)(access_token|auth_code|client_secret|code|credential|id_token|password|refresh_token|secret|token|wa_uid)=([^&\\s\"'<>;#]+)",
                RegexOption.IGNORE_CASE,
            )

            fun redactString(value: String): String {
                return value
                    .replace(Regex("(Bearer\\s+)[A-Za-z0-9._~+/=-]+", RegexOption.IGNORE_CASE), "$1[redacted]")
                    .replace(sensitiveParamPattern) { match ->
                        "${match.groupValues[1]}${match.groupValues[2]}=[redacted]"
                    }
                    .replace(Regex("((Cookie|Set-Cookie):\\s*)[^\\r\\n]+", RegexOption.IGNORE_CASE), "$1[redacted]")
                    .let { if (it.length > 120_000) it.take(120_000) else it }
            }

            fun safeJsonString(value: Any?, indentSpaces: Int = 0): String {
                return try {
                    when (val safe = redactValue(value)) {
                        is JSONObject -> if (indentSpaces > 0) safe.toString(indentSpaces) else safe.toString()
                        is JSONArray -> if (indentSpaces > 0) safe.toString(indentSpaces) else safe.toString()
                        else -> JSONObject().put("value", safe).toString()
                    }
                } catch (_: Exception) {
                    JSONObject().put("available", false).put("error", "json_serialization_failed").toString()
                }
            }

            private fun redactJsonObject(source: JSONObject): JSONObject {
                return redactValue(source) as? JSONObject ?: JSONObject()
            }

            private fun redactValue(value: Any?, key: String = "", depth: Int = 0): Any {
                if (depth > 8) return "[depth-limit]"
                if (value == null || value == JSONObject.NULL) return JSONObject.NULL
                val normalizedKey = key.lowercase()
                val safeCookieSummaryKey = normalizedKey in setOf(
                    "safe_cookie_session_summary",
                    "cookie_count",
                    "cookie_names",
                    "has_wa_uid",
                    "has_android_auth_session_cookie",
                )
                if (key.isNotBlank() && sensitiveKeyPattern.containsMatchIn(key) && !safeCookieSummaryKey) return "[redacted]"
                return when (value) {
                    is JSONObject -> {
                        val output = JSONObject()
                        val keys = value.keys()
                        while (keys.hasNext()) {
                            val itemKey = keys.next()
                            output.put(itemKey, redactValue(value.opt(itemKey), itemKey, depth + 1))
                        }
                        output
                    }
                    is JSONArray -> {
                        val output = JSONArray()
                        for (index in 0 until minOf(value.length(), 200)) {
                            output.put(redactValue(value.opt(index), "", depth + 1))
                        }
                        output
                    }
                    is String -> redactString(value)
                    is Double -> if (java.lang.Double.isFinite(value)) value else JSONObject.NULL
                    is Float -> if (java.lang.Float.isFinite(value)) value else JSONObject.NULL
                    is Number, is Boolean -> value
                    else -> redactString(value.toString())
                }
            }

            private fun filterEvents(events: JSONArray, prefixes: List<String>): JSONArray {
                val output = JSONArray()
                for (index in 0 until events.length()) {
                    val event = events.optJSONObject(index) ?: continue
                    val kind = event.optString("kind", "")
                    if (prefixes.any { prefix -> kind.startsWith(prefix) }) output.put(event)
                }
                return trimArray(output, 80)
            }

            private fun filterAuthUrls(events: JSONArray): JSONArray {
                val output = JSONArray()
                for (index in 0 until events.length()) {
                    val event = events.optJSONObject(index) ?: continue
                    val text = safeJsonString(event)
                    if (text.contains("accounts.google.com") ||
                        text.contains("/auth/google") ||
                        text.contains("/native/android/auth") ||
                        text.contains("wasm-agent://android-auth-return")) {
                        output.put(event)
                    }
                }
                return trimArray(output, 80)
            }

            private fun trimArray(source: JSONArray, limit: Int): JSONArray {
                val output = JSONArray()
                val start = maxOf(0, source.length() - limit)
                for (index in start until source.length()) {
                    output.put(source.opt(index))
                }
                return output
            }
        }
    }
}
