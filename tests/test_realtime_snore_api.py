import math
import struct
import sys
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


if __name__ == "__main__":
    unittest.main()
