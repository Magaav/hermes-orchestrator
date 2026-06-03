package com.colmeio.wasmagent

import android.app.Service
import android.content.Intent
import android.os.IBinder

class WasmAgentForegroundService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null
}
