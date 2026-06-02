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

    def test_audio_upload_updates_snore_status_and_timeline(self):
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
        self.assertTrue(status["snore_board_online"])
        self.assertEqual(status["audio_upload_count"], 1)
        self.assertIsNotNone(status["last_audio_received_at"])
        self.assertIsNotNone(status["snore_age_seconds"])
        self.assertIn("snore_level", status)

        timeline = self.client.get("/timeline?seconds=180").json()
        self.assertEqual(timeline["code"], 200)
        self.assertTrue(timeline["data"])
        self.assertTrue(timeline["data"][-1]["snore_online"])

    def test_snore_heartbeat_updates_snore_status(self):
        response = self.client.post(
            "/mock/snore-heartbeat",
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
        response = self.client.post("/mock/snore-session/start")
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
        response = self.client.post("/mock/snore-session/stop")
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
        self.client.post("/mock/snore-session/start")

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

        self.client.post("/mock/snore-session/start")
        # 强制把 session 的最近活动写成 60 秒前，远超 30 秒宽限期
        self.processor.snore_session_last_seen_at = time.time() - 60.0
        self.processor.last_snore_heartbeat_time = time.time() - 60.0
        self.processor.last_audio_received_time = time.time() - 60.0

        status = self.client.get("/status").json()
        self.assertFalse(status["snore_board_online"])
        self.assertFalse(status["snore_session_active"])

    def test_back_stays_offline_even_if_late_heartbeat_arrives(self):
        """back 之后即便还有迟到的 1Hz 心跳到达，前端也要一直显示离线。"""
        self.client.post("/mock/snore-session/start")
        self.client.post("/mock/snore-session/stop")

        # 模拟一个迟到的 1Hz 心跳：刚收到
        self.client.post(
            "/mock/snore-heartbeat",
            json={"snore_score": 0.0, "snore_detected": False, "source": "late"},
        )

        status = self.client.get("/status").json()
        self.assertFalse(status["snore_board_online"])

        # 直到用户重新按下 Snore detect 才允许再次显示在线
        self.client.post("/mock/snore-session/start")
        status = self.client.get("/status").json()
        self.assertTrue(status["snore_board_online"])
        self.assertTrue(status["snore_session_active"])


if __name__ == "__main__":
    unittest.main()
