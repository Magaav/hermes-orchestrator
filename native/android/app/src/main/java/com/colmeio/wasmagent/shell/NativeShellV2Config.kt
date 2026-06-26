package com.colmeio.wasmagent.shell

import android.net.Uri
import com.colmeio.wasmagent.BuildConfig
import org.json.JSONArray
import org.json.JSONObject

data class NativeShellV2Config(
    val origin: String,
    val buildId: String,
    val generatedAt: String,
    val authSessionId: String,
    val installDeviceHash: String,
) {
    fun homeUrl(): String {
        return Uri.parse("${origin.trimEnd('/')}/home").buildUpon()
            .appendQueryParameter("native", "android")
            .appendQueryParameter("shell", SHELL_NAME)
            .appendQueryParameter("android_shell", SHELL_NAME)
            .appendQueryParameter("android_runtime", "user-full")
            .appendQueryParameter("android_startup", "instant-v2")
            .appendQueryParameter("wake", "off")
            .appendQueryParameter("bridgeDiagnostics", "off")
            .appendQueryParameter("healthProbes", "off")
            .appendQueryParameter("nativeControl", "off")
            .appendQueryParameter("buildId", buildId)
            .appendQueryParameter("webBuildHint", generatedAt)
            .appendQueryParameter("android_auth_session", authSessionId)
            .appendQueryParameter("install_device_hash", installDeviceHash)
            .build()
            .toString()
    }

    fun shellInfo(): JSONObject {
        return JSONObject()
            .put("schema", "hermes.wasm_agent.android_shell_v2.config.v1")
            .put("shell", SHELL_NAME)
            .put("origin", origin)
            .put("start_url", homeUrl())
            .put("build_id", buildId)
            .put("generated_at", generatedAt)
            .put("android_auth_session", authSessionId)
            .put("install_device_hash", installDeviceHash)
            .put("startup_contract", startupContract())
            .put("capabilities", JSONArray(CAPABILITIES))
            .put("disabled_layers", JSONArray(DISABLED_LAYERS))
    }

    fun startupContract(): JSONObject {
        return JSONObject()
            .put("blocks_before_load_url", 0)
            .put("backend_probe_before_load_url", false)
            .put("wake_before_load_url", false)
            .put("diagnostics_upload_before_load_url", false)
            .put("native_control_polling_before_load_url", false)
            .put("release_feed_before_load_url", false)
            .put("first_layer", "webview_launch_only")
    }

    companion object {
        const val SHELL_NAME = "android-webview-v2"

        val CAPABILITIES = listOf(
            "native.capabilities.webViewBridge.v1",
            "native.capabilities.statusBus.v1",
            "native.capabilities.crashSafeStatus.v1",
            "native.capabilities.capabilityManifest.v1",
        )

        val DISABLED_LAYERS = listOf(
            "wake",
            "voice_tuning",
            "native_control_polling",
            "downloaded_runtime_sync",
            "diagnostics_upload",
            "backend_probe_gate",
        )

        fun production(authSessionId: String, installDeviceHash: String): NativeShellV2Config {
            val origin = BuildConfig.DEFAULT_SERVER_URL.trim().trimEnd('/')
            require(origin == "https://wa.colmeio.com") {
                "NativeShellV2 production origin must be https://wa.colmeio.com"
            }
            return NativeShellV2Config(
                origin = origin,
                buildId = BuildConfig.NATIVE_BUILD_ID,
                generatedAt = BuildConfig.BUILD_GENERATED_AT,
                authSessionId = authSessionId,
                installDeviceHash = installDeviceHash,
            )
        }
    }
}
