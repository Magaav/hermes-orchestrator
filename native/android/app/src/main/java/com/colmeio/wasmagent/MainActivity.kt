package com.colmeio.wasmagent

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.KeyEvent
import android.view.ViewGroup
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.TextView
import androidx.browser.customtabs.CustomTabsIntent
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

class MainActivity : Activity() {
    private lateinit var container: FrameLayout
    private var webView: WebView? = null
    private var selectedOrigin: String = ""
    private val candidates = listOf(
        "https://wa.colmeio.com",
        "http://10.0.2.2:8877",
        "http://127.0.0.1:8877"
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        container = FrameLayout(this)
        setContentView(container)
        showStatus("Finding wasm-agent...")
        resolveBackend()
    }

    override fun onBackPressed() {
        val current = webView
        if (current?.canGoBack() == true) {
            current.goBack()
            return
        }
        super.onBackPressed()
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        if (keyCode == KeyEvent.KEYCODE_R && event.isCtrlPressed) {
            if (event.isShiftPressed) {
                webView?.clearCache(true)
            }
            webView?.reload()
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

    private fun resolveBackend() {
        thread(name = "wasm-agent-origin-probe") {
            val selected = candidates.firstOrNull { candidate -> identifiesWasmAgent(candidate) }
            runOnUiThread {
                if (selected == null) {
                    showStatus("No validated wasm-agent backend found.")
                } else {
                    selectedOrigin = selected
                    openRemotePwaInBrowserHost(selected)
                }
            }
        }
    }

    private fun identifiesWasmAgent(origin: String): Boolean {
        return listOf("/config.json", "/health", "/healthz").any { path ->
            try {
                val connection = URL(origin.trimEnd('/') + path).openConnection() as HttpURLConnection
                connection.connectTimeout = 1200
                connection.readTimeout = 1200
                connection.requestMethod = "GET"
                connection.setRequestProperty("X-Wasm-Agent-Native-Probe", "wasm-agent")
                val body = connection.inputStream.bufferedReader().use { it.readText() }.lowercase()
                connection.responseCode in 200..299 &&
                    !body.contains("colmeio admin") &&
                    !body.contains("google_login_client_id") &&
                    (body.contains("\"appid\"") && body.contains("wasm-agent") ||
                        body.contains("\"service\"") && body.contains("wasm-agent") ||
                        body.contains("\"name\"") && body.contains("wasm-agent"))
            } catch (_: Exception) {
                false
            }
        }
    }

    private fun pwaHomeUrl(origin: String): String = origin.trimEnd('/') + "/home"

    private fun openRemotePwaInBrowserHost(origin: String) {
        val appUrl = pwaHomeUrl(origin)
        try {
            CustomTabsIntent.Builder()
                .setShowTitle(true)
                .build()
                .launchUrl(this, Uri.parse(appUrl))
            showStatus("Opened wasm-agent in a browser-compatible session.\n\nReturn here to retry or use WebView fallback.")
        } catch (_: ActivityNotFoundException) {
            openRemotePwaWebView(origin)
        } catch (_: Exception) {
            openRemotePwaWebView(origin)
        }
    }

    private fun openRemotePwaWebView(origin: String) {
        val view = WebView(this)
        webView = view
        view.layoutParams = FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT
        )
        view.settings.javaScriptEnabled = true
        view.settings.domStorageEnabled = true
        view.settings.databaseEnabled = true
        view.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean = false
        }
        container.removeAllViews()
        container.addView(view)
        view.loadUrl(pwaHomeUrl(origin))
    }

    private fun retrySelectedOrResolve() {
        if (selectedOrigin.isNotBlank()) {
            openRemotePwaInBrowserHost(selectedOrigin)
            return
        }
        showStatus("Finding wasm-agent...")
        resolveBackend()
    }

    private fun showStatus(message: String) {
        val status = TextView(this)
        status.text = "$message\n\nTap to retry. Long-press for WebView fallback."
        status.textSize = 16f
        status.setPadding(32, 32, 32, 32)
        status.setOnClickListener {
            retrySelectedOrResolve()
        }
        status.setOnLongClickListener {
            if (selectedOrigin.isNotBlank()) {
                openRemotePwaWebView(selectedOrigin)
                true
            } else {
                false
            }
        }
        container.removeAllViews()
        container.addView(status)
    }
}
