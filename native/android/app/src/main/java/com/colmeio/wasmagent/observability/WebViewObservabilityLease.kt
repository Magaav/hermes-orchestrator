package com.colmeio.wasmagent.observability

import android.app.Activity
import android.os.Handler
import android.os.Looper
import android.webkit.WebView
import org.json.JSONObject

object WebViewObservabilityLease {
        private const val MIN_LEASE_MS = 5_000L
        private const val MAX_LEASE_MS = 120_000L
    private val handler = Handler(Looper.getMainLooper())
    @Volatile private var expiresAt = 0L
    private val expire = Runnable { disableInternal() }

    fun execute(activity: Activity, operation: String, payload: JSONObject): JSONObject = when (operation) {
        "observability_enable" -> enable(activity, payload)
        "observability_disable" -> disable(activity)
        "observability_status", "observability_collect" -> status()
        else -> JSONObject().put("ok", false).put("error", "unsupported_observability_operation")
    }

    private fun enable(activity: Activity, payload: JSONObject): JSONObject {
        val requested = payload.optLong("lease_ms", 30_000L)
        val leaseMs = requested.coerceIn(MIN_LEASE_MS, MAX_LEASE_MS)
        activity.runOnUiThread {
            handler.removeCallbacks(expire)
            WebView.setWebContentsDebuggingEnabled(true)
            expiresAt = System.currentTimeMillis() + leaseMs
            handler.postDelayed(expire, leaseMs)
        }
        return status(leaseMs, true)
    }

    private fun disable(activity: Activity): JSONObject {
        activity.runOnUiThread { disableInternal() }
        return status(0L, false)
    }

    private fun status(): JSONObject {
        val remaining = (expiresAt - System.currentTimeMillis()).coerceAtLeast(0L)
        return status(remaining, remaining > 0L)
    }

    private fun disableInternal() {
        handler.removeCallbacks(expire)
        WebView.setWebContentsDebuggingEnabled(false)
        expiresAt = 0L
    }

    private fun status(remainingMs: Long, active: Boolean) = JSONObject()
        .put("ok", true)
        .put("schema", "hermes.wasm_agent.android_observability_lease.v1")
        .put("active", active)
        .put("remaining_ms", remainingMs)
        .put("transport", "android.webview.devtools_socket")
        .put("public_debug_port", false)
        .put("retention", "none")
}
