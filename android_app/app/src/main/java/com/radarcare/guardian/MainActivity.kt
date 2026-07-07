package com.radarcare.guardian

import android.Manifest
import android.app.Activity
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
    private val shieldBrand = Color.rgb(50, 91, 242)
    private val shieldBrandDark = Color.rgb(34, 46, 97)
    private val shieldSecondary = Color.rgb(121, 130, 166)
    private val shieldBg = Color.rgb(243, 246, 251)
    private val shieldCard = Color.WHITE
    private val shieldCardSoft = Color.rgb(248, 250, 255)
    private val shieldLine = Color.rgb(223, 229, 240)
    private val shieldDanger = Color.rgb(226, 55, 68)
    private val shieldSuccess = Color.rgb(39, 179, 106)

    private lateinit var backendInput: EditText
    private lateinit var modeText: TextView
    private lateinit var backendStatusText: TextView
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

    private var receiverRegistered = false
    private var backendOnline = false
    private var latestEmergencyEventId: Long? = null
    private var latestBackendData = BackendLiveData()

    private val statusReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action != GuardianMonitorService.ACTION_STATUS) return
            backendOnline = intent.getBooleanExtra(GuardianMonitorService.EXTRA_ONLINE, false)
            val message = intent.getStringExtra(GuardianMonitorService.EXTRA_MESSAGE).orEmpty()
            val alerts = intent.getStringExtra(GuardianMonitorService.EXTRA_ALERT_TEXT).orEmpty()
            latestBackendData = BackendLiveData(
                heartRate = intent.optionalDouble(GuardianMonitorService.EXTRA_HEART_RATE),
                breathRate = intent.optionalDouble(GuardianMonitorService.EXTRA_BREATH_RATE),
                targetDistanceMeters = intent.optionalDouble(GuardianMonitorService.EXTRA_TARGET_DISTANCE),
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

    private fun buildUi() {
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(22), dp(26), dp(22), dp(28))
            setBackgroundColor(shieldBg)
        }

        content.addView(TextView(this).apply {
            text = "Radar Care"
            textSize = 30f
            typeface = Typeface.DEFAULT_BOLD
            setTextColor(shieldBrandDark)
            letterSpacing = -0.02f
            setPadding(0, 0, 0, dp(2))
        })

        content.addView(TextView(this).apply {
            text = "多床位护理监护 App"
            textSize = 15f
            setTextColor(shieldSecondary)
            setPadding(0, 0, 0, dp(14))
        })

        modeText = TextView(this).apply {
            text = "未连接"
            textSize = 16f
            typeface = Typeface.DEFAULT_BOLD
            setTextColor(shieldBrandDark)
            setPadding(0, 0, 0, dp(14))
        }
        content.addView(modeText)

        backendInput = EditText(this).apply {
            hint = "后端地址，例如 http://192.168.31.236:8081"
            textSize = 16f
            setSingleLine(true)
            setText(GuardianPrefs.getBackendUrl(this@MainActivity))
            setTextColor(shieldBrandDark)
            setHintTextColor(shieldSecondary)
            setPadding(dp(16), dp(12), dp(16), dp(12))
            background = rounded(shieldCard, dp(18), shieldLine)
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
            setValue("后端", "轮询聚合")
        }))

        sectionTitle(content, "报警")
        alertText = TextView(this).apply {
            text = "暂无报警"
            textSize = 16f
            setTextColor(shieldBrandDark)
            setPadding(dp(16), dp(16), dp(16), dp(16))
            background = rounded(shieldCard, dp(20), shieldLine)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                elevation = dp(2).toFloat()
            }
        }
        content.addView(alertText, matchWrap())

        val scroll = ScrollView(this)
        scroll.addView(content)
        setContentView(scroll)
        updateModeText()
        updateMetricTiles()
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
        modeText.text = if (backendOnline) "后端监听" else "未连接"
    }

    private fun updateMetricTiles() {
        val data = latestBackendData
        heartTile.setValue(
            data.heartRate?.let { "${it.roundToInt()} BPM" } ?: "-- BPM",
            if (data.heartRate != null) "后端" else "等待数据"
        )
        breathTile.setValue(
            data.breathRate?.let { "${it.roundToInt()} RPM" } ?: "-- RPM",
            if (data.breathRate != null) "后端" else "等待数据"
        )
        distanceTile.setValue(
            data.targetDistanceMeters?.let { String.format("%.2f m", it) } ?: "-- m",
            if (data.targetDistanceMeters != null) "后端" else "等待雷达数据"
        )
        radarStateTile.setValue(
            if (data.radarOnline) "后端在线" else "离线",
            "后端雷达：${if (data.radarOnline) "在线" else "离线"}"
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
        backendStatusText.setTextColor(if (online) shieldSuccess else shieldDanger)
    }

    private fun requestRuntimePermissionsIfNeeded() {
        val permissions = mutableListOf<String>()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            permissions.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        if (permissions.isNotEmpty()) {
            requestPermissions(permissions.distinct().toTypedArray(), REQUEST_PERMISSIONS)
        }
    }

    private fun statusText(text: String): TextView {
        return TextView(this).apply {
            this.text = text
            textSize = 15f
            setTextColor(shieldSecondary)
            setPadding(dp(14), dp(10), dp(14), dp(10))
            background = rounded(shieldCardSoft, dp(18), shieldLine)
        }
    }

    private fun sectionTitle(root: LinearLayout, text: String) {
        root.addView(TextView(this).apply {
            this.text = text
            textSize = 19f
            typeface = Typeface.DEFAULT_BOLD
            setTextColor(shieldBrandDark)
            letterSpacing = -0.01f
            setPadding(0, dp(18), 0, dp(10))
        })
    }

    private fun button(text: String, onClick: () -> Unit): Button {
        return Button(this).apply {
            this.text = text
            textSize = 15f
            setAllCaps(false)
            setTextColor(Color.WHITE)
            typeface = Typeface.DEFAULT_BOLD
            minHeight = dp(46)
            background = rounded(shieldBrand, dp(23), shieldBrand)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                elevation = dp(2).toFloat()
                stateListAnimator = null
            }
            setOnClickListener { onClick() }
        }
    }

    private fun metricTile(title: String): MetricTile {
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), dp(14), dp(14), dp(14))
            minimumHeight = dp(118)
            background = rounded(shieldCard, dp(20), shieldLine)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                elevation = dp(2).toFloat()
            }
        }
        val titleView = TextView(this).apply {
            text = title
            textSize = 13f
            typeface = Typeface.DEFAULT_BOLD
            setTextColor(shieldSecondary)
        }
        val valueView = TextView(this).apply {
            text = "--"
            textSize = 23f
            typeface = Typeface.DEFAULT_BOLD
            setTextColor(shieldBrandDark)
            setPadding(0, dp(8), 0, dp(4))
        }
        val hintView = TextView(this).apply {
            text = "等待数据"
            textSize = 12f
            setTextColor(shieldSecondary)
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
    }
}
