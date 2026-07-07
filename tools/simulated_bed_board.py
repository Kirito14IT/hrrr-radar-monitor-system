#!/usr/bin/env python3
"""Standalone simulated embedded board for the demo bed.

This process intentionally lives outside the backend.  It behaves like a small
set of embedded devices and reports to the same HTTP endpoints used by real
boards:

  - /hardware/edgi-heartbeat
  - /hardware/environment-heartbeat
  - /hardware/snore-heartbeat
  - /save-vitals-with-user
  - /emergency
  - /beds/{bed_id}/emergency/resolve

The frontend controls it through this process' local control server
(default: http://127.0.0.1:8092).
"""

from __future__ import annotations

import argparse
import json
import math
import signal
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


SCENARIOS = {
    "normal",
    "snore",
    "apnea",
    "snore_stop_breath_drop",
    "night_absence",
    "emergency_voice",
    "board_fall",
    "offline",
    "temp_high",
    "temp_low",
}
EMERGENCY_SCENARIOS = {
    "apnea": {
        "event_type": "suspected_apnea",
        "title": "疑似呼吸暂停",
        "message": "开发板检测到呼噜后呼吸异常，请立即确认床旁情况。",
    },
    "snore_stop_breath_drop": {
        "event_type": "snore_stop_breath_drop",
        "title": "呼噜停止伴随呼吸异常",
        "message": "检测到呼噜声停止后，雷达呼吸/存在性信号跌破阈值，请立即确认。",
    },
    "night_absence": {
        "event_type": "night_absence",
        "title": "夜间疑似离床",
        "message": "夜间存在性检测连续超过 1 小时未检测到病人在床，请立即确认。",
    },
    "emergency_voice": {
        "event_type": "emergency_voice",
        "title": "请立即确认床旁情况",
        "message": "小智开发板上报求助语音。",
    },
    "board_fall": {
        "event_type": "board_fall",
        "title": "开发板摇晃报警",
        "message": "小智开发板检测到摇晃。",
    },
}


class SimulatedBedBoard:
    def __init__(self, args: argparse.Namespace):
        self.backend = args.backend.rstrip("/")
        self.bed_id = args.bed_id
        self.user_id = args.user_id
        self.interval = max(0.5, float(args.interval))
        self.device_id = args.device_id
        self.source = args.source
        self.started_at = time.time()
        self.running = True
        self.scenario = "normal"
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.last_error: str | None = None
        self.sent_count = 0
        self.last_sent_at: str | None = None
        self.last_emergency_at: dict[str, float] = {}
        self.emergency_sent_for_scenario: set[str] = set()

    def wave(self, now: float, period: float, amplitude: float = 1.0, phase: float = 0.0) -> float:
        return math.sin((now - self.started_at) / period * 2.0 * math.pi + phase) * amplitude

    def values(self) -> dict[str, Any]:
        with self.lock:
            scenario = self.scenario
            running = self.running
        now = time.time()
        offline = (not running) or scenario == "offline"
        snore = scenario in {"snore", "apnea"}
        apnea = scenario == "apnea"
        heart = 76.0 + self.wave(now, 44, 6.0) + self.wave(now, 13, 1.5, 0.8)
        breath = 16.0 + self.wave(now, 38, 2.8, 0.5)
        if apnea:
            breath = 8.2 + self.wave(now, 8, 1.0)
            heart = min(94.0, heart + 8.0)
        if scenario == "temp_high":
            temperature = 41.5 + self.wave(now, 120, 1.0, 0.8)
        elif scenario == "temp_low":
            temperature = 5.5 + self.wave(now, 120, 0.8, 1.5)
        else:
            temperature = 25.3 + self.wave(now, 120, 0.8, 1.2)
        humidity = 55.0 + self.wave(now, 100, 7.0, 0.4)
        snore_score = 0.76 + self.wave(now, 12, 0.13) if snore else 0.06
        snore_level = 0.70 + self.wave(now, 10, 0.10, 1.0) if snore else 0.08
        ambient_dbfs = -58.0 + self.wave(now, 32, 3.0, 0.6) + self.wave(now, 9, 1.2, 1.8)
        snore_dbfs = -33.0 + self.wave(now, 10, 4.0) if snore else ambient_dbfs
        return {
            "scenario": scenario,
            "offline": offline,
            "heart_rate": None if offline else round(max(64.0, min(98.0, heart)), 1),
            "breath_rate": None if offline else round(max(6.0, min(22.0, breath)), 1),
            "target_distance": None if offline else round(0.56 + self.wave(now, 52, 0.025), 3),
            "temperature_c": None if offline else (
                round(max(29.0, min(34.0, temperature)), 1) if scenario == "temp_high"
                else round(max(12.0, min(19.0, temperature)), 1) if scenario == "temp_low"
                else round(max(24.0, min(27.0, temperature)), 1)
            ),
            "humidity_pct": None if offline else round(max(45.0, min(65.0, humidity)), 1),
            "snore_detected": bool(snore and not offline),
            "snore_score": round(max(0.0, min(1.0, snore_score)), 3) if not offline else 0.0,
            "snore_level": round(max(0.0, min(1.0, snore_level)), 3) if not offline else None,
            "snore_dbfs": round(snore_dbfs, 1) if not offline else None,
        }

    def post_json(self, path: str, payload: dict[str, Any], timeout: float = 3.0) -> dict[str, Any] | None:
        url = f"{self.backend}{path}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw else {}
        except Exception as exc:
            with self.lock:
                self.last_error = f"{url}: {exc}"
            return None

    def send_once(self) -> None:
        values = self.values()
        if values["offline"]:
            with self.lock:
                self.last_sent_at = datetime.now().isoformat(timespec="seconds")
            return

        timestamp = datetime.now().isoformat(timespec="seconds")
        common = {
            "bed_id": self.bed_id,
            "device_id": self.device_id,
            "source": self.source,
        }
        self.post_json("/hardware/edgi-heartbeat", {
            **common,
            "mode": "guardian",
            "keyword_online": True,
            "snore_guard_enabled": True,
        })
        self.post_json("/hardware/environment-heartbeat", {
            **common,
            "temperature_c": values["temperature_c"],
            "humidity_pct": values["humidity_pct"],
            "sensor_ok": True,
        })
        self.post_json("/hardware/snore-heartbeat", {
            **common,
            "snore_score": values["snore_score"],
            "snore_detected": values["snore_detected"],
            "dbfs": values["snore_dbfs"],
        })
        self.post_json("/save-vitals-with-user", {
            "userID": self.user_id,
            "bed_id": self.bed_id,
            "heart_rate": values["heart_rate"],
            "breath_rate": values["breath_rate"],
            "target_distance": values["target_distance"],
            "timestamp": timestamp,
            "snore_detected": values["snore_detected"],
            "snore_score": values["snore_score"],
            "snore_level": values["snore_level"],
        })
        self.maybe_send_emergency(values["scenario"])
        with self.lock:
            self.sent_count += 1
            self.last_sent_at = timestamp
            self.last_error = None

    def maybe_send_emergency(self, scenario: str) -> None:
        if scenario not in EMERGENCY_SCENARIOS:
            return
        if scenario in self.emergency_sent_for_scenario:
            return
        now = time.time()
        last = self.last_emergency_at.get(scenario, 0.0)
        if now - last < 8.0:
            return
        spec = EMERGENCY_SCENARIOS[scenario]
        self.post_json("/emergency", {
            "bed_id": self.bed_id,
            "source": self.source,
            "device_id": self.device_id,
            "event_type": spec["event_type"],
            "title": spec["title"],
            "message": spec["message"],
            "severity": "critical",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "details": {"simulated": True, "scenario": scenario},
        })
        self.last_emergency_at[scenario] = now
        self.emergency_sent_for_scenario.add(scenario)

    def resolve_sim_emergencies(self) -> None:
        self.post_json(f"/beds/{self.bed_id}/emergency/resolve", {
            "bed_id": self.bed_id,
            "source": self.source,
            "device_id": self.device_id,
            "resolution_note": "模拟开发板场景恢复正常",
            "resolved_by": "simulated_bed_board",
        })

    def set_scenario(self, scenario: str) -> dict[str, Any]:
        scenario = (scenario or "normal").strip().lower()
        if scenario not in SCENARIOS:
            scenario = "normal"
        with self.lock:
            self.scenario = scenario
            self.running = scenario != "offline"
            self.last_error = None
        if scenario in {"normal", "snore", "offline", "temp_high", "temp_low"}:
            self.emergency_sent_for_scenario.clear()
            self.resolve_sim_emergencies()
        if scenario != "offline":
            self.send_once()
        return self.status()

    def status(self) -> dict[str, Any]:
        with self.lock:
            state = {
                "running": self.running,
                "scenario": self.scenario,
                "sent_count": self.sent_count,
                "last_sent_at": self.last_sent_at,
                "last_error": self.last_error,
            }
        state.update({
            "bed_id": self.bed_id,
            "backend": self.backend,
            "values": self.values(),
        })
        return state

    def loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.send_once()
            except Exception as exc:
                with self.lock:
                    self.last_error = str(exc)
            self.stop_event.wait(self.interval)


def make_handler(board: SimulatedBedBoard):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:
            self._send(200, {"status": "ok"})

        def do_GET(self) -> None:
            if self.path.rstrip("/") == "/status":
                self._send(200, {"status": "success", "data": board.status()})
            else:
                self._send(404, {"status": "error", "message": "not found"})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                payload = {}
            path = self.path.rstrip("/")
            if path == "/start":
                with board.lock:
                    board.running = True
                    if board.scenario == "offline":
                        board.scenario = "normal"
                board.send_once()
                self._send(200, {"status": "success", "data": board.status()})
            elif path == "/stop":
                board.set_scenario("offline")
                self._send(200, {"status": "success", "data": board.status()})
            elif path == "/scenario":
                self._send(200, {"status": "success", "data": board.set_scenario(payload.get("scenario", "normal"))})
            else:
                self._send(404, {"status": "error", "message": "not found"})

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone simulated bed embedded board")
    parser.add_argument("--backend", default="http://127.0.0.1:8081", help="Backend API base URL")
    parser.add_argument("--listen", default="127.0.0.1", help="Control server bind address")
    parser.add_argument("--port", type=int, default=8092, help="Control server port")
    parser.add_argument("--bed-id", default="bed-sim-001", help="Registered bed_id to report")
    parser.add_argument("--user-id", type=int, default=1, help="User ID for historical vitals")
    parser.add_argument("--device-id", default="sim-board-001", help="Simulated board device ID")
    parser.add_argument("--source", default="simulated_bed_board", help="Source identifier")
    parser.add_argument("--interval", type=float, default=2.0, help="Heartbeat interval in seconds")
    parser.add_argument("--once", action="store_true", help="Send one round of data and exit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    board = SimulatedBedBoard(args)
    if args.once:
        board.send_once()
        print(json.dumps(board.status(), ensure_ascii=False, indent=2))
        return 0

    worker = threading.Thread(target=board.loop, daemon=True)
    worker.start()
    server = ThreadingHTTPServer((args.listen, args.port), make_handler(board))
    print(f"Simulated bed board: http://{args.listen}:{args.port}")
    print(f"Reporting {args.bed_id} to {args.backend}")

    def shutdown(_signum: int, _frame: Any) -> None:
        board.stop_event.set()
        server.shutdown()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
