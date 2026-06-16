import sys
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import mock_hardware_api


class MockEnvironmentApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(mock_hardware_api.app)
        with mock_hardware_api.STATE_LOCK:
            mock_hardware_api.state["timeline"] = []
            mock_hardware_api.state["last_environment_heartbeat_at"] = None
            mock_hardware_api.state["environment_board_online"] = False
            mock_hardware_api.state["temperature_c"] = None
            mock_hardware_api.state["humidity_pct"] = None
            mock_hardware_api.state["comfort_status"] = "offline"
            mock_hardware_api.state["environment_sensor_ok"] = False
            mock_hardware_api.state["edgi_board_online"] = False
            mock_hardware_api.state["last_edgi_heartbeat_at"] = None
            mock_hardware_api.state["last_device_message"] = "test reset"

    def test_environment_heartbeat_updates_public_api_shape(self):
        response = self.client.post(
            "/mock/environment-heartbeat",
            json={
                "temperature_c": 21.8,
                "humidity_pct": 45.2,
                "sensor_ok": True,
                "source": "mock_environment_board",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["comfort_status"], "comfortable")

        status = self.client.get("/status").json()
        self.assertTrue(status["environment_board_online"])
        self.assertTrue(status["edgi_board_online"])
        self.assertEqual(status["temperature_c"], 21.8)
        self.assertEqual(status["humidity_pct"], 45.2)
        self.assertEqual(status["comfort_status"], "comfortable")

        timeline = self.client.get("/timeline?seconds=60").json()
        latest = timeline["data"][-1]
        self.assertTrue(latest["environment_online"])
        self.assertEqual(latest["temperature_c"], 21.8)
        self.assertEqual(latest["humidity_pct"], 45.2)
        self.assertEqual(timeline["summary"]["avg_humidity_pct"], 45.2)

        overview = self.client.get("/sleep/overview?mode=live&seconds=120").json()
        self.assertTrue(overview["devices"]["environment_board_online"])
        self.assertEqual(overview["stats"]["latest_comfort_status"], "comfortable")

    def test_environment_timeout_marks_board_offline(self):
        self.client.post(
            "/mock/environment-heartbeat",
            json={
                "temperature_c": 14.5,
                "humidity_pct": 28.0,
                "sensor_ok": True,
                "source": "mock_environment_board",
            },
        )

        with mock_hardware_api.STATE_LOCK:
            old_timestamp = mock_hardware_api.iso_second(
                mock_hardware_api.datetime.fromtimestamp(time.time() - 40.0)
            )
            mock_hardware_api.state["last_environment_heartbeat_at"] = old_timestamp
            mock_hardware_api.upsert_timeline_locked()

        status = self.client.get("/status").json()
        self.assertFalse(status["environment_board_online"])
        self.assertEqual(status["comfort_status"], "offline")
        self.assertIsNone(status["temperature_c"])
        self.assertIsNone(status["humidity_pct"])

    def test_sensor_error_keeps_edgi_board_online(self):
        response = self.client.post(
            "/mock/environment-heartbeat",
            json={
                "temperature_c": 0,
                "humidity_pct": 0,
                "sensor_ok": False,
                "source": "edgi_talk_m55",
            },
        )

        self.assertEqual(response.status_code, 200)
        status = self.client.get("/status").json()
        self.assertTrue(status["edgi_board_online"])
        self.assertTrue(status["environment_board_online"])
        self.assertIsNone(status["temperature_c"])
        self.assertIsNone(status["humidity_pct"])


if __name__ == "__main__":
    unittest.main()
