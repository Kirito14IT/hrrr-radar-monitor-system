import sys
from datetime import datetime, timedelta
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from apnea_fusion import breath_window_abnormal, detect_suspected_apnea_events


def _row(at: datetime, breath_rate=16.0, snore_level=0.1, target_distance=1.0, radar_online=True):
    return {
        "timestamp": at.isoformat(),
        "radar_online": radar_online,
        "radar_board_stationary": True,
        "target_distance": target_distance,
        "heart_rate": 72.0,
        "breath_rate": breath_rate,
        "snore_level": snore_level,
        "snore_score": snore_level,
        "snore_detected": snore_level >= 0.5,
    }


def test_detects_low_breath_with_snore_recovery_evidence():
    start = datetime(2026, 1, 1, 0, 0, 0)
    rows = []
    rows += [_row(start + timedelta(seconds=i), breath_rate=16.0, snore_level=0.2) for i in range(8)]
    rows += [_row(start + timedelta(seconds=8 + i), breath_rate=5.5, snore_level=0.66) for i in range(12)]
    rows += [_row(start + timedelta(seconds=20 + i), breath_rate=15.0, snore_level=0.52) for i in range(8)]

    events = detect_suspected_apnea_events(rows)

    assert len(events) == 1
    assert events[0]["type"] == "suspected_apnea"
    assert events[0]["details"]["duration_seconds"] >= 10
    assert "snore_evidence" in events[0]["details"]["reasons"]


def test_does_not_trigger_on_single_bad_breath_point():
    start = datetime(2026, 1, 1, 0, 0, 0)
    rows = [_row(start + timedelta(seconds=i), breath_rate=16.0, snore_level=0.65) for i in range(20)]
    rows[10]["breath_rate"] = 4.0

    assert detect_suspected_apnea_events(rows) == []


def test_does_not_trigger_when_person_not_detected():
    start = datetime(2026, 1, 1, 0, 0, 0)
    rows = [
        _row(start + timedelta(seconds=i), breath_rate=5.0, snore_level=0.8, target_distance=0.0)
        for i in range(20)
    ]

    assert detect_suspected_apnea_events(rows) == []


def test_breath_abnormal_requires_window_majority():
    start = datetime(2026, 1, 1, 0, 0, 0)
    noisy_rows = [_row(start + timedelta(seconds=i), breath_rate=16.0) for i in range(8)]
    noisy_rows[2]["breath_rate"] = 7.0
    assert breath_window_abnormal(noisy_rows) is None

    sustained_rows = [_row(start + timedelta(seconds=i), breath_rate=8.0) for i in range(8)]
    summary = breath_window_abnormal(sustained_rows)
    assert summary is not None
    assert summary["median_breath_rate"] == 8.0
