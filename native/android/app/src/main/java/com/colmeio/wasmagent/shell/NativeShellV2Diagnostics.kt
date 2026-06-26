package com.colmeio.wasmagent.shell

import org.json.JSONArray
import org.json.JSONObject

class NativeShellV2Diagnostics(private val maxEvents: Int = 80) {
    val activityCreatedAt: Long = System.currentTimeMillis()
    @Volatile var firstLoadUrlAt: Long = 0L
        private set
    @Volatile var pageStartedAt: Long = 0L
        private set
    @Volatile var pageCommitVisibleAt: Long = 0L
        private set
    @Volatile var pageFinishedAt: Long = 0L
        private set
    @Volatile var rendererReadyAt: Long = 0L
        private set
    @Volatile var currentUrl: String = ""
        private set

    private val events = ArrayDeque<JSONObject>()

    @Synchronized
    fun markLoadUrl(url: String) {
        if (firstLoadUrlAt == 0L) firstLoadUrlAt = System.currentTimeMillis()
        currentUrl = url
        record("webview_load_url", JSONObject()
            .put("url", url)
            .put("delta_ms", firstLoadUrlAt - activityCreatedAt))
    }

    @Synchronized
    fun markPageStarted(url: String) {
        pageStartedAt = System.currentTimeMillis()
        currentUrl = url
        record("page_started", JSONObject().put("url", url))
    }

    @Synchronized
    fun markPageCommitVisible(url: String) {
        pageCommitVisibleAt = System.currentTimeMillis()
        currentUrl = url
        record("page_commit_visible", JSONObject().put("url", url))
    }

    @Synchronized
    fun markPageFinished(url: String) {
        pageFinishedAt = System.currentTimeMillis()
        currentUrl = url
        record("page_finished", JSONObject().put("url", url))
    }

    @Synchronized
    fun markRendererReady(payload: JSONObject) {
        if (rendererReadyAt == 0L) rendererReadyAt = System.currentTimeMillis()
        record("renderer_app_ready", payload)
    }

    @Synchronized
    fun record(kind: String, payload: JSONObject = JSONObject()) {
        events.addLast(JSONObject()
            .put("at", System.currentTimeMillis())
            .put("kind", kind.take(120))
            .put("payload", payload))
        while (events.size > maxEvents) events.removeFirst()
    }

    @Synchronized
    fun snapshot(config: NativeShellV2Config): JSONObject {
        return JSONObject()
            .put("schema", "hermes.wasm_agent.android_shell_v2.runtime.v1")
            .put("shell", NativeShellV2Config.SHELL_NAME)
            .put("origin", config.origin)
            .put("current_url", currentUrl)
            .put("activity_created_at", activityCreatedAt)
            .put("first_load_url_at", nullIfZero(firstLoadUrlAt))
            .put("first_load_url_delta_ms", delta(firstLoadUrlAt, activityCreatedAt))
            .put("page_started_at", nullIfZero(pageStartedAt))
            .put("page_commit_visible_at", nullIfZero(pageCommitVisibleAt))
            .put("page_finished_at", nullIfZero(pageFinishedAt))
            .put("renderer_ready_at", nullIfZero(rendererReadyAt))
            .put("startup_contract", config.startupContract())
            .put("events", JSONArray(events))
    }

    private fun nullIfZero(value: Long): Any {
        return if (value > 0L) value else JSONObject.NULL
    }

    private fun delta(value: Long, base: Long): Any {
        return if (value > 0L && base > 0L) value - base else JSONObject.NULL
    }
}
