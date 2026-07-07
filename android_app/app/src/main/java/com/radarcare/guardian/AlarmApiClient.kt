package com.radarcare.guardian

import org.json.JSONArray
import org.json.JSONObject
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import kotlin.math.roundToInt

data class AlertEvent(
    val key: String,
    val eventId: Long?,
    val type: String,
    val severity: String,
    val status: String,
    val title: String,
    val message: String,
    val source: String,
    val timestamp: String
) {
    fun isActiveCritical(): Boolean {
        if (status.isNotBlank() && status != "active") return false
        if (severity != "critical") return false
        return type == "emergency_voice" || type == "suspected_apnea" || type.contains("emergency")
    }

    fun canResolveEmergency(): Boolean {
        return status == "active" && (type == "emergency_voice" || type.contains("emergency"))
    }

    fun displayLine(): String {
        val time = if (timestamp.isBlank()) "--" else timestamp.replace('T', ' ')
        return "[$time] $title\n$message\n来源：$source"
    }
}

data class BackendLiveData(
    val heartRate: Double? = null,
    val breathRate: Double? = null,
    val targetDistanceMeters: Double? = null,
    val temperatureC: Double? = null,
    val humidityPct: Double? = null,
    val snoreScore: Double? = null,
    val snoreDbfs: Double? = null,
    val snoreLevel: Double? = null,
    val snoreDetected: Boolean = false,
    val radarOnline: Boolean = false,
    val snoreOnline: Boolean = false,
    val environmentOnline: Boolean = false,
    val emergencyActive: Boolean = false,
    val updatedAt: String = ""
) {
    fun summaryText(): String {
        val heart = heartRate?.let { "${it.roundToInt()} BPM" } ?: "-- BPM"
        val breath = breathRate?.let { "${it.roundToInt()} RPM" } ?: "-- RPM"
        val temp = temperatureC?.let { String.format("%.1f °C", it) } ?: "-- °C"
        val humidity = humidityPct?.let { String.format("%.0f %%RH", it) } ?: "-- %RH"
        val snore = snoreScore?.let { String.format("%.2f", it) } ?: "--"
        val dbfs = snoreDbfs?.let { String.format("%.1f dBFS", it) } ?: "-- dBFS"
        return "心率 $heart · 呼吸 $breath\n温湿度 $temp / $humidity\n呼噜 $snore · $dbfs"
    }
}

data class OverviewResult(
    val ok: Boolean,
    val message: String,
    val alerts: List<AlertEvent>,
    val liveData: BackendLiveData = BackendLiveData()
)

object AlarmApiClient {
    fun normalizeBaseUrl(raw: String): String {
        val trimmed = raw.trim().trimEnd('/')
        if (trimmed.isBlank()) return ""
        return if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
            trimmed
        } else {
            "http://$trimmed"
        }
    }

    fun fetchOverview(baseUrl: String): OverviewResult {
        val base = normalizeBaseUrl(baseUrl)
        if (base.isBlank()) {
            return OverviewResult(false, "请先填写后端地址", emptyList())
        }

        return try {
            val overview = getJson("$base/sleep/overview?mode=live&seconds=1800")
            val status = runCatching { getJson("$base/status") }.getOrNull()
            val alerts = parseAlerts(overview)
            val liveData = parseLiveData(overview, status)
            OverviewResult(
                ok = true,
                message = "后端已连接，当前紧急报警 ${alerts.size} 条",
                alerts = alerts,
                liveData = liveData
            )
        } catch (exc: Exception) {
            OverviewResult(
                ok = false,
                message = "连接失败：${exc.message ?: exc.javaClass.simpleName}",
                alerts = emptyList()
            )
        }
    }

    fun resolveEmergency(baseUrl: String, eventId: Long?): Pair<Boolean, String> {
        val base = normalizeBaseUrl(baseUrl)
        if (base.isBlank()) return false to "请先填写后端地址"

        return try {
            val payload = JSONObject().apply {
                put("source", "android_guardian_app")
                put("resolved_by", "Android 监护人 App")
                put("resolution_note", "手机端确认处理")
                if (eventId != null) put("event_id", eventId)
            }
            val conn = (URL("$base/emergency/resolve").openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 5000
                readTimeout = 5000
                doOutput = true
                setRequestProperty("Content-Type", "application/json;charset=utf-8")
            }
            OutputStreamWriter(conn.outputStream, Charsets.UTF_8).use { it.write(payload.toString()) }
            val code = conn.responseCode
            val body = readBody(conn, code)
            conn.disconnect()

            val status = runCatching { JSONObject(body).optString("status") }.getOrDefault("")
            if (code in 200..299 && status == "success") {
                true to "紧急状态已处理"
            } else {
                false to "处理失败：$body"
            }
        } catch (exc: Exception) {
            false to "处理失败：${exc.message ?: exc.javaClass.simpleName}"
        }
    }

    private fun getJson(url: String): JSONObject {
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 5000
            readTimeout = 5000
        }
        val code = conn.responseCode
        val body = readBody(conn, code)
        conn.disconnect()
        if (code !in 200..299) {
            throw IllegalStateException("后端返回 $code: $body")
        }
        return JSONObject(body)
    }

    private fun readBody(conn: HttpURLConnection, code: Int): String {
        return if (code in 200..299) {
            conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } else {
            conn.errorStream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
        }
    }

    private fun parseAlerts(root: JSONObject): List<AlertEvent> {
        val events = root.optJSONArray("events") ?: JSONArray()
        val alerts = mutableListOf<AlertEvent>()
        for (index in 0 until events.length()) {
            val event = events.optJSONObject(index) ?: continue
            val type = event.optString("type", event.optString("event_type", ""))
            val severity = event.optString("severity", "")
            val status = event.optString("status", "active")
            val eventId = if (event.has("eventID") && !event.isNull("eventID")) event.optLong("eventID") else null
            val fingerprint = event.optString("fingerprint", "")
            val key = when {
                fingerprint.isNotBlank() -> fingerprint
                eventId != null -> "event:$eventId"
                else -> "${type}:${event.optString("timestamp", "")}:${event.optString("title", "")}"
            }
            val alert = AlertEvent(
                key = key,
                eventId = eventId,
                type = type,
                severity = severity,
                status = status,
                title = event.optString("title", fallbackTitle(type)),
                message = event.optString("message", "检测到需要关注的看护事件"),
                source = event.optString("source", "--"),
                timestamp = event.optString("timestamp", "")
            )
            if (alert.isActiveCritical()) alerts.add(alert)
        }
        return alerts
    }

    private fun parseLiveData(overview: JSONObject, status: JSONObject?): BackendLiveData {
        val devices = overview.optJSONObject("devices") ?: JSONObject()
        val stats = overview.optJSONObject("stats") ?: JSONObject()
        val source = status ?: JSONObject()

        val heart = source.optNullableDouble("heart_rate")
            ?: stats.optNullableDouble("avg_heart_rate")
        val breath = source.optNullableDouble("breath_rate")
            ?: stats.optNullableDouble("avg_breath_rate")
        val temperature = source.optNullableDouble("temperature_c")
            ?: devices.optNullableDouble("temperature_c")
            ?: stats.optNullableDouble("avg_temperature_c")
        val humidity = source.optNullableDouble("humidity_pct")
            ?: devices.optNullableDouble("humidity_pct")
            ?: stats.optNullableDouble("avg_humidity_pct")
        val snoreScore = source.optNullableDouble("snore_score")
            ?: source.optNullableDouble("snore_level")
            ?: stats.optNullableDouble("avg_snore_level")
        val snoreLevel = source.optNullableDouble("snore_level")
            ?: stats.optNullableDouble("avg_snore_level")

        return BackendLiveData(
            heartRate = heart,
            breathRate = breath,
            targetDistanceMeters = source.optNullableDouble("target_distance"),
            temperatureC = temperature,
            humidityPct = humidity,
            snoreScore = snoreScore,
            snoreDbfs = source.optNullableDouble("snore_dbfs"),
            snoreLevel = snoreLevel,
            snoreDetected = source.optBoolean("snore_detected", devices.optBoolean("snore_detected", false)),
            radarOnline = source.optBoolean("radar_online", devices.optBoolean("radar_board_online", false)),
            snoreOnline = source.optBoolean("snore_board_online", devices.optBoolean("snore_board_online", false)),
            environmentOnline = source.optBoolean("environment_online", devices.optBoolean("environment_board_online", false)),
            emergencyActive = source.optBoolean("emergency_active", devices.optBoolean("emergency_active", false)),
            updatedAt = source.optString("generated_at", overview.optString("generated_at", ""))
        )
    }

    private fun JSONObject.optNullableDouble(name: String): Double? {
        if (!has(name) || isNull(name)) return null
        return runCatching { getDouble(name) }.getOrNull()
    }

    private fun fallbackTitle(type: String): String {
        return when (type) {
            "emergency_voice" -> "语音紧急求助"
            "suspected_apnea" -> "疑似呼吸暂停"
            else -> "看护报警"
        }
    }
}
