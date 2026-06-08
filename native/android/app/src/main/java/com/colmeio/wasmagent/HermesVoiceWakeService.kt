package com.colmeio.wasmagent

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.AssetManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.IBinder
import com.colmeio.wasmagent.voice.AndroidSpeechRecognizerEngine
import com.colmeio.wasmagent.voice.OpenWakeWordOnnxEngine
import com.colmeio.wasmagent.voice.WakeWordResult
import com.colmeio.wasmagent.voice.VoiceWakeEvent
import com.colmeio.wasmagent.voice.VoiceWakeStateMachine
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID
import kotlin.concurrent.thread

class HermesVoiceWakeService : Service() {
    companion object {
        const val ACTION_START = "com.colmeio.wasmagent.voice.START"
        const val ACTION_STOP = "com.colmeio.wasmagent.voice.STOP"
        const val ACTION_STATUS = "com.colmeio.wasmagent.voice.STATUS"
        const val EXTRA_ORIGIN = "origin"
        const val PREFS_NAME = "wasm_agent_android_shell"
        const val PREF_ENABLED = "voice_wake_enabled"
        const val PREF_ORIGIN = "voice_wake_origin"
        private const val CHANNEL_ID = "wasm_agent_hermes_voice_wake"
        private const val NOTIFICATION_ID = 4721
        private const val MAX_CAPTURE_MS = 12_000L

        fun statusFile(context: Context): File = File(context.filesDir, "native-diagnostics/voice-wake.json")

        internal fun installBundledHermesModelIfPresent(
            modelFile: File,
            openAsset: (String) -> InputStream,
        ): Boolean {
            if (modelFile.exists()) return false
            return try {
                openAsset("voice/hermes.onnx").use { input ->
                    modelFile.parentFile?.mkdirs()
                    FileOutputStream(modelFile).use { output -> input.copyTo(output) }
                }
                true
            } catch (_: Exception) {
                false
            }
        }

        internal fun bundledHermesModelAvailable(assets: AssetManager): Boolean {
            return try {
                assets.open("voice/hermes.onnx").use { true }
            } catch (_: Exception) {
                false
            }
        }

        fun start(context: Context, origin: String) {
            val intent = Intent(context, HermesVoiceWakeService::class.java)
                .setAction(ACTION_START)
                .putExtra(EXTRA_ORIGIN, origin)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(intent) else context.startService(intent)
        }

        fun stop(context: Context) {
            context.startService(Intent(context, HermesVoiceWakeService::class.java).setAction(ACTION_STOP))
        }
    }

    private val machine = VoiceWakeStateMachine()
    @Volatile private var running = false
    @Volatile private var worker: Thread? = null
    private val hermesModelFile by lazy { File(filesDir, "voice/hermes.onnx") }
    @Volatile private var wakeEngine: OpenWakeWordOnnxEngine? = null
    private val transcriptionEngine by lazy { AndroidSpeechRecognizerEngine(this) }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopListening("user_disabled")
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_STATUS -> writeStatus()
            else -> startListening(intent?.getStringExtra(EXTRA_ORIGIN).orEmpty())
        }
        return START_STICKY
    }

    override fun onDestroy() {
        if (running) {
            stopListening("service_destroy")
        } else {
            writeStatus("service_destroy")
        }
        super.onDestroy()
    }

    private fun startListening(origin: String) {
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val selectedOrigin = origin.ifBlank { prefs.getString(PREF_ORIGIN, "").orEmpty() }.ifBlank { BuildConfig.DEFAULT_SERVER_URL }
        prefs.edit().putBoolean(PREF_ENABLED, true).putString(PREF_ORIGIN, selectedOrigin).apply()
        installBundledHermesModelIfPresent()
        var activeWakeEngine = refreshWakeEngine()
        if (!hasRecordAudioPermission()) {
            prefs.edit().putBoolean(PREF_ENABLED, false).apply()
            machine.fail("record_audio_permission_missing")
            writeStatus()
            stopSelf()
            return
        }
        if (running) {
            writeStatus()
            return
        }
        startForeground(NOTIFICATION_ID, notification("Listening for Hermes"))
        running = true
        machine.enable()
        if (!activeWakeEngine.ready) {
            machine.blocked(activeWakeEngine.diagnosticReason)
            writeStatus("Place a compatible Hermes raw-PCM ONNX wake model at files/voice/hermes.onnx or bundle assets/voice/hermes.onnx. Wake detection is not active until the model is ready.")
            worker = thread(name = "hermes-voice-wake-blocked") {
                while (running) {
                    Thread.sleep(15_000)
                    installBundledHermesModelIfPresent()
                    activeWakeEngine = refreshWakeEngine()
                    if (activeWakeEngine.ready) {
                        machine.enable()
                        writeStatus("wake_engine_ready")
                        listenLoop(selectedOrigin)
                        return@thread
                    }
                    machine.blocked(activeWakeEngine.diagnosticReason)
                    writeStatus("wake_engine_not_ready")
                }
            }
            return
        }
        writeStatus()
        worker = thread(name = "hermes-voice-wake-listener") {
            listenLoop(selectedOrigin)
        }
    }

    private fun stopListening(reason: String) {
        running = false
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit().putBoolean(PREF_ENABLED, false).apply()
        machine.disable()
        writeStatus(reason)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) stopForeground(STOP_FOREGROUND_REMOVE) else @Suppress("DEPRECATION") stopForeground(true)
    }

    private fun listenLoop(origin: String) {
        while (running) {
            val wake = listenForWake()
            if (wake == null || !running) continue
            val startedAt = System.currentTimeMillis()
            machine.beginTranscribing()
            writeStatus()
            val transcript = transcriptionEngine.transcribeLiveAfterWake(MAX_CAPTURE_MS)
            val endedAt = System.currentTimeMillis()
            if (transcript.transcript.isBlank()) {
                machine.fail(transcript.error.ifBlank { "transcription_empty" })
                writeStatus()
                machine.listenAgain()
                continue
            }
            val event = VoiceWakeEvent(
                transcript = transcript.transcript,
                confidence = minOf(wake.confidence, transcript.confidence).coerceIn(0.0, 1.0),
                startedAt = startedAt,
                endedAt = endedAt,
                buildId = BuildConfig.NATIVE_BUILD_ID,
                sessionId = UUID.randomUUID().toString(),
            )
            machine.complete(event)
            writeStatus()
            postVoiceEvent(origin, event)
            machine.listenAgain()
            writeStatus()
        }
    }

    private fun listenForWake(): WakeWordResult? {
        val minBuffer = AudioRecord.getMinBufferSize(
            OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        ).coerceAtLeast(OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ)
        val recorder = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            minBuffer,
        )
        try {
            recorder.startRecording()
            val buffer = ShortArray(1024)
            while (running) {
                val count = recorder.read(buffer, 0, buffer.size)
                if (count <= 0) continue
                val frame = buffer.copyOf(count)
                val wake = currentWakeEngine().processPcm16(frame, OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ)
                if (machine.onWake(wake)) {
                    writeStatus()
                    return wake
                }
            }
        } catch (error: Exception) {
            machine.fail(error.javaClass.simpleName)
            writeStatus()
        } finally {
            try {
                recorder.stop()
            } catch (_: Exception) {
            }
            recorder.release()
        }
        return null
    }

    private fun postVoiceEvent(origin: String, event: VoiceWakeEvent) {
        thread(name = "hermes-voice-wake-event") {
            try {
                val payload = event.toJson()
                    .put("kind", "voice_command")
                    .put("platform", "android")
                    .put("device_id", "android-${BuildConfig.NATIVE_BUILD_ID}")
                    .put("timestamp", System.currentTimeMillis())
                val connection = (URL(origin.trimEnd('/') + "/native/events").openConnection() as HttpURLConnection).apply {
                    connectTimeout = 3000
                    readTimeout = 3000
                    requestMethod = "POST"
                    setRequestProperty("Content-Type", "application/json; charset=utf-8")
                    doOutput = true
                }
                connection.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
                connection.inputStream.close()
                connection.disconnect()
            } catch (error: Exception) {
                machine.fail("voice_event_post_failed:${error.javaClass.simpleName}")
                writeStatus()
            }
        }
    }

    private fun writeStatus(reason: String = "") {
        val activeWakeEngine = currentWakeEngine()
        val status = machine.snapshot(
            enabled = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).getBoolean(PREF_ENABLED, false),
            permissionGranted = hasRecordAudioPermission(),
            foregroundServiceRunning = running,
            wakeEngine = activeWakeEngine.name,
            wakeEngineReady = activeWakeEngine.ready,
            transcriptionEngine = transcriptionEngine.name,
            batteryWarning = "Always-on microphone uses extra battery; disable Hermes Voice Wake when not needed.",
        )
            .put("reason", reason)
            .put("bundled_model_available", bundledHermesModelAvailable())
            .put("model_asset_found", bundledHermesModelAvailable())
            .put("onnx_runtime_available", activeWakeEngine.onnxRuntimeAvailable)
            .put("wake_model", activeWakeEngine.diagnostics())
        statusFile(this).apply {
            parentFile?.mkdirs()
            writeText(status.toString(2))
        }
    }

    private fun currentWakeEngine(): OpenWakeWordOnnxEngine =
        wakeEngine ?: refreshWakeEngine()

    private fun refreshWakeEngine(): OpenWakeWordOnnxEngine =
        OpenWakeWordOnnxEngine(hermesModelFile).also { wakeEngine = it }

    private fun installBundledHermesModelIfPresent() {
        installBundledHermesModelIfPresent(hermesModelFile) { path -> assets.open(path) }
    }

    private fun bundledHermesModelAvailable(): Boolean {
        return bundledHermesModelAvailable(assets)
    }

    private fun hasRecordAudioPermission(): Boolean {
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.M ||
            checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
    }

    private fun notification(text: String): Notification {
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        return builder
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("WASM Agent listening for Hermes")
            .setContentText(text)
            .setOngoing(true)
            .setContentIntent(PendingIntent.getActivity(
                this,
                0,
                Intent(this, MainActivity::class.java),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            ))
            .build()
    }

    override fun onCreate() {
        super.onCreate()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel(
                CHANNEL_ID,
                "Hermes Voice Wake",
                NotificationManager.IMPORTANCE_LOW,
            ))
        }
    }
}
