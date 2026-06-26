package com.radarcare.guardian

import android.Manifest
import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import kotlin.math.roundToInt

class MainActivity : Activity() {
    private lateinit var backendInput: EditText
    private lateinit var modeText: TextView
    private lateinit var backendStatusText: TextView
    private lateinit var bleStatusText: TextView
    private lateinit var alertText: TextView
    private lateinit var resolveButton: Button

    private lateinit var heartTile: MetricTile
    private lateinit var breathTile: MetricTile
    private lateinit var distanceTile: MetricTile
    private lateinit var radarStateTile: MetricTile
    private lateinit var tempTile: MetricTile
    private lateinit var humidityTile: MetricTile
    private lateinit var snoreStateTile: MetricTile
    private lateinit var snoreScoreTile: MetricTile
    private lateinit var snoreDbfsTile: MetricTile

    private lateinit var bleClient: RadarBleClient
    private var receiverRegistered = false
    private var backendOnline = false
    private var latestEmergencyEventId: Long? = null
    private var latestBackendData = BackendLiveData()
    private var latestBleStatus: RadarBleStatus? = null

    private val statusReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action != GuardianMonitorService.ACTION_STATUS) return
            backendOnline = intent.getBooleanExtra(GuardianMonitorService.EXTRA_ONLINE, false)
            val message = intent.getStringExtra(GuardianMonitorService.EXTRA_MESSAGE).orEmpty()
            val alerts = intent.getStringExtra(GuardianMonitorService.EXTRA_ALERT_TEXT).orEmpty()
            latestBackendData = BackendLiveData(
                heartRate = intent.optionalDouble(GuardianMonitorService.EXTRA_HEART_RATE),
                breathRate = intent.optionalDouble(GuardianMonitorService.EXTRA_BREATH_RATE),
                temperatureC = intent.optionalDouble(GuardianMonitorService.EXTRA_TEMPERATURE_C),
                humidityPct = intent.optionalDouble(GuardianMonitorService.EXTRA_HUMIDITY_PCT),
                snoreScore = intent.optionalDouble(GuardianMonitorService.EXTRA_SNORE_SCORE),
                snoreDbfs = intent.optionalDouble(GuardianMonitorService.EXTRA_SNORE_DBFS),
                radarOnline = intent.getBooleanExtra(GuardianMonitorService.EXTRA_RADAR_ONLINE, false),
                snoreOnline = intent.getBooleanExtra(GuardianMonitorService.EXTRA_SNORE_ONLINE, false),
                snoreDetected = intent.getBooleanExtra(GuardianMonitorService.EXTRA_SNORE_DETECTED, false),
                environmentOnline = intent.getBooleanExtra(GuardianMonitorService.EXTRA_ENVIRONMENT_ONLINE, false),
                emergencyActive = intent.getBooleanExtra(GuardianMonitorService.EXTRA_EMERGENCY_ACTIVE, false)
            )
            setBackendStatus(message, backendOnline)
            alertText.text = alerts.ifBlank { "暂无 active critical 报警" }
            updateModeText()
            updateMetricTiles()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        bleClient = RadarBleClient(this, bleListener)
        buildUi()
        requestRuntimePermissionsIfNeeded()
    }

    override fun onStart() {
        super.onStart()
        val filter = IntentFilter(GuardianMonitorService.ACTION_STATUS)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(statusReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            registerReceiver(statusReceiver, filter)
        }
        receiverRegistered = true
        refreshNow()
    }

    override fun onStop() {
        if (receiverRegistered) {
            unregisterReceiver(statusReceiver)
            receiverRegistered = false
        }
        super.onStop()
    }

    override fun onDestroy() {
        bleClient.disconnect()
        super.onDestroy()
    }

    private val bleListener = object : RadarBleClient.Listener {
        override fun onBleMessage(message: String) {
            setBleStatus(message, bleClient.isConnected())
        }

        override fun onDeviceFound(name: String, address: String) {
            setBleStatus("已发现：$name ($address)", false)
        }

        override fun onConnected() {
            setBleStatus("蓝牙雷达已连接", true)
            showBleNotification("雷达蓝牙已连接")
            updateModeText()
        }

        override fun onDisconnected(message: String) {
            latestBleStatus = null
            setBleStatus(message, false)
            cancelBleNotification()
            updateModeText()
            updateMetricTiles()
        }

        override fun onStatus(status: RadarBleStatus) {
            latestBleStatus = status
            setBleStatus("蓝牙雷达已连接 · ${status.statusText()}", true)
            updateModeText()
            updateMetricTiles()
        }
    }

    private fun buildUi() {
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(20), dp(18), dp(24))
            setBackgroundColor(Color.rgb(246, 248, 250))
        }

        content.addView(TextView(this).apply {
            text = "睡眠监护 App"
            textSize = 26f
            typeface = Typeface.DEFAULT_BOLD
            setTextColor(Color.rgb(20, 30, 45))
            setPadding(0, 0, 0, dp(6))
        })

        modeText = TextView(this).apply {
            text = "未连接"
            textSize = 16f
            typeface = Typeface.DEFAULT_BOLD
            setTextColor(Color.rgb(50, 70, 95))
            setPadding(0, 0, 0, dp(14))
        }
        content.addView(modeText)

        backendInput = EditText(this).apply {
            hint = "后端地址，例如 http://192.168.0.102:8081"
            textSize = 16f
            setSingleLine(true)
            setText(GuardianPrefs.getBackendUrl(this@MainActivity))
        }
        content.addView(backendInput, matchWrap())

        backendStatusText = statusText("后端未连接")
        content.addView(backendStatusText)

        val backendButtons = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(8), 0, dp(8))
        }
        backendButtons.addView(button("保存地址") { saveBackendUrl() }, weightButton())
        backendButtons.addView(button("开始监听") { startMonitor() }, weightButton())
        backendButtons.addView(button("停止") { stopMonitor() }, weightButton())
        content.addView(backendButtons)

        val backendButtons2 = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, 0, 0, dp(12))
        }
        backendButtons2.addView(button("刷新") { refreshNow() }, weightButton())
        resolveButton = button("已处理") { resolveEmergency() }
        resolveButton.isEnabled = false
        backendButtons2.addView(resolveButton, weightButton())
        content.addView(backendButtons2)

        sectionTitle(content, "蓝牙雷达")
        bleStatusText = statusText("蓝牙未连接")
        content.addView(bleStatusText)

        val bleButtons1 = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(8), 0, dp(8))
        }
        bleButtons1.addView(button("扫描雷达") { scanRadar() }, weightButton())
        bleButtons1.addView(button("连接") { bleClient.connectLastDevice() }, weightButton())
        bleButtons1.addView(button("断开") { bleClient.disconnect() }, weightButton())
        content.addView(bleButtons1)

        val bleButtons2 = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, 0, 0, dp(12))
        }
        bleButtons2.addView(button("暂停雷达") { bleClient.pauseRadarTx() }, weightButton())
        bleButtons2.addView(button("恢复雷达") { bleClient.resumeRadarTx() }, weightButton())
        content.addView(bleButtons2)

        sectionTitle(content, "实时数据")
        heartTile = metricTile("心率")
        breathTile = metricTile("呼吸率")
        distanceTile = metricTile("目标距离")
        radarStateTile = metricTile("雷达状态")
        tempTile = metricTile("温度")
        humidityTile = metricTile("湿度")
        snoreStateTile = metricTile("打鼾情况")
        snoreScoreTile = metricTile("呼噜分数")
        snoreDbfsTile = metricTile("环境声音")

        content.addView(metricRow(heartTile, breathTile))
        content.addView(metricRow(distanceTile, radarStateTile))
        content.addView(metricRow(tempTile, humidityTile))
        content.addView(metricRow(snoreStateTile, snoreScoreTile))
        content.addView(metricRow(snoreDbfsTile, metricTile("数据来源").apply {
            setValue("后端 / 蓝牙", "自动优先显示可用数据")
        }))

        sectionTitle(content, "报警")
        alertText = TextView(this).apply {
            text = "暂无报警"
            textSize = 16f
            setTextColor(Color.rgb(30, 40, 55))
            setPadding(dp(14), dp(14), dp(14), dp(14))
            background = rounded(Color.WHITE, dp(12), Color.rgb(225, 230, 238))
        }
        content.addView(alertText, matchWrap())

        val scroll = ScrollView(this)
        scroll.addView(content)
        setContentView(scroll)
        updateModeText()
        updateMetricTiles()
    }

    private fun scanRadar() {
        if (!bleClient.hasRequiredPermissions()) {
            requestRuntimePermissionsIfNeeded()
            toast("请允许蓝牙权限后再次扫描")
            return
        }
        bleClient.startScan()
    }

    private fun saveBackendUrl() {
        val normalized = AlarmApiClient.normalizeBaseUrl(backendInput.text.toString())
        GuardianPrefs.setBackendUrl(this, normalized)
        backendInput.setText(normalized)
        toast("后端地址已保存")
        refreshNow()
    }

    private fun startMonitor() {
        saveBackendUrl()
        GuardianMonitorService.start(this)
        setBackendStatus("看护监听中", true)
        updateModeText()
    }

    private fun stopMonitor() {
        GuardianMonitorService.stop(this)
        backendOnline = false
        setBackendStatus("已停止监听", false)
        updateModeText()
    }

    private fun refreshNow() {
        Thread {
            val result = AlarmApiClient.fetchOverview(GuardianPrefs.getBackendUrl(this))
            latestEmergencyEventId = result.alerts.firstOrNull { it.canResolveEmergency() }?.eventId
            val text = result.alerts.joinToString("\n\n") { it.displayLine() }
            runOnUiThread {
                backendOnline = result.ok
                latestBackendData = result.liveData
                setBackendStatus(result.message, result.ok)
                alertText.text = text.ifBlank { "暂无 active critical 报警" }
                resolveButton.isEnabled = latestEmergencyEventId != null
                updateModeText()
                updateMetricTiles()
            }
        }.start()
    }

    private fun resolveEmergency() {
        val eventId = latestEmergencyEventId
        Thread {
            val (ok, message) = AlarmApiClient.resolveEmergency(GuardianPrefs.getBackendUrl(this), eventId)
            runOnUiThread {
                toast(message)
                if (ok) refreshNow()
            }
        }.start()
    }

    private fun updateModeText() {
        val bleConnected = latestBleStatus != null && bleClient.isConnected()
        modeText.text = when {
            bleConnected && backendOnline -> "双模式运行中：蓝牙雷达 + 后端监听"
            bleConnected -> "蓝牙雷达"
            backendOnline -> "后端监听"
            else -> "未连接"
        }
    }

    private fun updateMetricTiles() {
        val ble = latestBleStatus
        val heart = ble?.heartRate ?: latestBackendData.heartRate
        val breath = ble?.breathRate ?: latestBackendData.breathRate
        val heartSource = if (ble?.heartRate != null) "蓝牙雷达" else if (latestBackendData.heartRate != null) "后端" else "等待数据"
        val breathSource = if (ble?.breathRate != null) "蓝牙雷达" else if (latestBackendData.breathRate != null) "后端" else "等待数据"

        heartTile.setValue(heart?.let { "${it.roundToInt()} BPM" } ?: "-- BPM", heartSource)
        breathTile.setValue(breath?.let { "${it.roundToInt()} RPM" } ?: "-- RPM", breathSource)
        distanceTile.setValue(
            ble?.distanceMeters?.let { String.format("%.2f m", it) } ?: "-- m",
            if (ble?.distanceMeters != null) "蓝牙雷达" else "等待蓝牙数据"
        )
        radarStateTile.setValue(
            when {
                ble == null -> if (latestBackendData.radarOnline) "后端在线" else "离线"
                ble.boardStill -> "静止"
                else -> "未静止"
            },
            ble?.statusText() ?: "后端雷达：${if (latestBackendData.radarOnline) "在线" else "离线"}"
        )
        tempTile.setValue(
            latestBackendData.temperatureC?.let { String.format("%.1f °C", it) } ?: "-- °C",
            if (latestBackendData.environmentOnline) "环境板在线" else "等待温湿度"
        )
        humidityTile.setValue(
            latestBackendData.humidityPct?.let { String.format("%.0f %%RH", it) } ?: "-- %RH",
            if (latestBackendData.environmentOnline) "环境板在线" else "等待温湿度"
        )
        snoreStateTile.setValue(
            when {
                !latestBackendData.snoreOnline -> "离线"
                latestBackendData.snoreDetected -> "正在打鼾"
                else -> "未检测到"
            },
            if (latestBackendData.snoreOnline) "呼噜守护在线" else "等待呼噜心跳"
        )
        snoreScoreTile.setValue(
            latestBackendData.snoreScore?.let { String.format("%.2f", it) } ?: "--",
            if (latestBackendData.snoreOnline) "呼噜守护在线" else "等待呼噜数据"
        )
        snoreDbfsTile.setValue(
            latestBackendData.snoreDbfs?.let { String.format("%.1f dBFS", it) } ?: "-- dBFS",
            if (latestBackendData.snoreDbfs != null) "后端汇聚" else "等待分贝数据"
        )
    }

    private fun setBackendStatus(message: String, online: Boolean) {
        backendStatusText.text = "后端：$message"
        backendStatusText.setTextColor(if (online) Color.rgb(20, 130, 75) else Color.rgb(190, 55, 45))
    }

    private fun setBleStatus(message: String, online: Boolean) {
        bleStatusText.text = "蓝牙：$message"
        bleStatusText.setTextColor(if (online) Color.rgb(20, 130, 75) else Color.rgb(90, 100, 115))
    }

    private fun showBleNotification(text: String) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            return
        }
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channel = NotificationChannel(
            BLE_CHANNEL_ID,
            "雷达蓝牙",
            NotificationManager.IMPORTANCE_LOW
        )
        manager.createNotificationChannel(channel)
        val intent = Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        val pendingIntent = PendingIntent.getActivity(
            this,
            1,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notification = Notification.Builder(this, BLE_CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
            .setContentTitle("雷达蓝牙直连")
            .setContentText(text)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .build()
        manager.notify(BLE_NOTIFICATION_ID, notification)
    }

    private fun cancelBleNotification() {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.cancel(BLE_NOTIFICATION_ID)
    }

    private fun requestRuntimePermissionsIfNeeded() {
        val permissions = mutableListOf<String>()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            permissions.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        permissions.addAll(bleClient.requiredPermissions().filter {
            checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED
        })
        if (permissions.isNotEmpty()) {
            requestPermissions(permissions.distinct().toTypedArray(), REQUEST_PERMISSIONS)
        }
    }

    private fun statusText(text: String): TextView {
        return TextView(this).apply {
            this.text = text
            textSize = 15f
            setTextColor(Color.rgb(90, 100, 115))
            setPadding(0, dp(8), 0, dp(8))
        }
    }

    private fun sectionTitle(root: LinearLayout, text: String) {
        root.addView(TextView(this).apply {
            this.text = text
            textSize = 19f
            typeface = Typeface.DEFAULT_BOLD
            setTextColor(Color.rgb(20, 30, 45))
            setPadding(0, dp(14), 0, dp(8))
        })
    }

    private fun button(text: String, onClick: () -> Unit): Button {
        return Button(this).apply {
            this.text = text
            textSize = 15f
            setAllCaps(false)
            setOnClickListener { onClick() }
        }
    }

    private fun metricTile(title: String): MetricTile {
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12), dp(12), dp(12), dp(12))
            background = rounded(Color.WHITE, dp(12), Color.rgb(225, 230, 238))
        }
        val titleView = TextView(this).apply {
            text = title
            textSize = 13f
            setTextColor(Color.rgb(95, 105, 120))
        }
        val valueView = TextView(this).apply {
            text = "--"
            textSize = 22f
            typeface = Typeface.DEFAULT_BOLD
            setTextColor(Color.rgb(20, 30, 45))
            setPadding(0, dp(5), 0, dp(3))
        }
        val hintView = TextView(this).apply {
            text = "等待数据"
            textSize = 12f
            setTextColor(Color.rgb(105, 115, 130))
        }
        container.addView(titleView)
        container.addView(valueView)
        container.addView(hintView)
        return MetricTile(container, valueView, hintView)
    }

    private fun metricRow(left: MetricTile, right: MetricTile): LinearLayout {
        return LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, 0, 0, dp(10))
            addView(left.container, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply {
                marginEnd = dp(6)
            })
            addView(right.container, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply {
                marginStart = dp(6)
            })
        }
    }

    private fun rounded(fill: Int, radius: Int, stroke: Int): GradientDrawable {
        return GradientDrawable().apply {
            setColor(fill)
            cornerRadius = radius.toFloat()
            setStroke(1, stroke)
        }
    }

    private fun toast(text: String) {
        Toast.makeText(this, text, Toast.LENGTH_SHORT).show()
    }

    private fun Intent.optionalDouble(name: String): Double? {
        if (!hasExtra(name)) return null
        val value = getDoubleExtra(name, Double.NaN)
        return if (value.isNaN()) null else value
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private fun matchWrap(): LinearLayout.LayoutParams {
        return LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        )
    }

    private fun weightButton(): LinearLayout.LayoutParams {
        return LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply {
            marginEnd = dp(6)
        }
    }

    private data class MetricTile(
        val container: LinearLayout,
        val valueView: TextView,
        val hintView: TextView
    ) {
        fun setValue(value: String, hint: String) {
            valueView.text = value
            hintView.text = hint
        }
    }

    companion object {
        private const val REQUEST_PERMISSIONS = 42
        private const val BLE_CHANNEL_ID = "radar_ble"
        private const val BLE_NOTIFICATION_ID = 3001
    }
}
