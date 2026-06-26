package com.colmeio.wasmagent.shell

import android.net.Uri
import android.webkit.WebView
import org.json.JSONObject

object NativeShellV2WakeForeground {
    private const val DISPATCH_DEBOUNCE_MS = 1_200L
    @Volatile private var lastDispatchAt: Long = 0L

    fun isWakeUri(uri: Uri): Boolean =
        uri.scheme == "https" &&
            uri.host == "wa.colmeio.com" &&
            uri.getQueryParameter("native_screen") == "wake-word" &&
            uri.getQueryParameter("wake_source") == "hermes_voice_wake"

    fun dispatch(webView: WebView?, diagnostics: NativeShellV2Diagnostics, uri: Uri) {
        val now = System.currentTimeMillis()
        if (now - lastDispatchAt < DISPATCH_DEBOUNCE_MS) {
            diagnostics.record("wake_foreground_event_debounced", JSONObject().put("delta_ms", now - lastDispatchAt))
            return
        }
        lastDispatchAt = now
        val payload = JSONObject()
            .put("native_screen", "wake-word")
            .put("wake_source", "hermes_voice_wake")
            .put("wake_confidence", uri.getQueryParameter("wake_confidence").orEmpty())
            .put("received_at", now)
        diagnostics.record("wake_foreground_event_dispatched", payload)
        webView?.evaluateJavascript("""
            (() => {
              const detail = $payload;
              window.__wasmAgentLastNativeWake = detail;
              window.dispatchEvent(new CustomEvent('wasm-agent:native-wake-detected', { detail }));
              return true;
            })();
        """.trimIndent(), null)
    }
}
