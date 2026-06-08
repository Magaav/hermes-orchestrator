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
import android.net.Uri
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Looper
import android.provider.Settings
import android.util.Log
import android.view.Gravity
import android.view.KeyEvent
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
import com.colmeio.wasmagent.voice.OpenWakeWordOnnxEngine
import com.colmeio.wasmagent.voice.VoiceTuningCategory
import com.colmeio.wasmagent.voice.VoiceTuningRecorder
import com.colmeio.wasmagent.voice.VoiceTuningStore
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread
import kotlin.math.roundToInt

class MainActivity : Activity() {
    companion object {
        private const val PREFS_NAME = "wasm_agent_android_shell"
        private const val PREF_ANDROID_AUTH_SESSION = "android_auth_session"
        private const val PREF_NATIVE_CORRELATION_ID = "native_correlation_id"
        private const val PREF_INSTALL_ID = "install_id"
        private const val PREF_LAST_URL = "last_url"
        private const val PREF_SELECTED_ORIGIN = "selected_origin"
        private const val STATE_WEBVIEW = "wasm_agent_webview_state"
        private const val STATE_SELECTED_ORIGIN = "wasm_agent_selected_origin"
        private const val LOG_TAG = "WasmAgentNative"
        private const val REQUEST_FILE_CHOOSER = 8801
        private const val REQUEST_WEB_PERMISSIONS = 8802
        private const val REQUEST_GEOLOCATION_PERMISSION = 8803
        private const val REQUEST_VOICE_WAKE_PERMISSION = 8804
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
    @Volatile private var webViewPageStartedAt: Long = 0
    @Volatile private var webViewPageFinishedAt: Long = 0
    @Volatile private var webViewPageCommitVisibleAt: Long = 0
    @Volatile private var webViewMainFrameError: JSONObject? = null
    @Volatile private var lastRendererReadiness: JSONObject? = null
    private val prefs by lazy { getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE) }
    private val diagnostics by lazy { NativeDiagnostics(File(filesDir, "native-diagnostics/latest.json")) }
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
            .put("shell", "android-webview"))
        handleLaunchIntent(intent, "activity_create")

        val restoredOrigin = savedInstanceState?.getString(STATE_SELECTED_ORIGIN).orEmpty()
        val restoredWebViewState = savedInstanceState?.getBundle(STATE_WEBVIEW)
        if (restoredOrigin.isNotBlank() && restoredWebViewState != null) {
            selectedOrigin = restoredOrigin
            openRemotePwaWebView(restoredOrigin, restoredWebViewState)
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
        val data = intent?.data ?: return
        lastDeepLinkSummary = JSONObject()
            .put("reason", reason)
            .put("data", data.toString())
            .put("scheme", data.scheme.orEmpty())
            .put("host", data.host.orEmpty())
        logDiagnostic("activity_intent_data_observed", lastDeepLinkSummary ?: JSONObject())
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
        showSplash("WASM Agent", "Connecting to wa.colmeio.com")
        logDiagnostic("backend_resolve_started", JSONObject()
            .put("candidates", JSONArray(candidates))
            .put("allow_local_dev", BuildConfig.ALLOW_LOCAL_DEV))
        thread(name = "wasm-agent-origin-probe") {
            val selected = candidates.firstOrNull { candidate -> identifiesWasmAgent(candidate) }
            runOnUiThread {
                if (selected == null) {
                    logDiagnostic("backend_resolve_failed", JSONObject()
                        .put("candidates", JSONArray(candidates)))
                    showErrorScreen(
                        "WASM Agent is offline",
                        "The Android shell could not reach wa.colmeio.com. Check your connection and retry.",
                    )
                } else {
                    selectedOrigin = selected
                    prefs.edit().putString(PREF_SELECTED_ORIGIN, selected).apply()
                    logDiagnostic("backend_resolve_finished", JSONObject()
                        .put("selected_origin", selected))
                    openRemotePwaWebView(selected)
                }
            }
        }
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
            .appendQueryParameter("buildId", BuildConfig.NATIVE_BUILD_ID)
            .appendQueryParameter("native_correlation_id", nativeCorrelationId)
            .appendQueryParameter("android_auth_session", androidAuthSessionId)
            .appendQueryParameter("install_device_hash", installDeviceHash)
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
            prefs.edit().putString(PREF_LAST_URL, url).apply()
            logDiagnostic("webview_load_url", JSONObject()
                .put("url", url)
                .put("deterministic_boot", true))
            view.alpha = 0f
            view.loadUrl(url)
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
        view.addJavascriptInterface(AndroidNativeBridge(origin), "wasmAgentNative")
        view.addJavascriptInterface(AndroidDiagnosticsBridge(origin), "WasmAgentAndroidDiagnostics")
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
                logDiagnostic("webview_console_message", JSONObject()
                    .put("level", consoleMessage.messageLevel().name.lowercase())
                    .put("message", consoleMessage.message().take(500))
                    .put("source", consoleMessage.sourceId().orEmpty())
                    .put("line", consoleMessage.lineNumber()))
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

    private inner class AndroidBridge(private val origin: String) {
        @JavascriptInterface
        fun authSessionId(): String = androidAuthSessionId

        @JavascriptInterface
        fun shellInfo(): String = nativeShellConfig(origin).toString()

        @JavascriptInterface
        fun logDiagnostic(kind: String, payloadJson: String?) {
            val payload = parseJsonPayload(payloadJson)
            rememberRendererReadiness(kind, payload)
            logDiagnostic("renderer_$kind", payload)
        }

        @JavascriptInterface
        fun appReady(payloadJson: String?) {
            val payload = parseJsonPayload(payloadJson)
            logDiagnostic("renderer_app_ready", payload)
            runOnUiThread {
                webView?.alpha = 1f
                hideSplash()
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
        fun config(): String = nativeShellConfig(origin).toString()

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
            CookieManager.getInstance().flush()
            val cookies = CookieManager.getInstance().getCookie(origin).orEmpty()
            logDiagnostic("renderer_auth_cookie_flush_requested", payload
                .put("cookie_count", if (cookies.isBlank()) 0 else cookies.split(";").size)
                .put("has_wa_uid", cookies.contains("wa_uid=")))
            if (cookies.contains("wa_uid=")) {
                transitionOAuth("COOKIE_FLUSHED", "renderer_flush_auth_cookies")
            }
            return JSONObject()
                .put("ok", true)
                .put("cookieCount", if (cookies.isBlank()) 0 else cookies.split(";").size)
                .put("hasWaUid", cookies.contains("wa_uid="))
                .toString()
        }

        @JavascriptInterface
        fun getNativeState(): String = diagnosticsSnapshot().toString()

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
        fun startVoiceTuningSample(categoryId: String): String = startVoiceTuningSample(categoryId, null)

        @JavascriptInterface
        fun startVoiceTuningSample(categoryId: String, source: String?): String {
            val category = VoiceTuningCategory.fromId(categoryId)
                ?: return JSONObject().put("ok", false).put("error", "unknown_voice_tuning_category").toString()
            if (!permissionGranted(Manifest.permission.RECORD_AUDIO)) {
                runOnUiThread {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                        requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), REQUEST_VOICE_WAKE_PERMISSION)
                    }
                }
                return JSONObject()
                    .put("ok", false)
                    .put("requested", true)
                    .put("error", "record_audio_permission_missing")
                    .put("status", this@MainActivity.voiceTuningStatus())
                    .toString()
            }
            val result = voiceTuningRecorder.record(category, source) { event ->
                logDiagnostic(event.optString("type", "voice_tuning_event"), event)
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
        fun cancelVoiceTuning(): String {
            val event = voiceTuningRecorder.cancel()
            logDiagnostic("voice_tuning_cancelled", event)
            emitRendererEvent("wasm-agent:native-voice-tuning", event)
            return event.put("status", this@MainActivity.voiceTuningStatus()).toString()
        }

        @JavascriptInterface
        fun requestVoiceWakePermission(): String {
            val needed = voiceWakeRuntimePermissions().filter { permission -> !permissionGranted(permission) }
            prefs.edit()
                .putBoolean(HermesVoiceWakeService.PREF_ENABLED, true)
                .putString(HermesVoiceWakeService.PREF_ORIGIN, origin)
                .apply()
            if (needed.isEmpty()) {
                runOnUiThread { HermesVoiceWakeService.start(this@MainActivity, origin) }
                return JSONObject().put("ok", true).put("granted", true).put("status", voiceWakeStatus()).toString()
            }
            runOnUiThread {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    requestPermissions(needed.toTypedArray(), REQUEST_VOICE_WAKE_PERMISSION)
                }
            }
            return JSONObject().put("ok", true).put("requested", true).put("status", voiceWakeStatus()).toString()
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
        fun disableVoiceWake(): String {
            prefs.edit().putBoolean(HermesVoiceWakeService.PREF_ENABLED, false).apply()
            runOnUiThread {
                HermesVoiceWakeService.stop(this@MainActivity)
                logDiagnostic("voice_wake_disable_requested")
            }
            return JSONObject().put("ok", true).put("status", voiceWakeStatus()).toString()
        }
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
        fun startVoiceTuningSample(categoryId: String): String = AndroidNativeBridge(origin).startVoiceTuningSample(categoryId)

        @JavascriptInterface
        fun startVoiceTuningSample(categoryId: String, source: String?): String = AndroidNativeBridge(origin).startVoiceTuningSample(categoryId, source)

        @JavascriptInterface
        fun deleteLastVoiceTuningSample(categoryId: String): String = AndroidNativeBridge(origin).deleteLastVoiceTuningSample(categoryId)

        @JavascriptInterface
        fun cancelVoiceTuning(): String = AndroidNativeBridge(origin).cancelVoiceTuning()

        @JavascriptInterface
        fun requestVoiceWakePermission(): String = AndroidNativeBridge(origin).requestVoiceWakePermission()

        @JavascriptInterface
        fun enableVoiceWake(): String = AndroidNativeBridge(origin).enableVoiceWake()

        @JavascriptInterface
        fun disableVoiceWake(): String = AndroidNativeBridge(origin).disableVoiceWake()

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
            .put("voiceWake", voiceWakeStatus())
            .put("diagnosticsPath", diagnostics.path())
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
        diagnostics.log(kind, enriched, diagnosticsSnapshot())
        Log.i(LOG_TAG, "${kind} ${NativeDiagnostics.redactString(payload.toString()).take(3000)}")
        maybeUploadNativeDiagnostics(kind)
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
            .put("safe_cookie_session_summary", safeCookieSummary())
            .put("oauth", JSONObject()
                .put("stage", oauthStage)
                .put("result", oauthResult))
            .put("voice_wake", voiceWakeStatus())
            .put("voice_tuning", voiceTuningStatus())
            .put("last_exception", lastExceptionSummary ?: JSONObject.NULL)
    }

    private fun voiceTuningStatus(): JSONObject {
        val wakeStatus = voiceWakeStatus()
        val modelStatus = when {
            wakeStatus.optBoolean("wake_engine_ready", false) -> "validated_model"
            wakeStatus.optJSONObject("wake_model")?.optBoolean("wake_model_exists", false) == true -> "candidate_model"
            else -> "no_model"
        }
        val nextAction = "Samples collected here must be exported and trained with tools/voice/audit-hermes-dataset.py, train-hermes-wake-model.py, build-hermes-wake-model.sh, verify-hermes-wake-model.py, and import-hermes-wake-model.sh before wake-on-Hermes is enabled."
        return voiceTuningStore.status(modelStatus = modelStatus, nextAction = nextAction)
            .put("recording_active", voiceTuningRecorder.isRecording())
            .put("permission_record_audio", permissionGranted(Manifest.permission.RECORD_AUDIO))
            .put("always_on_wake_service_started", false)
            .put("wake_service_enabled", prefs.getBoolean(HermesVoiceWakeService.PREF_ENABLED, false))
            .put("message", "Samples collected. Training and validation still required.")
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

    private fun voiceWakeStatus(): JSONObject {
        val enabled = prefs.getBoolean(HermesVoiceWakeService.PREF_ENABLED, false)
        val wakeEngine = OpenWakeWordOnnxEngine(File(filesDir, "voice/hermes.onnx"))
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
        return base
            .put("enabled", enabled)
            .put("wake_word", "hermes")
            .put("permission_record_audio", permissionGranted(Manifest.permission.RECORD_AUDIO))
            .put("permission_post_notifications", if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) permissionGranted(Manifest.permission.POST_NOTIFICATIONS) else true)
            .put("wake_engine", wakeEngine.name)
            .put("wake_engine_ready", wakeEngine.ready)
            .put("wake_engine_state", if (wakeEngine.ready) "ready" else wakeEngine.diagnosticReason)
            .put("wake_model_path", "files/voice/hermes.onnx")
            .put("asset_model_path", "assets/voice/hermes.onnx")
            .put("model_asset_found", hermesWakeModelAssetFound())
            .put("onnx_runtime_available", wakeEngine.onnxRuntimeAvailable)
            .put("wake_model", wakeEngine.diagnostics())
            .put("foreground_service_required", true)
            .put("foreground_notification", "WASM Agent listening for Hermes")
            .put("source", "android_native_hermes_voice_wake")
            .put("build_id", BuildConfig.NATIVE_BUILD_ID)
            .put("origin", prefs.getString(HermesVoiceWakeService.PREF_ORIGIN, selectedOrigin).orEmpty())
            .put("audio_retained", false)
            .put("continuous_audio_uploaded", false)
    }

    private fun voiceWakeRuntimePermissions(): List<String> {
        return buildList {
            add(Manifest.permission.RECORD_AUDIO)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) add(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    private fun hermesWakeModelAssetFound(): Boolean {
        return try {
            assets.open("voice/hermes.onnx").use { true }
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

    private fun sha256Hex(value: String): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { byte -> "%02x".format(byte) }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private class NativeDiagnostics(private val file: File) {
        private val events = ArrayDeque<JSONObject>()

        fun path(): String = file.absolutePath

        @Synchronized
        fun log(kind: String, event: JSONObject, snapshot: JSONObject) {
            while (events.size >= 160) events.removeFirst()
            events.addLast(redactJsonObject(event))
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
                .put("last_exception", redactValue(snapshot.opt("last_exception")))
                .put("events", eventList)
            file.parentFile?.mkdirs()
            file.writeText(latest.toString(2))
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
                .put("events", JSONArray())
            file.parentFile?.mkdirs()
            file.writeText(latest.toString(2))
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
                    val text = event.toString()
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
