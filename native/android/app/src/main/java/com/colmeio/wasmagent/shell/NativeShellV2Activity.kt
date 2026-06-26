package com.colmeio.wasmagent.shell

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.view.MotionEvent
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import com.colmeio.wasmagent.BuildConfig
import com.colmeio.wasmagent.HermesVoiceWakeService
import com.colmeio.wasmagent.NativeBridgeContract
import org.json.JSONObject
import java.util.UUID

class NativeShellV2Activity : Activity() {
    companion object { private const val VOICE_WAKE_UI_ACTIVE_WINDOW_MS = 4_000L; private const val VOICE_WAKE_UI_MARK_THROTTLE_MS = 650L }
    private lateinit var root: FrameLayout
    private lateinit var diagnostics: NativeShellV2Diagnostics
    private lateinit var config: NativeShellV2Config
    private var webView: WebView? = null
    private var pendingWakeForegroundUri: Uri? = null
    @Volatile private var lastVoiceWakeUiActivityMarkAt: Long = 0L

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        diagnostics = NativeShellV2Diagnostics()
        config = NativeShellV2Config.production(authSessionId = stableId("android_auth_session"), installDeviceHash = stableId("install_device_hash"))
        window.statusBarColor = Color.BLACK
        window.navigationBarColor = Color.BLACK
        root = FrameLayout(this).apply { setBackgroundColor(Color.BLACK) }
        val view = createWebView()
        webView = view
        root.addView(view, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        setContentView(root)
        val url = initialLaunchUrl(intent?.data)
        diagnostics.markLoadUrl(url)
        view.loadUrl(url)
        NativeShellV2WakeIntent.handle(this, config, diagnostics, intent)
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIncomingUri(intent?.data)
        NativeShellV2WakeIntent.handle(this, config, diagnostics, intent)
    }

    override fun onBackPressed() {
        val view = webView
        if (view?.canGoBack() == true) view.goBack()
        else super.onBackPressed()
    }

    override fun dispatchTouchEvent(event: MotionEvent?): Boolean {
        if (event?.actionMasked == MotionEvent.ACTION_DOWN || event?.actionMasked == MotionEvent.ACTION_MOVE) {
            markVoiceWakeUiActivity("shell_v2_touch")
        }
        return super.dispatchTouchEvent(event)
    }

    override fun onDestroy() {
        val view = webView
        webView = null
        if (view != null) {
            root.removeView(view)
            view.stopLoading()
            view.destroy()
        }
        super.onDestroy()
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun createWebView(): WebView {
        WebView.setWebContentsDebuggingEnabled(BuildConfig.ALLOW_LOCAL_DEV)
        val bridge = NativeShellV2Bridge(activity = this, config = config, diagnostics = diagnostics, webViewProvider = { webView })
        return WebView(this).apply {
            setBackgroundColor(Color.BLACK)
            isFocusable = true
            isFocusableInTouchMode = true
            settings.apply {
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
                mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                userAgentString = "$userAgentString WASMAgentAndroid/${BuildConfig.NATIVE_BUILD_ID} shell/${NativeShellV2Config.SHELL_NAME}"
            }
            CookieManager.getInstance().setAcceptCookie(true)
            CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)
            addJavascriptInterface(bridge, "wasmAgentAndroid")
            addJavascriptInterface(bridge, NativeBridgeContract.GENERAL_BRIDGE_OBJECT)
            addJavascriptInterface(bridge, "WasmAgentNative")
            webViewClient = shellWebViewClient()
        }
    }

    private fun shellWebViewClient(): WebViewClient {
        return object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                return handleNavigationUri(request.url)
            }

            @Deprecated("Deprecated in Java")
            override fun shouldOverrideUrlLoading(view: WebView, url: String): Boolean {
                return handleNavigationUri(Uri.parse(url))
            }

            override fun onPageStarted(view: WebView, url: String, favicon: android.graphics.Bitmap?) = diagnostics.markPageStarted(url)

            override fun onPageCommitVisible(view: WebView, url: String) = diagnostics.markPageCommitVisible(url)

            override fun onPageFinished(view: WebView, url: String) {
                diagnostics.markPageFinished(url)
                pendingWakeForegroundUri?.let {
                    pendingWakeForegroundUri = null
                    NativeShellV2WakeForeground.dispatch(view, diagnostics, it)
                }
            }
        }
    }

    private fun handleIncomingUri(uri: Uri?) {
        if (uri == null) return
        diagnostics.record("incoming_intent", JSONObject()
            .put("scheme", uri.scheme.orEmpty())
            .put("host", uri.host.orEmpty())
            .put("path", uri.path.orEmpty()))
        if (NativeShellV2WakeForeground.isWakeUri(uri)) {
            NativeShellV2WakeForeground.dispatch(webView, diagnostics, uri)
            return
        }
        if (isAllowedAppUri(uri)) webView?.loadUrl(uri.toString())
    }

    private fun initialLaunchUrl(uri: Uri?): String {
        if (uri != null && NativeShellV2WakeForeground.isWakeUri(uri)) {
            diagnostics.record("initial_wake_foreground_intent", JSONObject().put("uri", uri.toString().take(300)))
            pendingWakeForegroundUri = uri
            return config.homeUrl()
        }
        if (uri != null && isAllowedAppUri(uri)) {
            diagnostics.record("initial_launch_uri", JSONObject().put("uri", uri.toString().take(300)))
            return uri.toString()
        }
        return config.homeUrl()
    }

    private fun handleNavigationUri(uri: Uri): Boolean {
        if (isAllowedAppUri(uri)) return false
        if (uri.scheme == "wasm-agent" && uri.host == "android-auth-return") {
            diagnostics.record("auth_return_not_yet_wired", JSONObject()
                .put("uri", uri.toString().take(300)))
            webView?.loadUrl(config.homeUrl())
            return true
        }
        openExternal(uri)
        return true
    }

    private fun isAllowedAppUri(uri: Uri): Boolean {
        return uri.scheme == "https" && uri.host == "wa.colmeio.com"
    }

    private fun openExternal(uri: Uri) {
        diagnostics.record("external_navigation", JSONObject()
            .put("uri", uri.toString().take(300)))
        runCatching {
            startActivity(Intent(Intent.ACTION_VIEW, uri))
        }.onFailure {
            diagnostics.record("external_navigation_failed", JSONObject()
                .put("error", it.javaClass.simpleName))
        }
    }

    private fun markVoiceWakeUiActivity(reason: String) {
        val now = System.currentTimeMillis()
        if (now - lastVoiceWakeUiActivityMarkAt < VOICE_WAKE_UI_MARK_THROTTLE_MS) return
        lastVoiceWakeUiActivityMarkAt = now
        getSharedPreferences(HermesVoiceWakeService.PREFS_NAME, MODE_PRIVATE)
            .edit()
            .putLong(HermesVoiceWakeService.PREF_FOREGROUND_UI_ACTIVE_UNTIL, now + VOICE_WAKE_UI_ACTIVE_WINDOW_MS)
            .apply()
        diagnostics.record("voice_wake_ui_activity_marked", JSONObject()
            .put("reason", reason)
            .put("active_for_ms", VOICE_WAKE_UI_ACTIVE_WINDOW_MS))
    }

    private fun stableId(name: String): String {
        val prefs = getSharedPreferences("wasm_agent_shell_v2", MODE_PRIVATE)
        val existing = prefs.getString(name, "").orEmpty()
        if (existing.isNotBlank()) return existing
        val next = UUID.randomUUID().toString()
        prefs.edit().putString(name, next).apply()
        return next
    }
}
