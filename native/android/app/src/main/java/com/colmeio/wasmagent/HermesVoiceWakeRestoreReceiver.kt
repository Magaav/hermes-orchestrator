package com.colmeio.wasmagent

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

class HermesVoiceWakeRestoreReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action.orEmpty()
        if (action !in RESTORE_ACTIONS) return
        try {
            HermesVoiceWakeService.restoreIfEnabled(context, action)
        } catch (error: Exception) {
            Log.w("HermesVoiceWake", "voice_wake_restore_failed action=$action error=${error.javaClass.simpleName}")
        }
    }

    companion object {
        private val RESTORE_ACTIONS = setOf(
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_MY_PACKAGE_REPLACED,
            Intent.ACTION_USER_UNLOCKED,
        )
    }
}
