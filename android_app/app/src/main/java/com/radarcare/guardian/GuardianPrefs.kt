package com.radarcare.guardian

import android.content.Context

object GuardianPrefs {
    private const val PREFS = "guardian_prefs"
    private const val KEY_BACKEND_URL = "backend_url"
    private const val KEY_NOTIFIED_EVENTS = "notified_events"
    private const val DEFAULT_BACKEND_URL = "http://192.168.31.236:8081"

    fun getBackendUrl(context: Context): String {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_BACKEND_URL, DEFAULT_BACKEND_URL) ?: DEFAULT_BACKEND_URL
    }

    fun setBackendUrl(context: Context, value: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_BACKEND_URL, AlarmApiClient.normalizeBaseUrl(value))
            .apply()
    }

    fun getNotifiedEventKeys(context: Context): MutableSet<String> {
        val saved = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getStringSet(KEY_NOTIFIED_EVENTS, emptySet()) ?: emptySet()
        return saved.toMutableSet()
    }

    fun saveNotifiedEventKeys(context: Context, keys: Set<String>) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putStringSet(KEY_NOTIFIED_EVENTS, keys.toList().takeLast(120).toSet())
            .apply()
    }
}
