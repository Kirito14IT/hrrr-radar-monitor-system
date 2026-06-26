import math
import struct
import sys
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from realtime_radar_processing import RealtimeRadarProcessor


def make_pcm(seconds=0.25, sample_rate=16000):
    frames = int(seconds * sample_rate)
    chunks = bytearray()
    for idx in range(frames):
        value = int(0.25 * 32767 * math.sin(2.0 * math.pi * 90.0 * idx / sample_rate))
        chunks += struct.pack("<hh", value, value)
    return bytes(chunks)


class RealtimeSnoreApiTest(unittest.TestCase):
    def setUp(self):
        self.processor = RealtimeRadarProcessor(load_models=False, api_enabled=True)
        self.client = TestClient(self.processor.app)

    def test_audio_upload_saves_audio_without_predicting_snore_status(self):
        response = self.client.post(
            "/audio",
            content=make_pcm(),
            headers={"Content-Type": "application/octet-stream"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["message"], "音频已接收")
        Path(body["file"]).unlink(missing_ok=True)

        status = self.client.get("/status").json()
        self.assertFalse(status["snore_board_online"])
        self.assertEqual(status["audio_upload_count"], 1)
        self.assertIsNotNone(status["last_audio_received_at"])
        self.assertIsNotNone(status["last_audio_dbfs"])
        self.assertIsNone(status["last_snore_heartbeat_at"])
        self.assertIsNone(status["snore_age_seconds"])
        self.assertEqual(status["snore_score"], 0.0)
        self.assertIsNone(status["snore_dbfs"])
        self.assertIsNone(status["snore_level"])
        self.assertFalse(status["snore_detected"])

        timeline = self.client.get("/timeline?seconds=180").json()
        self.assertEqual(timeline["code"], 200)
        self.assertTrue(timeline["data"])
        self.assertFalse(timeline["data"][-1]["snore_online"])

    def test_audio_upload_does_not_overwrite_real_snore_heartbeat(self):
        heartbeat = self.client.post(
            "/hardware/snore-heartbeat",
            json={
                "snore_score": 0.72,
                "snore_detected": True,
                "dbfs": -24.0,
                "source": "real_snore_board",
            },
        )
        self.assertEqual(heartbeat.status_code, 200)
        before = self.client.get("/status").json()

        response = self.client.post(
            "/audio",
            content=make_pcm(seconds=8.0),
            headers={"Content-Type": "application/octet-stream"},
        )

        self.assertEqual(response.status_code, 200)
        Path(response.json()["file"]).unlink(missing_ok=True)

        status = self.client.get("/status").json()
        self.assertTrue(status["snore_board_online"])
        self.assertEqual(status["audio_upload_count"], 1)
        self.assertIsNotNone(status["last_audio_dbfs"])
        self.assertEqual(status["last_snore_heartbeat_at"], before["last_snore_heartbeat_at"])
        self.assertEqual(status["snore_score"], 0.72)
        self.assertEqual(status["snore_dbfs"], -24.0)
        self.assertTrue(status["snore_detected"])
        self.assertEqual(status["snore_event_count"], before["snore_event_count"])

    def test_snore_heartbeat_updates_snore_status(self):
        response = self.client.post(
            "/hardware/snore-heartbeat",
            json={
                "snore_score": 0.72,
                "snore_detected": True,
                "dbfs": -24.0,
                "source": "real_snore_board",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["snore_score"], 0.72)

        status = self.client.get("/status").json()
        self.assertTrue(status["snore_board_online"])
        self.assertTrue(status["snore_detected"])
        self.assertEqual(status["snore_score"], 0.72)

    def test_snore_session_start_stop_toggles_online_status(self):
        """按下 Snore detect → 在线；按下 back → 离线。"""
        # 初始离线
        status = self.client.get("/status").json()
        self.assertFalse(status["snore_board_online"])
        self.assertFalse(status["snore_session_active"])

        # 按下 Snore detect
        response = self.client.post("/hardware/snore-session/start")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "success")
        self.assertTrue(body["snore_board_online"])
        self.assertIsNotNone(body["started_at"])

        status = self.client.get("/status").json()
        self.assertTrue(status["snore_board_online"])
        self.assertTrue(status["snore_session_active"])
        self.assertEqual(status["snore_session_started_at"], body["started_at"])

        # 按下 back
        response = self.client.post("/hardware/snore-session/stop")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "success")
        self.assertFalse(body["snore_board_online"])

        status = self.client.get("/status").json()
        self.assertFalse(status["snore_board_online"])
        self.assertFalse(status["snore_session_active"])

    def test_snore_session_keeps_board_online_during_audio_collection(self):
        """Snore detect 按下后，10 秒收音频期间不应该掉线。"""
        # 打开 session
        self.client.post("/hardware/snore-session/start")

        # 模拟“收完 10 秒音频”这一刻：把 last_audio_received_time 写成 8 秒前
        # （已超过 5s 默认超时，但还没超过 15s 新超时和 30s session 宽限期）
        self.processor.last_audio_received_time = time.time() - 8.0

        # 在 10 秒收音频的窗口内，前端仍应看到在线
        status = self.client.get("/status").json()
        self.assertTrue(status["snore_board_online"])
        self.assertTrue(status["snore_session_active"])

    def test_snore_session_auto_expires_after_long_silence(self):
        """长时间没有任何活动，session 应当自动失效，恢复离线。"""
        import realtime_radar_processing as rrp

        self.client.post("/hardware/snore-session/start")
        # 强制把 session 的最近活动写成 60 秒前，远超 30 秒宽限期
        self.processor.snore_session_last_seen_at = time.time() - 60.0
        self.processor.last_snore_heartbeat_time = time.time() - 60.0
        self.processor.last_audio_received_time = time.time() - 60.0

        status = self.client.get("/status").json()
        self.assertFalse(status["snore_board_online"])
        self.assertFalse(status["snore_session_active"])

    def test_back_stays_offline_even_if_late_heartbeat_arrives(self):
        """back 之后即便还有迟到的 1Hz 心跳到达，前端也要一直显示离线。"""
        self.client.post("/hardware/snore-session/start")
        self.client.post("/hardware/snore-session/stop")

        # 模拟一个迟到的 1Hz 心跳：刚收到
        self.client.post(
            "/hardware/snore-heartbeat",
            json={"snore_score": 0.0, "snore_detected": False, "source": "late"},
        )

        status = self.client.get("/status").json()
        self.assertFalse(status["snore_board_online"])

        # 直到用户重新按下 Snore detect 才允许再次显示在线
        self.client.post("/hardware/snore-session/start")
        status = self.client.get("/status").json()
        self.assertTrue(status["snore_board_online"])
        self.assertTrue(status["snore_session_active"])

    def test_environment_heartbeat_updates_status_timeline_and_overview(self):
        response = self.client.post(
            "/hardware/environment-heartbeat",
            json={
                "temperature_c": 24.3,
                "humidity_pct": 52.1,
                "sensor_ok": True,
                "source": "real_edgi_talk_m33_aht20",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["comfort_status"], "comfortable")

        status = self.client.get("/status").json()
        self.assertTrue(status["environment_board_online"])
        self.assertTrue(status["edgi_board_online"])
        self.assertEqual(status["temperature_c"], 24.3)
        self.assertEqual(status["humidity_pct"], 52.1)
        self.assertEqual(status["comfort_status"], "comfortable")
        self.assertIsNotNone(status["last_environment_heartbeat_at"])
        self.assertIsNotNone(status["environment_age_seconds"])

        timeline = self.client.get("/timeline?seconds=180").json()
        self.assertEqual(timeline["code"], 200)
        latest = timeline["data"][-1]
        self.assertTrue(latest["environment_online"])
        self.assertEqual(latest["temperature_c"], 24.3)
        self.assertEqual(latest["humidity_pct"], 52.1)
        self.assertEqual(latest["comfort_status"], "comfortable")
        self.assertIn("avg_temperature_c", timeline["summary"])

        overview = self.client.get("/sleep/overview?mode=live&seconds=180").json()
        self.assertTrue(overview["devices"]["environment_board_online"])
        self.assertEqual(overview["stats"]["latest_comfort_status"], "comfortable")
        self.assertIn("环境舒适度", [card["title"] for card in overview["stability_cards"]])

    def test_emergency_updates_status_and_overview(self):
        response = self.client.post(
            "/emergency",
            json={
                "source": "xiaozhi_voice_board",
                "phrase": "需要帮助",
                "transcript": "小智我需要帮助",
                "device_id": "realtime-test",
            },
        )
        self.assertEqual(response.status_code, 200)
        event_id = response.json()["event_id"]

        status = self.client.get("/status").json()
        self.assertTrue(status["edgi_board_online"])
        self.assertTrue(status["emergency_active"])
        self.assertEqual(status["active_emergency"]["eventID"], event_id)

        overview = self.client.get("/sleep/overview?mode=live&seconds=60").json()
        event = next(item for item in overview["events"] if item["eventID"] == event_id)
        self.assertEqual(event["type"], "emergency_voice")
        self.assertEqual(event["severity"], "critical")

    def test_environment_offline_timeout_and_extreme_comfort_status(self):
        response = self.client.post(
            "/hardware/environment-heartbeat",
            json={
                "temperature_c": 33.5,
                "humidity_pct": 82.0,
                "sensor_ok": True,
                "source": "real_edgi_talk_m33_aht20",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["comfort_status"], "hot_humid_critical")

        self.processor.last_environment_heartbeat_time = time.time() - 30.0
        status = self.client.get("/status").json()
        self.assertFalse(status["environment_board_online"])
        self.assertEqual(status["comfort_status"], "offline")
        self.assertIsNone(status["temperature_c"])
        self.assertIsNone(status["humidity_pct"])


if __name__ == "__main__":
    unittest.main()
