package com.radarcare.guardian

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothGattService
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.ParcelUuid
import java.util.UUID

data class RadarBleStatus(
    val version: Int,
    val flags: Int,
    val heartRate: Double?,
    val breathRate: Double?,
    val distanceMeters: Double?,
    val motionDelta: Int,
    val sequence: Long,
    val radarOnline: Boolean,
    val boardStill: Boolean,
    val personPresent: Boolean,
    val txEnabled: Boolean,
    val imuReady: Boolean
) {
    fun statusText(): String {
        val still = if (boardStill) "静止" else "未静止"
        val person = if (personPresent) "有人" else "无人/等待"
        val tx = if (txEnabled) "传输中" else "已暂停"
        return "$still · $person · $tx · 序号 $sequence"
    }
}

class RadarBleClient(
    private val context: Context,
    private val listener: Listener
) {
    interface Listener {
        fun onBleMessage(message: String)
        fun onDeviceFound(name: String, address: String)
        fun onConnected()
        fun onDisconnected(message: String)
        fun onStatus(status: RadarBleStatus)
    }

    private val mainHandler = Handler(Looper.getMainLooper())
    private val bluetoothManager = context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
    private val adapter: BluetoothAdapter? get() = bluetoothManager.adapter
    private val scanner get() = adapter?.bluetoothLeScanner

    private var scanning = false
    private var lastDevice: BluetoothDevice? = null
    private var gatt: BluetoothGatt? = null
    private var statusCharacteristic: BluetoothGattCharacteristic? = null
    private var controlCharacteristic: BluetoothGattCharacteristic? = null

    private val scanCallback = object : ScanCallback() {
        @SuppressLint("MissingPermission")
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            val device = result.device ?: return
            val advertisedName = result.scanRecord?.deviceName
            val deviceName = advertisedName ?: runCatching { device.name }.getOrNull().orEmpty()
            val matchesName = deviceName.startsWith("RadarCare", ignoreCase = true)
            val matchesService = result.scanRecord?.serviceUuids?.any { it.uuid == SERVICE_UUID } == true
            if (!matchesName && !matchesService) return

            lastDevice = device
            stopScan()
            post {
                listener.onDeviceFound(deviceName.ifBlank { "RadarCare" }, device.address)
                listener.onBleMessage("已发现雷达板：${deviceName.ifBlank { device.address }}")
            }
        }

        override fun onScanFailed(errorCode: Int) {
            scanning = false
            post { listener.onBleMessage("蓝牙扫描失败：$errorCode") }
        }
    }

    private val gattCallback = object : BluetoothGattCallback() {
        @SuppressLint("MissingPermission")
        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                this@RadarBleClient.gatt = gatt
                post {
                    listener.onConnected()
                    listener.onBleMessage("蓝牙雷达已连接，正在发现服务")
                }
                gatt.discoverServices()
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                cleanupGatt()
                post { listener.onDisconnected("蓝牙已断开") }
            }
        }

        @SuppressLint("MissingPermission")
        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            if (status != BluetoothGatt.GATT_SUCCESS) {
                post { listener.onBleMessage("发现服务失败：$status") }
                return
            }
            val service = gatt.getService(SERVICE_UUID)
            if (service == null) {
                post { listener.onBleMessage("未找到雷达 GATT 服务") }
                return
            }

            statusCharacteristic = service.getCharacteristic(STATUS_CHAR_UUID)
            controlCharacteristic = service.getCharacteristic(CONTROL_CHAR_UUID)
            val statusChar = statusCharacteristic
            if (statusChar == null) {
                post { listener.onBleMessage("未找到雷达状态特征") }
                return
            }

            enableNotifications(gatt, statusChar)
            gatt.readCharacteristic(statusChar)
            post { listener.onBleMessage("已订阅雷达状态通知") }
        }

        override fun onCharacteristicRead(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            status: Int
        ) {
            if (status == BluetoothGatt.GATT_SUCCESS && characteristic.uuid == STATUS_CHAR_UUID) {
                parseAndPublish(characteristic.value)
            }
        }

        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic
        ) {
            if (characteristic.uuid == STATUS_CHAR_UUID) {
                parseAndPublish(characteristic.value)
            }
        }

        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray
        ) {
            if (characteristic.uuid == STATUS_CHAR_UUID) {
                parseAndPublish(value)
            }
        }

        override fun onCharacteristicWrite(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            status: Int
        ) {
            val message = if (status == BluetoothGatt.GATT_SUCCESS) {
                "控制命令已发送"
            } else {
                "控制命令发送失败：$status"
            }
            post { listener.onBleMessage(message) }
        }
    }

    fun isConnected(): Boolean = gatt != null

    fun hasRequiredPermissions(): Boolean {
        return requiredPermissions().all {
            context.checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED
        }
    }

    fun requiredPermissions(): Array<String> {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
        } else {
            arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
        }
    }

    @SuppressLint("MissingPermission")
    fun startScan() {
        if (!hasRequiredPermissions()) {
            listener.onBleMessage("请先允许蓝牙权限")
            return
        }
        if (adapter?.isEnabled != true) {
            listener.onBleMessage("请先打开手机蓝牙")
            return
        }
        if (scanning) stopScan()

        lastDevice = null
        val filter = ScanFilter.Builder()
            .setServiceUuid(ParcelUuid(SERVICE_UUID))
            .build()
        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
            .build()
        scanning = true
        scanner?.startScan(listOf(filter), settings, scanCallback)
        listener.onBleMessage("正在扫描 RadarCare 雷达板")

        mainHandler.postDelayed({
            if (scanning) {
                stopScan()
                listener.onBleMessage("扫描结束，未发现 RadarCare 雷达板")
            }
        }, SCAN_TIMEOUT_MS)
    }

    @SuppressLint("MissingPermission")
    fun stopScan() {
        if (!scanning) return
        scanning = false
        runCatching { scanner?.stopScan(scanCallback) }
    }

    @SuppressLint("MissingPermission")
    fun connectLastDevice() {
        if (!hasRequiredPermissions()) {
            listener.onBleMessage("请先允许蓝牙权限")
            return
        }
        val device = lastDevice
        if (device == null) {
            listener.onBleMessage("请先扫描到 RadarCare 雷达板")
            return
        }
        cleanupGatt()
        listener.onBleMessage("正在连接 ${runCatching { device.name }.getOrNull() ?: device.address}")
        gatt = device.connectGatt(context, false, gattCallback, BluetoothDevice.TRANSPORT_LE)
    }

    @SuppressLint("MissingPermission")
    fun disconnect() {
        stopScan()
        val oldGatt = gatt
        if (oldGatt != null) {
            runCatching { oldGatt.disconnect() }
            runCatching { oldGatt.close() }
        }
        cleanupGatt()
        listener.onDisconnected("蓝牙已断开")
    }

    fun pauseRadarTx() {
        writeControl("pause_tx")
    }

    fun resumeRadarTx() {
        writeControl("resume_tx")
    }

    @SuppressLint("MissingPermission")
    private fun writeControl(command: String) {
        if (!hasRequiredPermissions()) {
            listener.onBleMessage("请先允许蓝牙权限")
            return
        }
        val gatt = gatt
        val characteristic = controlCharacteristic
        if (gatt == null || characteristic == null) {
            listener.onBleMessage("蓝牙未连接，无法发送控制命令")
            return
        }

        val payload = command.toByteArray(Charsets.US_ASCII)
        characteristic.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            gatt.writeCharacteristic(characteristic, payload, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT)
        } else {
            @Suppress("DEPRECATION")
            characteristic.value = payload
            @Suppress("DEPRECATION")
            gatt.writeCharacteristic(characteristic)
        }
    }

    @SuppressLint("MissingPermission")
    private fun enableNotifications(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic) {
        gatt.setCharacteristicNotification(characteristic, true)
        val descriptor = characteristic.getDescriptor(CCCD_UUID) ?: return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            gatt.writeDescriptor(descriptor, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
        } else {
            @Suppress("DEPRECATION")
            descriptor.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
            @Suppress("DEPRECATION")
            gatt.writeDescriptor(descriptor)
        }
    }

    private fun parseAndPublish(value: ByteArray) {
        val status = parseStatus(value) ?: return
        post { listener.onStatus(status) }
    }

    private fun parseStatus(value: ByteArray): RadarBleStatus? {
        if (value.size < 14) {
            post { listener.onBleMessage("雷达状态包长度异常：${value.size}") }
            return null
        }
        val flags = u8(value, 1)
        val heartRaw = s16(value, 2)
        val breathRaw = s16(value, 4)
        val distanceMm = u16(value, 6)
        return RadarBleStatus(
            version = u8(value, 0),
            flags = flags,
            heartRate = if (hasFlag(flags, FLAG_HEART_VALID)) heartRaw / 10.0 else null,
            breathRate = if (hasFlag(flags, FLAG_BREATH_VALID)) breathRaw / 10.0 else null,
            distanceMeters = if (hasFlag(flags, FLAG_DISTANCE_VALID)) distanceMm / 1000.0 else null,
            motionDelta = u16(value, 8),
            sequence = u32(value, 10),
            radarOnline = hasFlag(flags, FLAG_RADAR_ONLINE),
            boardStill = hasFlag(flags, FLAG_BOARD_STILL),
            personPresent = hasFlag(flags, FLAG_PERSON_PRESENT),
            txEnabled = hasFlag(flags, FLAG_TX_ENABLED),
            imuReady = hasFlag(flags, FLAG_IMU_READY)
        )
    }

    private fun cleanupGatt() {
        statusCharacteristic = null
        controlCharacteristic = null
        val old = gatt
        gatt = null
        runCatching { old?.close() }
    }

    private fun post(block: () -> Unit) {
        mainHandler.post(block)
    }

    private fun u8(value: ByteArray, index: Int): Int {
        return value[index].toInt() and 0xff
    }

    private fun u16(value: ByteArray, index: Int): Int {
        return (u8(value, index) or (u8(value, index + 1) shl 8))
    }

    private fun s16(value: ByteArray, index: Int): Int {
        return u16(value, index).toShort().toInt()
    }

    private fun u32(value: ByteArray, index: Int): Long {
        return (u8(value, index).toLong() or
            (u8(value, index + 1).toLong() shl 8) or
            (u8(value, index + 2).toLong() shl 16) or
            (u8(value, index + 3).toLong() shl 24)) and 0xffffffffL
    }

    private fun hasFlag(flags: Int, flag: Int): Boolean = (flags and flag) != 0

    companion object {
        val SERVICE_UUID: UUID = UUID.fromString("9f5c1000-8d3b-4f4f-9b1a-6b0bd2d7c001")
        val STATUS_CHAR_UUID: UUID = UUID.fromString("9f5c1001-8d3b-4f4f-9b1a-6b0bd2d7c001")
        val CONTROL_CHAR_UUID: UUID = UUID.fromString("9f5c1002-8d3b-4f4f-9b1a-6b0bd2d7c001")
        private val CCCD_UUID: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")

        private const val FLAG_RADAR_ONLINE = 1 shl 0
        private const val FLAG_BOARD_STILL = 1 shl 1
        private const val FLAG_PERSON_PRESENT = 1 shl 2
        private const val FLAG_TX_ENABLED = 1 shl 3
        private const val FLAG_IMU_READY = 1 shl 4
        private const val FLAG_HEART_VALID = 1 shl 5
        private const val FLAG_BREATH_VALID = 1 shl 6
        private const val FLAG_DISTANCE_VALID = 1 shl 7
        private const val SCAN_TIMEOUT_MS = 8000L
    }
}
