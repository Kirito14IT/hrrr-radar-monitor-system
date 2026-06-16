import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import mock_hardware_api


class MockEmergencyApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(mock_hardware_api.app)

    def test_emergency_is_exposed_in_status_and_overview(self):
        response = self.client.post(
            "/emergency",
            json={
                "source": "xiaozhi_voice_board",
                "phrase": "救命",
                "transcript": "小智救命",
                "device_id": "test-board",
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

        resolved = self.client.post(
            "/emergency/resolve",
            json={
                "event_id": event_id,
                "source": "xiaozhi_voice_board",
                "resolved_by": "test",
                "resolution_note": "test resolved",
            },
        )
        self.assertEqual(resolved.json()["status"], "success")


if __name__ == "__main__":
    unittest.main()
