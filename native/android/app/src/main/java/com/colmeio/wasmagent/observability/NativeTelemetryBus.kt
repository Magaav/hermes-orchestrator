package com.colmeio.wasmagent.observability

import android.content.Context
import android.util.Log
import java.net.URLEncoder
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString

object NativeTelemetryBus {
    private const val LOG_TAG = "NativeTelemetryBus"
    private const val WAO_VERSION = 1
    private const val WAO_TLV_NULL = 0
    private const val WAO_TLV_BOOL = 1
    private const val WAO_TLV_I64 = 2
    private const val WAO_TLV_F64 = 3
    private const val WAO_TLV_UTF8 = 4
    private const val WAO_TLV_JSON = 6
    private const val FRAME_HELLO = 1
    private const val FRAME_EVENT = 3
    private const val FRAME_STATE_PATCH = 4
    private const val FRAME_HEARTBEAT = 10
    private const val FIELD_DEVICE_ID = 1
    private const val FIELD_STREAM = 2
    private const val FIELD_TYPE = 3
    private const val FIELD_KEY = 4
    private const val FIELD_TS_MS = 5
    private const val FIELD_PAYLOAD_JSON = 12
    private const val FIELD_ROUTE = 14
    private const val FIELD_BUILD_ID = 15
    private const val FIELD_RUNTIME = 17
    private const val FIELD_TOPICS = 22
    private const val FIELD_ROLE = 28
    private const val RING_LIMIT = 96

    private val client = OkHttpClient.Builder()
        .pingInterval(10, TimeUnit.SECONDS)
        .build()
    private val executor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "native-telemetry-bus").apply { isDaemon = true }
    }
    private val seq = AtomicLong(1)
    private val pending = ArrayDeque<ByteArray>()
    private val lock = Any()
    @Volatile private var socket: WebSocket? = null
    @Volatile private var connected: Boolean = false
    @Volatile private var deviceId: String = ""
    @Volatile private var origin: String = ""
    @Volatile private var buildId: String = ""

    fun start(context: Context, backendOrigin: String, nativeDeviceId: String, nativeBuildId: String) {
        val cleanOrigin = backendOrigin.trim().trimEnd('/')
        if (!cleanOrigin.startsWith("https://") && !cleanOrigin.startsWith("http://")) return
        if (cleanOrigin == origin && nativeDeviceId == deviceId && socket != null) return
        origin = cleanOrigin
        deviceId = nativeDeviceId
        buildId = nativeBuildId
        executor.execute {
            try {
                socket?.close(1000, "restart")
                connected = false
                val request = Request.Builder()
                    .url(obsUrl(cleanOrigin, nativeDeviceId))
                    .header("Origin", cleanOrigin)
                    .header("X-Wasm-Agent-Native-Device-Id", nativeDeviceId)
                    .header("X-Wasm-Agent-Native-Runtime", "android-service")
                    .build()
                socket = client.newWebSocket(request, listener(context.applicationContext))
            } catch (error: Exception) {
                Log.w(LOG_TAG, "connect_failed ${error.javaClass.simpleName}")
            }
        }
    }

    fun stop() {
        executor.execute {
            connected = false
            socket?.close(1000, "stop")
            socket = null
        }
    }

    fun heartbeat() {
        send(FRAME_HEARTBEAT, mapOf(
            FIELD_DEVICE_ID to deviceId,
            FIELD_BUILD_ID to buildId,
            FIELD_ROUTE to origin,
            FIELD_RUNTIME to "android-service",
            FIELD_TS_MS to System.currentTimeMillis(),
            FIELD_PAYLOAD_JSON to JsonPayload(mapOf(
                "platform" to "android",
                "runtime" to "foreground_voice_wake_service",
            )),
        ))
    }

    fun publishWakeState(
        reason: String,
        inferenceCount: Long,
        confidence: Double,
        maxConfidence: Double,
        threshold: Double,
        thresholdCrossed: Boolean,
        detected: Boolean,
        wakeHitCount: Long,
        audioPeak: Int,
        audioRms: Double,
        rejectionReason: String,
    ) {
        val payload = JsonPayload(mapOf(
            "schema" to "hermes.wasm_agent.android.wake.compact_state.v1",
            "reason" to reason,
            "inference_count" to inferenceCount,
            "last_confidence" to confidence,
            "max_observed_confidence" to maxConfidence,
            "threshold" to threshold,
            "threshold_crossed" to thresholdCrossed,
            "detected" to detected,
            "wake_hit_count" to wakeHitCount,
            "audio_peak" to audioPeak,
            "audio_rms" to audioRms,
            "rejection_reason" to rejectionReason,
        ))
        send(FRAME_STATE_PATCH, mapOf(
            FIELD_DEVICE_ID to deviceId,
            FIELD_STREAM to "wake",
            FIELD_TYPE to "state",
            FIELD_KEY to "wake.latest",
            FIELD_TS_MS to System.currentTimeMillis(),
            FIELD_PAYLOAD_JSON to payload,
        ))
    }

    fun publishWakeHit(confidence: Double, wakeHitCount: Long) {
        send(FRAME_EVENT, mapOf(
            FIELD_DEVICE_ID to deviceId,
            FIELD_STREAM to "wake",
            FIELD_TYPE to "wake_hit",
            FIELD_KEY to "wake.last_hit",
            FIELD_TS_MS to System.currentTimeMillis(),
            FIELD_PAYLOAD_JSON to JsonPayload(mapOf(
                "schema" to "hermes.wasm_agent.android.wake.hit.v1",
                "confidence" to confidence,
                "wake_hit_count" to wakeHitCount,
            )),
        ))
    }

    fun publishPolicy(reason: String, threshold: Double, vadRms: Double, vadPeak: Int) {
        send(FRAME_EVENT, mapOf(
            FIELD_DEVICE_ID to deviceId,
            FIELD_STREAM to "wake",
            FIELD_TYPE to "policy",
            FIELD_KEY to "wake.policy",
            FIELD_TS_MS to System.currentTimeMillis(),
            FIELD_PAYLOAD_JSON to JsonPayload(mapOf(
                "schema" to "hermes.wasm_agent.android.wake.policy.v1",
                "reason" to reason,
                "threshold" to threshold,
                "vad_rms_threshold" to vadRms,
                "vad_peak_threshold" to vadPeak,
            )),
        ))
    }

    private fun listener(context: Context): WebSocketListener = object : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            connected = true
            send(FRAME_HELLO, mapOf(
                FIELD_DEVICE_ID to deviceId,
                FIELD_ROLE to "android-service",
                FIELD_TOPICS to "wake,android.audio,errors",
                FIELD_BUILD_ID to buildId,
                FIELD_ROUTE to origin,
                FIELD_RUNTIME to "android-service",
                FIELD_PAYLOAD_JSON to JsonPayload(mapOf(
                    "schema" to "hermes.wasm_agent.android.telemetry_bus.v1",
                    "package" to context.packageName,
                )),
            ), bypassQueue = true)
            heartbeat()
            flushPending(webSocket)
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            connected = false
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            connected = false
            Log.w(LOG_TAG, "socket_failed ${t.javaClass.simpleName}")
        }
    }

    private fun send(frameType: Int, fields: Map<Int, Any?>, bypassQueue: Boolean = false) {
        if (deviceId.isBlank() && frameType != FRAME_HELLO) return
        val frame = encodeFrame(frameType, fields)
        executor.execute {
            val current = socket
            if (connected && current != null && current.send(frame.toByteString())) return@execute
            if (!bypassQueue) {
                synchronized(lock) {
                    pending.addLast(frame)
                    while (pending.size > RING_LIMIT) pending.removeFirst()
                }
            }
        }
    }

    private fun flushPending(webSocket: WebSocket) {
        val frames = mutableListOf<ByteArray>()
        synchronized(lock) {
            while (pending.isNotEmpty()) frames.add(pending.removeFirst())
        }
        frames.forEach { webSocket.send(it.toByteString()) }
    }

    private fun encodeFrame(frameType: Int, fields: Map<Int, Any?>): ByteArray {
        val payload = encodeTlv(fields)
        val buffer = ByteBuffer.allocate(40 + payload.size).order(ByteOrder.LITTLE_ENDIAN)
        buffer.put(byteArrayOf('W'.code.toByte(), 'A'.code.toByte(), 'O'.code.toByte(), '1'.code.toByte()))
        buffer.put(WAO_VERSION.toByte())
        buffer.put(frameType.toByte())
        buffer.putShort(0.toShort())
        buffer.putInt(0)
        buffer.putInt(0)
        buffer.putLong(seq.getAndIncrement())
        buffer.putLong(0)
        buffer.putLong(System.nanoTime() / 1_000_000L)
        buffer.put(payload)
        return buffer.array()
    }

    private fun encodeTlv(fields: Map<Int, Any?>): ByteArray {
        val chunks = fields.mapNotNull { (fieldId, value) ->
            val encoded = encodeValue(value) ?: return@mapNotNull null
            val header = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
                .putShort(fieldId.toShort())
                .put(encoded.first.toByte())
                .put(0.toByte())
                .putInt(encoded.second.size)
                .array()
            header + encoded.second
        }
        return ByteArray(chunks.sumOf { it.size }).also { output ->
            var offset = 0
            for (chunk in chunks) {
                chunk.copyInto(output, offset)
                offset += chunk.size
            }
        }
    }

    private fun encodeValue(value: Any?): Pair<Int, ByteArray>? = when (value) {
        null -> WAO_TLV_NULL to ByteArray(0)
        is Boolean -> WAO_TLV_BOOL to byteArrayOf((if (value) 1 else 0).toByte())
        is Int -> WAO_TLV_I64 to ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN).putLong(value.toLong()).array()
        is Long -> WAO_TLV_I64 to ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN).putLong(value).array()
        is Float -> WAO_TLV_F64 to ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN).putDouble(value.toDouble()).array()
        is Double -> WAO_TLV_F64 to ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN).putDouble(value).array()
        is JsonPayload -> WAO_TLV_JSON to jsonBytes(value.fields)
        is String -> WAO_TLV_UTF8 to value.toByteArray(Charsets.UTF_8)
        else -> WAO_TLV_UTF8 to value.toString().toByteArray(Charsets.UTF_8)
    }

    private fun obsUrl(origin: String, nativeDeviceId: String): String {
        val wsOrigin = origin
            .replaceFirst("https://", "wss://")
            .replaceFirst("http://", "ws://")
            .trimEnd('/')
        val encodedDevice = URLEncoder.encode(nativeDeviceId, "UTF-8")
        return "$wsOrigin/native/obs/v1?device_id=$encodedDevice&role=android-service&topics=wake,android.audio,errors"
    }

    private fun jsonBytes(fields: Map<String, Any?>): ByteArray = buildString {
        append('{')
        fields.entries.forEachIndexed { index, entry ->
            if (index > 0) append(',')
            append('"').append(escapeJson(entry.key)).append('"').append(':')
            appendJsonValue(entry.value)
        }
        append('}')
    }.toByteArray(Charsets.UTF_8)

    private fun StringBuilder.appendJsonValue(value: Any?) {
        when (value) {
            null -> append("null")
            is Boolean -> append(if (value) "true" else "false")
            is Number -> append(if (value.toDouble().isFinite()) value.toString() else "null")
            else -> append('"').append(escapeJson(value.toString())).append('"')
        }
    }

    private fun escapeJson(value: String): String = buildString {
        value.forEach { char ->
            when (char) {
                '\\' -> append("\\\\")
                '"' -> append("\\\"")
                '\n' -> append("\\n")
                '\r' -> append("\\r")
                '\t' -> append("\\t")
                else -> append(char)
            }
        }
    }

    private data class JsonPayload(val fields: Map<String, Any?>)
}
