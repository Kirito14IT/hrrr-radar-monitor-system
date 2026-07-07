package com.radarcare.guardian

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.os.Build
import android.os.IBinder
import android.os.SystemClock
import android.provider.Settings

class GuardianMonitorService : Service() {
    @Volatile private var running = false
    private var worker: Thread? = null

    override fun onCreate() {
        super.onCreate()
        createChannels()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(MONITOR_NOTIFICATION_ID, monitorNotification("看护监听中"))
        if (!running) {
            running = true
            worker = Thread(::monitorLoop, "guardian-monitor").also { it.start() }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        worker?.interrupt()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun monitorLoop() {
        val notified = GuardianPrefs.getNotifiedEventKeys(this)
        while (running) {
            val baseUrl = GuardianPrefs.getBackendUrl(this)
            val result = AlarmApiClient.fetchOverview(baseUrl)
            sendStatusBroadcast(result)

            if (result.ok) {
                for (alert in result.alerts) {
                    if (notified.add(alert.key)) {
                        GuardianPrefs.saveNotifiedEventKeys(this, notified)
                        notifyAlarm(alert)
                    }
                }
            }
            updateMonitorNotification(result.message)
            SystemClock.sleep(POLL_INTERVAL_MS)
        }
    }

    private fun sendStatusBroadcast(result: OverviewResult) {
        val alertText = result.alerts.joinToString("\n\n") { it.displayLine() }
        val data = result.liveData
        sendBroadcast(Intent(ACTION_STATUS).apply {
            setPackage(packageName)
            putExtra(EXTRA_ONLINE, result.ok)
            putExtra(EXTRA_MESSAGE, result.message)
            putExtra(EXTRA_ALERT_TEXT, alertText)
            putExtra(EXTRA_ALERT_COUNT, result.alerts.size)
            putNullableDouble(EXTRA_HEART_RATE, data.heartRate)
            putNullableDouble(EXTRA_BREATH_RATE, data.breathRate)
            putNullableDouble(EXTRA_TARGET_DISTANCE, data.targetDistanceMeters)
            putNullableDouble(EXTRA_TEMPERATURE_C, data.temperatureC)
            putNullableDouble(EXTRA_HUMIDITY_PCT, data.humidityPct)
            putNullableDouble(EXTRA_SNORE_SCORE, data.snoreScore)
            putNullableDouble(EXTRA_SNORE_DBFS, data.snoreDbfs)
            putExtra(EXTRA_RADAR_ONLINE, data.radarOnline)
            putExtra(EXTRA_SNORE_ONLINE, data.snoreOnline)
            putExtra(EXTRA_SNORE_DETECTED, data.snoreDetected)
            putExtra(EXTRA_ENVIRONMENT_ONLINE, data.environmentOnline)
            putExtra(EXTRA_EMERGENCY_ACTIVE, data.emergencyActive)
            putExtra(EXTRA_DATA_TEXT, data.summaryText())
        })
    }

    private fun updateMonitorNotification(text: String) {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(MONITOR_NOTIFICATION_ID, monitorNotification(text))
    }

    private fun monitorNotification(text: String): Notification {
        return Notification.Builder(this, CHANNEL_MONITOR)
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentTitle("睡眠看护监听")
            .setContentText(text)
            .setContentIntent(openAppIntent())
            .setOngoing(true)
            .build()
    }

    private fun notifyAlarm(alert: AlertEvent) {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val notification = Notification.Builder(this, CHANNEL_ALARM)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle(alert.title)
            .setContentText(alert.message)
            .setStyle(Notification.BigTextStyle().bigText(alert.displayLine()))
            .setContentIntent(openAppIntent())
            .setAutoCancel(true)
            .setPriority(Notification.PRIORITY_MAX)
            .build()
        manager.notify(ALARM_NOTIFICATION_BASE_ID + (alert.key.hashCode() and 0x0fff), notification)
    }

    private fun openAppIntent(): PendingIntent {
        val intent = Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        return PendingIntent.getActivity(
            this,
            0,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
    }

    private fun createChannels() {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val monitor = NotificationChannel(
            CHANNEL_MONITOR,
            "看护监听",
            NotificationManager.IMPORTANCE_LOW
        )
        val alarm = NotificationChannel(
            CHANNEL_ALARM,
            "紧急报警",
            NotificationManager.IMPORTANCE_HIGH
        ).apply {
            enableVibration(true)
            setSound(
                Settings.System.DEFAULT_ALARM_ALERT_URI,
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ALARM)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build()
            )
        }
        manager.createNotificationChannel(monitor)
        manager.createNotificationChannel(alarm)
    }

    private fun Intent.putNullableDouble(name: String, value: Double?) {
        putExtra(name, value ?: Double.NaN)
    }

    companion object {
        const val ACTION_STATUS = "com.radarcare.guardian.MONITOR_STATUS"
        const val EXTRA_ONLINE = "online"
        const val EXTRA_MESSAGE = "message"
        const val EXTRA_ALERT_TEXT = "alert_text"
        const val EXTRA_ALERT_COUNT = "alert_count"
        const val EXTRA_HEART_RATE = "heart_rate"
        const val EXTRA_BREATH_RATE = "breath_rate"
        const val EXTRA_TARGET_DISTANCE = "target_distance"
        const val EXTRA_TEMPERATURE_C = "temperature_c"
        const val EXTRA_HUMIDITY_PCT = "humidity_pct"
        const val EXTRA_SNORE_SCORE = "snore_score"
        const val EXTRA_SNORE_DBFS = "snore_dbfs"
        const val EXTRA_RADAR_ONLINE = "radar_online"
        const val EXTRA_SNORE_ONLINE = "snore_online"
        const val EXTRA_SNORE_DETECTED = "snore_detected"
        const val EXTRA_ENVIRONMENT_ONLINE = "environment_online"
        const val EXTRA_EMERGENCY_ACTIVE = "emergency_active"
        const val EXTRA_DATA_TEXT = "data_text"

        private const val POLL_INTERVAL_MS = 5000L
        private const val CHANNEL_MONITOR = "guardian_monitor"
        private const val CHANNEL_ALARM = "guardian_alarm"
        private const val MONITOR_NOTIFICATION_ID = 1001
        private const val ALARM_NOTIFICATION_BASE_ID = 2000

        fun start(context: Context) {
            val intent = Intent(context, GuardianMonitorService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, GuardianMonitorService::class.java))
        }
    }
}
