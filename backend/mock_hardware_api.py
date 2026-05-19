#!/usr/bin/env python3
"""
No-hardware mock API for the radar monitor project.

This service is intentionally lightweight:
- no TensorFlow model
- no MySQL server
- no physical radar board
- no physical snore board

It exposes the same API shape used by the current Vue frontend and accepts the
same raw HTTP audio upload shape sent by meow_detect_once.cpp.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import random
import socket
import sqlite3
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    import uvicorn
except ImportError:  # pragma: no cover - startup will print a clearer error.
    uvicorn = None


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "mock_monitor.db"
AUDIO_DIR = BASE_DIR / "mock_audio_uploads"

API_HOST = "0.0.0.0"
API_PORT = int(os.environ.get("MOCK_API_PORT", "8081"))

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
NUM_CHANNELS = 2
BOARD_TIMEOUT_SECONDS = 5.0
SNORE_EVENT_HOLD_SECONDS = 12.0
TIMELINE_RETENTION_SECONDS = 7200
DEEPSEEK_TIMEOUT_SECONDS = 40

STATE_LOCK = threading.Lock()

state: dict[str, Any] = {
    "scenario": "auto",
    "scenario_until": 0.0,
    "heart_rate": 0.0,
    "breath_rate": 0.0,
    "target_distance": 0.0,
    "target_bin": 0,
    "phase_values": [],
    "running": True,
    "start_time": time.time(),
    "frame_count": 0,
    "radar_online": False,
    "radar_board_online": False,
    "snore_board_online": False,
    "last_radar_received_at": None,
    "last_snore_heartbeat_at": None,
    "last_radar_frame_number": 0,
    "snore_score": 0.0,
    "snore_dbfs": None,
    "snore_detected": False,
    "snore_event_count": 0,
    "last_snore_at": None,
    "audio_upload_count": 0,
    "last_audio_received_at": None,
    "last_audio_file": None,
    "last_audio_seconds": 0.0,
    "last_audio_dbfs": None,
    "last_device_message": "mock api started",
    "last_sleep_condition": "unknown",
    "timeline": [],
}


app = FastAPI(
    title="Radar Monitor Mock Hardware API",
    description="No-hardware API simulator for radar vitals and snore audio upload.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class UserRegister(BaseModel):
    userName: str
    passWord: str
    email: str


class UserLogin(BaseModel):
    userName: str
    passWord: str


class VitalsData(BaseModel):
    userID: int
    heart_rate: float
    breath_rate: float
    target_distance: float
    timestamp: Optional[str] = None


class ScenarioRequest(BaseModel):
    scenario: str = "auto"
    seconds: float = 12.0
    message: Optional[str] = None


class RadarFrameData(BaseModel):
    frame_number: int
    heart_rate: float
    breath_rate: float
    target_distance: float
    target_bin: int = 0
    phase_values: list[float] = []
    status: str = "ok"
    source: str = "mock_radar_board"


class SnoreHeartbeat(BaseModel):
    snore_score: float = 0.0
    snore_detected: bool = False
    dbfs: Optional[float] = None
    source: str = "mock_snore_board"


class AiAnalysisRequest(BaseModel):
    rows: list[dict[str, Any]] = []
    date: Optional[str] = None
    userID: Optional[int] = None


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def iso_second(value: Optional[datetime] = None) -> str:
    dt = value or datetime.now()
    return dt.replace(microsecond=0).isoformat(timespec="seconds")


def seconds_since(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return time.time() - datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def parse_iso_seconds(value: str) -> Optional[float]:
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return None


def load_env_file() -> dict[str, str]:
    env_path = BASE_DIR / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def config_value(key: str, default: str = "") -> str:
    return os.environ.get(key) or load_env_file().get(key) or default


def password_hash(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_info (
                userID INTEGER PRIMARY KEY AUTOINCREMENT,
                userName TEXT NOT NULL UNIQUE,
                passWord TEXT NOT NULL,
                email TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS heart_data (
                dataID INTEGER PRIMARY KEY AUTOINCREMENT,
                userID INTEGER NOT NULL,
                heart_rate REAL NOT NULL,
                breath_rate REAL NOT NULL,
                target_distance REAL NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sleep_events (
                eventID INTEGER PRIMARY KEY AUTOINCREMENT,
                userID INTEGER,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                source TEXT NOT NULL,
                score_delta REAL NOT NULL DEFAULT 0,
                details TEXT,
                fingerprint TEXT NOT NULL UNIQUE
            )
            """
        )
        conn.commit()


def get_lan_ip() -> str:
    """Best-effort local LAN IP discovery without sending useful traffic."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def current_scenario(elapsed: float) -> str:
    with STATE_LOCK:
        forced = state["scenario"]
        forced_until = state["scenario_until"]
    if forced != "auto" and time.time() < forced_until:
        return forced

    cycle = elapsed % 90.0
    if cycle < 55.0:
        return "normal"
    if cycle < 70.0:
        return "abnormal"
    if cycle < 82.0:
        return "no_person"
    return "snore_hint"


def synthesize_phase(elapsed: float, scenario: str, n: int = 180) -> list[float]:
    values: list[float] = []
    for idx in range(n):
        t = elapsed + idx / 30.0
        breath = math.sin(2.0 * math.pi * 0.28 * t)
        heart = 0.18 * math.sin(2.0 * math.pi * 1.2 * t)
        noise = random.uniform(-0.035, 0.035)
        amp = 1.1
        if scenario == "no_person":
            amp = 0.04
            heart = 0.0
        elif scenario == "abnormal":
            amp = 0.75
            heart = 0.08 * math.sin(2.0 * math.pi * 1.65 * t)
        values.append(round(amp * breath + heart + noise, 4))
    return values


def update_mock_state_loop() -> None:
    while True:
        with STATE_LOCK:
            radar_age = seconds_since(state["last_radar_received_at"])
            snore_heartbeat_age = seconds_since(state["last_snore_heartbeat_at"])
            audio_age = seconds_since(state["last_audio_received_at"])
            snore_event_age = seconds_since(state["last_snore_at"])

            radar_online = radar_age is not None and radar_age <= BOARD_TIMEOUT_SECONDS
            snore_online = (
                snore_heartbeat_age is not None and snore_heartbeat_age <= BOARD_TIMEOUT_SECONDS
            ) or (audio_age is not None and audio_age <= BOARD_TIMEOUT_SECONDS)

            state["radar_board_online"] = radar_online
            state["radar_online"] = radar_online
            state["snore_board_online"] = snore_online

            if not radar_online:
                state["heart_rate"] = 0.0
                state["breath_rate"] = 0.0
                state["target_distance"] = 0.0
                state["target_bin"] = 0
                state["phase_values"] = []

            if snore_event_age is None or snore_event_age > SNORE_EVENT_HOLD_SECONDS:
                state["snore_detected"] = False
                if not snore_online:
                    state["snore_score"] = 0.0
                    state["snore_dbfs"] = None

            upsert_timeline_locked()

        time.sleep(0.5)


def state_snapshot() -> dict[str, Any]:
    with STATE_LOCK:
        return json.loads(json.dumps(state))


def normalize_date_filter(date_str: Optional[str]) -> Optional[str]:
    if not date_str or not isinstance(date_str, str):
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str


def row_to_frontend(row: sqlite3.Row) -> dict[str, Any]:
    ts = row["timestamp"]
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        dt = datetime.now()
    return {
        "dataID": row["dataID"],
        "userID": row["userID"],
        "year": dt.year,
        "month": dt.month,
        "day": dt.day,
        "bpm_rader": row["heart_rate"],
        "bpm_finger": row["breath_rate"],
        "target_distance": row["target_distance"],
        "timestamp": ts,
    }


def save_raw_audio_as_wav(raw_audio: bytes, output_file: Path) -> float:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_file), "wb") as wav_file:
        wav_file.setnchannels(NUM_CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(raw_audio)
    return len(raw_audio) / float(SAMPLE_RATE * SAMPLE_WIDTH * NUM_CHANNELS)


def estimate_dbfs(raw_audio: bytes) -> Optional[float]:
    if len(raw_audio) < 2:
        return None
    sample_count = len(raw_audio) // 2
    total = 0.0
    for idx in range(sample_count):
        sample = int.from_bytes(raw_audio[idx * 2 : idx * 2 + 2], "little", signed=True)
        total += sample * sample
    rms = math.sqrt(total / sample_count)
    return round(20.0 * math.log10(rms / 32768.0 + 1e-9), 2)


def snore_level_from_dbfs(dbfs: Optional[float], score: float) -> Optional[float]:
    if dbfs is None:
        return max(0.0, min(1.0, score)) if score > 0 else None
    return round(max(0.0, min(1.0, (float(dbfs) + 45.0) / 33.0)), 3)


def sleep_stage_for(
    heart_rate: Optional[float],
    breath_rate: Optional[float],
    target_distance: float,
    snore_score: float,
    snore_detected: bool,
    radar_online: bool,
) -> str:
    if not radar_online or target_distance <= 0:
        return "未检测到"
    if snore_detected or snore_score >= 0.65:
        return "疑似呼噜扰动"
    if heart_rate is None or breath_rate is None:
        return "浅睡"
    if heart_rate >= 95 or breath_rate >= 23 or heart_rate < 55 or breath_rate < 10:
        return "清醒/异常"
    if 58 <= heart_rate <= 72 and 11 <= breath_rate <= 18 and snore_score < 0.35:
        return "深睡"
    return "浅睡"


def timeline_entry_locked(timestamp: Optional[str] = None) -> dict[str, Any]:
    ts = timestamp or iso_second()
    radar_online = bool(state["radar_online"]) and float(state["target_distance"] or 0) > 0.0
    snore_online = bool(state["snore_board_online"])
    heart_rate = round(float(state["heart_rate"]), 2) if radar_online and state["heart_rate"] else None
    breath_rate = round(float(state["breath_rate"]), 2) if radar_online and state["breath_rate"] else None
    target_distance = round(float(state["target_distance"] or 0.0), 3) if radar_online else 0.0
    snore_score = round(float(state["snore_score"] or 0.0), 3) if snore_online else 0.0
    snore_dbfs = state["snore_dbfs"] if snore_online else None
    snore_level = snore_level_from_dbfs(snore_dbfs, snore_score) if snore_online else None
    snore_detected = bool(state["snore_detected"]) if snore_online else False
    return {
        "timestamp": ts,
        "heart_rate": heart_rate,
        "breath_rate": breath_rate,
        "target_distance": target_distance,
        "snore_score": snore_score,
        "snore_dbfs": snore_dbfs,
        "snore_level": snore_level,
        "snore_detected": snore_detected,
        "radar_online": radar_online,
        "snore_online": snore_online,
        "sleep_stage": sleep_stage_for(
            heart_rate,
            breath_rate,
            target_distance,
            snore_score,
            snore_detected,
            radar_online,
        ),
    }


def trim_timeline_locked() -> None:
    cutoff = time.time() - TIMELINE_RETENTION_SECONDS
    state["timeline"] = [
        row
        for row in state["timeline"]
        if (parse_iso_seconds(row.get("timestamp", "")) or 0) >= cutoff
    ]


def upsert_timeline_locked(timestamp: Optional[str] = None) -> None:
    entry = timeline_entry_locked(timestamp)
    timeline = state["timeline"]
    if timeline and timeline[-1].get("timestamp") == entry["timestamp"]:
        timeline[-1] = entry
    else:
        timeline.append(entry)
    trim_timeline_locked()
    record_sleep_events_locked(entry)


def timeline_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid_hr = [row["heart_rate"] for row in rows if isinstance(row.get("heart_rate"), (int, float))]
    valid_br = [row["breath_rate"] for row in rows if isinstance(row.get("breath_rate"), (int, float))]
    snore_rows = [row for row in rows if row.get("snore_detected")]
    snore_levels = [row["snore_level"] for row in rows if isinstance(row.get("snore_level"), (int, float))]
    latest = rows[-1] if rows else None
    return {
        "points": len(rows),
        "valid_heart_points": len(valid_hr),
        "valid_breath_points": len(valid_br),
        "snore_events": len(snore_rows),
        "avg_snore_level": round(sum(snore_levels) / len(snore_levels), 3) if snore_levels else None,
        "avg_heart_rate": round(sum(valid_hr) / len(valid_hr), 2) if valid_hr else None,
        "avg_breath_rate": round(sum(valid_br) / len(valid_br), 2) if valid_br else None,
        "latest_sleep_stage": latest.get("sleep_stage") if latest else "等待数据",
        "latest_timestamp": latest.get("timestamp") if latest else None,
    }


def average(values: list[float]) -> Optional[float]:
    return round(sum(values) / len(values), 3) if values else None


def standard_deviation(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return round(math.sqrt(variance), 3)


def minute_key(timestamp: str) -> str:
    return timestamp[:16] if timestamp else now_iso()[:16]


def minute_label(timestamp: str) -> str:
    try:
        return datetime.fromisoformat(timestamp).strftime("%H:%M")
    except ValueError:
        return timestamp[-5:] if timestamp else "--:--"


def severity_rank(severity: str) -> int:
    return {"info": 0, "normal": 1, "warning": 2, "critical": 3}.get(severity, 0)


def insert_sleep_event(
    event_type: str,
    severity: str,
    title: str,
    message: str,
    timestamp: str,
    source: str,
    score_delta: float,
    details: Optional[dict[str, Any]] = None,
    user_id: Optional[int] = None,
    fingerprint: Optional[str] = None,
) -> None:
    event_fingerprint = fingerprint or f"{event_type}:{minute_key(timestamp)}"
    try:
        with db_connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO sleep_events
                (userID, event_type, severity, title, message, timestamp, source, score_delta, details, fingerprint)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    event_type,
                    severity,
                    title,
                    message,
                    timestamp,
                    source,
                    score_delta,
                    json.dumps(details or {}, ensure_ascii=False),
                    event_fingerprint,
                ),
            )
            conn.commit()
    except sqlite3.Error as exc:
        print(f"[sleep-events] 写入事件失败: {exc}")


def record_sleep_events_locked(row: dict[str, Any]) -> None:
    """Persist coarse sleep events once per minute for history playback."""
    timestamp = row["timestamp"]
    minute = minute_key(timestamp)
    heart_rate = row.get("heart_rate")
    breath_rate = row.get("breath_rate")
    snore_level = row.get("snore_level")
    target_distance = float(row.get("target_distance") or 0.0)
    radar_board_online = bool(state["radar_board_online"])
    snore_board_online = bool(state["snore_board_online"])
    radar_has_target = bool(row.get("radar_online")) and target_distance > 0

    condition = "normal"
    if not radar_board_online:
        condition = "radar_offline"
        insert_sleep_event(
            "device_offline",
            "critical",
            "雷达板离线",
            "毫米波雷达模拟板超过 5 秒未发送数据，心率和呼吸率会断线。",
            timestamp,
            "radar_board",
            -18,
            {"radar_age_seconds": seconds_since(state["last_radar_received_at"])},
            fingerprint=f"device_offline:radar:{minute}",
        )
    elif not radar_has_target:
        condition = "no_person"
        insert_sleep_event(
            "no_person",
            "warning",
            "疑似离床 / 未检测到人体",
            "雷达板在线，但目标距离为 0，当前未检测到稳定人体目标。",
            timestamp,
            "radar_board",
            -14,
            {"target_distance": target_distance},
            fingerprint=f"no_person:{minute}",
        )

    if not snore_board_online:
        if condition == "normal":
            condition = "snore_offline"
        insert_sleep_event(
            "device_offline",
            "warning",
            "呼噜检测板离线",
            "呼噜检测模拟板超过 5 秒未发送特征或音频片段。",
            timestamp,
            "snore_board",
            -8,
            {"snore_age_seconds": seconds_since(state["last_snore_heartbeat_at"])},
            fingerprint=f"device_offline:snore:{minute}",
        )

    if isinstance(snore_level, (int, float)) and (row.get("snore_detected") or snore_level >= 0.62):
        severity = "critical" if snore_level >= 0.78 else "warning"
        condition = "snore"
        insert_sleep_event(
            "snore",
            severity,
            "呼噜扰动",
            f"检测到呼噜强度约 {snore_level * 100:.0f}%，建议观察其对心率和呼吸的影响。",
            timestamp,
            "snore_board",
            -16 if severity == "critical" else -9,
            {
                "snore_level": snore_level,
                "snore_score": row.get("snore_score"),
                "snore_dbfs": row.get("snore_dbfs"),
            },
            fingerprint=f"snore:{minute}",
        )

    if isinstance(heart_rate, (int, float)) and (heart_rate >= 100 or heart_rate < 55):
        condition = "vital_abnormal"
        insert_sleep_event(
            "heart_abnormal",
            "warning",
            "心率异常波动",
            f"当前心率 {heart_rate:.1f} BPM，超出模拟静息观察范围。",
            timestamp,
            "radar_board",
            -10,
            {"heart_rate": heart_rate},
            fingerprint=f"heart_abnormal:{minute}",
        )

    if isinstance(breath_rate, (int, float)) and (breath_rate >= 24 or breath_rate < 10):
        condition = "vital_abnormal"
        insert_sleep_event(
            "breath_abnormal",
            "warning",
            "呼吸异常波动",
            f"当前呼吸率 {breath_rate:.1f} RPM，超出模拟静息观察范围。",
            timestamp,
            "radar_board",
            -10,
            {"breath_rate": breath_rate},
            fingerprint=f"breath_abnormal:{minute}",
        )

    previous = state.get("last_sleep_condition", "unknown")
    if condition == "normal" and previous not in {"normal", "unknown"}:
        insert_sleep_event(
            "recovered",
            "normal",
            "状态恢复",
            "设备在线且生命体征回到模拟稳定区间。",
            timestamp,
            "mock_api",
            4,
            {"previous_condition": previous},
            fingerprint=f"recovered:{minute}",
        )
    state["last_sleep_condition"] = condition


def rows_between(rows: list[dict[str, Any]], start_ts: float) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if (parse_iso_seconds(row.get("timestamp", "")) or 0.0) >= start_ts
    ]


def sleep_event_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    try:
        details = json.loads(row["details"] or "{}")
    except json.JSONDecodeError:
        details = {}
    return {
        "eventID": row["eventID"],
        "userID": row["userID"],
        "type": row["event_type"],
        "severity": row["severity"],
        "title": row["title"],
        "message": row["message"],
        "timestamp": row["timestamp"],
        "source": row["source"],
        "score_delta": row["score_delta"],
        "details": details,
    }


def load_sleep_events(
    start_iso: Optional[str] = None,
    end_iso: Optional[str] = None,
    date: Optional[str] = None,
    user_id: Optional[int] = None,
    limit: int = 160,
) -> list[dict[str, Any]]:
    where_parts: list[str] = []
    params: list[Any] = []
    if start_iso:
        where_parts.append("timestamp >= ?")
        params.append(start_iso)
    if end_iso:
        where_parts.append("timestamp <= ?")
        params.append(end_iso)
    normalized_date = normalize_date_filter(date)
    if normalized_date:
        where_parts.append("date(timestamp) = ?")
        params.append(normalized_date)
    if user_id:
        where_parts.append("(userID IS NULL OR userID = ?)")
        params.append(user_id)
    where_sql = " WHERE " + " AND ".join(where_parts) if where_parts else ""
    with db_connect() as conn:
        rows = conn.execute(
            f"""
            SELECT eventID, userID, event_type, severity, title, message, timestamp,
                   source, score_delta, details
            FROM sleep_events
            {where_sql}
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()
    return [sleep_event_to_dict(row) for row in rows]


def load_history_rows(date: Optional[str], user_id: Optional[int]) -> list[dict[str, Any]]:
    where_parts: list[str] = []
    params: list[Any] = []
    if user_id:
        where_parts.append("userID = ?")
        params.append(user_id)
    normalized_date = normalize_date_filter(date)
    if normalized_date:
        where_parts.append("date(timestamp) = ?")
        params.append(normalized_date)
    where_sql = " WHERE " + " AND ".join(where_parts) if where_parts else ""
    with db_connect() as conn:
        rows = conn.execute(
            f"""
            SELECT heart_rate, breath_rate, target_distance, timestamp
            FROM heart_data
            {where_sql}
            ORDER BY timestamp ASC
            LIMIT 2000
            """,
            params,
        ).fetchall()
    return [
        {
            "timestamp": row["timestamp"],
            "heart_rate": row["heart_rate"],
            "breath_rate": row["breath_rate"],
            "target_distance": row["target_distance"],
            "snore_score": 0.0,
            "snore_dbfs": None,
            "snore_level": None,
            "snore_detected": False,
            "radar_online": row["target_distance"] > 0,
            "snore_online": None,
            "sleep_stage": sleep_stage_for(
                row["heart_rate"],
                row["breath_rate"],
                row["target_distance"],
                0.0,
                False,
                row["target_distance"] > 0,
            ),
        }
        for row in rows
    ]


def build_snore_heatmap(rows: list[dict[str, Any]], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = minute_key(row.get("timestamp", ""))
        bucket = buckets.setdefault(
            key,
            {
                "timestamp": f"{key}:00",
                "label": minute_label(f"{key}:00"),
                "snore_values": [],
                "heart_values": [],
                "breath_values": [],
                "snore_events": 0,
            },
        )
        if isinstance(row.get("snore_level"), (int, float)):
            bucket["snore_values"].append(float(row["snore_level"]))
        if row.get("snore_detected"):
            bucket["snore_events"] += 1
        if isinstance(row.get("heart_rate"), (int, float)):
            bucket["heart_values"].append(float(row["heart_rate"]))
        if isinstance(row.get("breath_rate"), (int, float)):
            bucket["breath_values"].append(float(row["breath_rate"]))

    for event in events:
        if event.get("type") != "snore":
            continue
        key = minute_key(event.get("timestamp", ""))
        details = event.get("details") or {}
        bucket = buckets.setdefault(
            key,
            {
                "timestamp": f"{key}:00",
                "label": minute_label(f"{key}:00"),
                "snore_values": [],
                "heart_values": [],
                "breath_values": [],
                "snore_events": 0,
            },
        )
        level = details.get("snore_level")
        if isinstance(level, (int, float)):
            bucket["snore_values"].append(float(level))
        bucket["snore_events"] += 1

    result: list[dict[str, Any]] = []
    previous_hr: Optional[float] = None
    previous_br: Optional[float] = None
    for key in sorted(buckets):
        bucket = buckets[key]
        avg_snore = average(bucket["snore_values"]) or 0.0
        max_snore = max(bucket["snore_values"]) if bucket["snore_values"] else 0.0
        avg_hr = average(bucket["heart_values"])
        avg_br = average(bucket["breath_values"])
        heart_delta = round(avg_hr - previous_hr, 2) if avg_hr is not None and previous_hr is not None else None
        breath_delta = round(avg_br - previous_br, 2) if avg_br is not None and previous_br is not None else None
        if avg_hr is not None:
            previous_hr = avg_hr
        if avg_br is not None:
            previous_br = avg_br
        intensity = min(1.0, avg_snore * 0.82 + min(1.0, bucket["snore_events"] / 4.0) * 0.18)
        severity = "critical" if intensity >= 0.7 else "warning" if intensity >= 0.38 else "info"
        result.append(
            {
                "timestamp": bucket["timestamp"],
                "label": bucket["label"],
                "avg_snore_level": round(avg_snore, 3),
                "max_snore_level": round(max_snore, 3),
                "snore_events": bucket["snore_events"],
                "heart_delta": heart_delta,
                "breath_delta": breath_delta,
                "intensity": round(intensity, 3),
                "severity": severity,
            }
        )
    return result[-90:]


def compute_sleep_score(rows: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows and not events:
        return {
            "score": 0,
            "label": "等待数据",
            "summary": "启动模拟后端和两个模拟开发板后，睡眠看护驾驶舱会开始生成评分。",
            "penalties": [],
        }

    heart_values = numeric_values(rows, "heart_rate")
    breath_values = numeric_values(rows, "breath_rate")
    snore_levels = numeric_values(rows, "snore_level")
    total_rows = max(len(rows), 1)
    radar_offline_ratio = sum(1 for row in rows if row.get("radar_online") is False) / total_rows if rows else 0.0
    snore_offline_ratio = sum(1 for row in rows if row.get("snore_online") is False) / total_rows if rows else 0.0
    no_person_ratio = sum(1 for row in rows if row.get("radar_online") is False or float(row.get("target_distance") or 0) <= 0) / total_rows if rows else 0.0
    snore_event_count = sum(1 for row in rows if row.get("snore_detected")) + sum(1 for event in events if event.get("type") == "snore")

    penalties: list[dict[str, Any]] = []
    if len(rows) < 10:
        penalties.append({"name": "数据不足", "value": 10, "reason": "有效时间轴少于 10 个点"})

    if heart_values:
        hr_std = standard_deviation(heart_values)
        penalty = min(16.0, hr_std * 1.8)
        if penalty >= 2:
            penalties.append({"name": "心率波动", "value": round(penalty, 1), "reason": f"心率标准差 {hr_std:.1f} BPM"})
    if breath_values:
        br_std = standard_deviation(breath_values)
        penalty = min(16.0, br_std * 3.2)
        if penalty >= 2:
            penalties.append({"name": "呼吸波动", "value": round(penalty, 1), "reason": f"呼吸率标准差 {br_std:.1f} RPM"})
    if snore_levels or snore_event_count:
        avg_snore = average(snore_levels) or 0.0
        penalty = min(28.0, avg_snore * 20.0 + snore_event_count * 0.6)
        if penalty >= 2:
            penalties.append({"name": "呼噜扰动", "value": round(penalty, 1), "reason": f"平均呼噜强度 {avg_snore * 100:.0f}%，事件点 {snore_event_count} 个"})
    if radar_offline_ratio > 0:
        penalties.append({"name": "雷达掉线", "value": round(min(22.0, radar_offline_ratio * 34.0), 1), "reason": f"雷达断线占比 {radar_offline_ratio * 100:.0f}%"})
    if snore_offline_ratio > 0:
        penalties.append({"name": "呼噜板掉线", "value": round(min(14.0, snore_offline_ratio * 24.0), 1), "reason": f"呼噜板断线占比 {snore_offline_ratio * 100:.0f}%"})
    if no_person_ratio > 0.08:
        penalties.append({"name": "疑似离床", "value": round(min(24.0, no_person_ratio * 32.0), 1), "reason": f"未检测到人体占比 {no_person_ratio * 100:.0f}%"})

    score = max(0, min(100, round(100.0 - sum(float(item["value"]) for item in penalties))))
    event_severities = [event.get("severity", "info") for event in events]
    worst_event = max(event_severities, key=severity_rank) if event_severities else "info"
    if radar_offline_ratio > 0.25 or worst_event == "critical":
        label = "设备异常" if radar_offline_ratio > 0.25 else "呼噜频繁"
    elif no_person_ratio > 0.12:
        label = "疑似离床"
    elif score >= 86:
        label = "稳定睡眠"
    elif score >= 68:
        label = "轻度扰动"
    else:
        label = "需要关注"

    main_reason = penalties[0]["reason"] if penalties else "当前窗口内心率、呼吸和呼噜数据整体平稳"
    return {
        "score": score,
        "label": label,
        "summary": main_reason,
        "penalties": penalties,
    }


def build_stability_cards(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    heart_values = numeric_values(rows, "heart_rate")
    breath_values = numeric_values(rows, "breath_rate")
    snore_levels = numeric_values(rows, "snore_level")
    cards = [
        {
            "key": "heart",
            "title": "心率稳定性",
            "value": round(max(0, 100 - standard_deviation(heart_values) * 8)) if heart_values else 0,
            "unit": "%",
            "detail": f"平均 {average(heart_values) or '--'} BPM，样本 {len(heart_values)}",
        },
        {
            "key": "breath",
            "title": "呼吸稳定性",
            "value": round(max(0, 100 - standard_deviation(breath_values) * 16)) if breath_values else 0,
            "unit": "%",
            "detail": f"平均 {average(breath_values) or '--'} RPM，样本 {len(breath_values)}",
        },
        {
            "key": "snore",
            "title": "呼噜安静度",
            "value": round(max(0, 100 - (average(snore_levels) or 0) * 100)) if snore_levels else 100,
            "unit": "%",
            "detail": f"平均强度 {round((average(snore_levels) or 0) * 100)}%，样本 {len(snore_levels)}",
        },
    ]
    return cards


def build_sleep_overview(
    rows: list[dict[str, Any]],
    events: list[dict[str, Any]],
    mode: str,
    seconds: int,
    date: Optional[str],
    user_id: Optional[int],
    devices: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    events_sorted = sorted(events, key=lambda item: item.get("timestamp", ""), reverse=True)
    heatmap = build_snore_heatmap(rows, events_sorted)
    score = compute_sleep_score(rows, events_sorted)
    stats = timeline_summary(rows)
    worst = max(heatmap, key=lambda item: item["intensity"], default=None)
    return {
        "code": 200,
        "status": "success",
        "mode": mode,
        "seconds": seconds,
        "date": normalize_date_filter(date),
        "userID": user_id,
        "generated_at": now_iso(),
        "score": score,
        "stats": {
            **stats,
            "event_count": len(events_sorted),
            "critical_event_count": sum(1 for event in events_sorted if event.get("severity") == "critical"),
            "warning_event_count": sum(1 for event in events_sorted if event.get("severity") == "warning"),
        },
        "devices": devices or {},
        "heatmap": heatmap,
        "worst_disturbance": worst,
        "events": events_sorted[:120],
        "stability_cards": build_stability_cards(rows),
    }


def numeric_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return values


def local_vitals_report(rows: list[dict[str, Any]], reason: str = "") -> str:
    heart_values = numeric_values(rows, "bpm_rader") or numeric_values(rows, "heart_rate")
    breath_values = numeric_values(rows, "bpm_finger") or numeric_values(rows, "breath_rate")
    if not heart_values or not breath_values:
        return "暂无足够有效的心率和呼吸率数据，暂时无法生成分析。请先运行雷达模拟板并积累历史数据。"

    avg_hr = sum(heart_values) / len(heart_values)
    avg_br = sum(breath_values) / len(breath_values)
    max_hr = max(heart_values)
    min_hr = min(heart_values)
    max_br = max(breath_values)
    min_br = min(breath_values)
    risks: list[str] = []
    if max_hr >= 100:
        risks.append("出现过偏快心率")
    if min_hr < 60:
        risks.append("出现过偏慢心率")
    if max_br > 24:
        risks.append("出现过呼吸偏快")
    if min_br < 10:
        risks.append("出现过呼吸偏慢")
    risk_text = "、".join(risks) if risks else "本页数据整体处于常见静息范围"
    prefix = f"本地规则分析（{reason}）\n" if reason else "本地规则分析\n"
    return (
        f"{prefix}"
        f"平均心率约 {avg_hr:.1f} BPM，范围 {min_hr:.1f}–{max_hr:.1f} BPM。\n"
        f"平均呼吸率约 {avg_br:.1f} RPM，范围 {min_br:.1f}–{max_br:.1f} RPM。\n"
        f"初步判断：{risk_text}。\n"
        "建议：保持模拟板连续运行以积累更长时间数据；若后续接入真实硬件，请结合实际佩戴/距离和人工标注一起判断。"
    )


def build_ai_prompt(rows: list[dict[str, Any]], date: Optional[str], user_id: Optional[int]) -> str:
    rows = rows[:100]
    return (
        "你是一名谨慎、专业的睡眠与生命体征监测助手。"
        "请基于以下雷达历史数据生成中文分析报告，避免夸大诊断，只给演示性质建议。\n"
        f"用户ID：{user_id or '未知'}；日期筛选：{date or '未指定'}。\n"
        "数据字段中 bpm_rader 表示心率 BPM，bpm_finger 表示呼吸率 RPM。\n"
        f"数据JSON：{json.dumps(rows, ensure_ascii=False)}\n"
        "请输出：1.总体结论；2.异常点；3.睡眠/呼吸观察；4.一到两条建议。不要使用Markdown表格。"
    )


def call_deepseek(prompt: str) -> str:
    api_key = config_value("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY")
    base_url = config_value("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = config_value("DEEPSEEK_MODEL", "deepseek-v4-flash")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": 800,
        "temperature": 0.35,
    }
    req = UrlRequest(
        f"{base_url}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(req, timeout=DEEPSEEK_TIMEOUT_SECONDS) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = data.get("choices", [{}])[0].get("message", {}).get("content")
    if not content:
        raise RuntimeError("DeepSeek 未返回有效内容")
    return str(content).strip()


@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    if not getattr(app.state, "mock_thread_started", False):
        thread = threading.Thread(target=update_mock_state_loop, daemon=True)
        thread.start()
        app.state.mock_thread_started = True
    lan_ip = get_lan_ip()
    print("=" * 72)
    print("无硬件模拟后端已启动")
    print(f"本机访问: http://localhost:{API_PORT}")
    print(f"局域网访问: http://{lan_ip}:{API_PORT}")
    print("前端默认使用 http://localhost:8081；如果换电脑访问，请设置 VITE_API_BASE_URL。")
    print("=" * 72)


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "message": "无硬件模拟后端正在运行",
        "api": f"http://localhost:{API_PORT}",
        "status": "ok",
    }


@app.get("/heartrate")
async def get_heart_rate() -> dict[str, Any]:
    snapshot = state_snapshot()
    return {
        "heart_rate": snapshot["heart_rate"],
        "timestamp": time.time(),
        "status": "ok" if snapshot["radar_online"] and snapshot["target_distance"] > 0 else "no_data",
    }


@app.get("/target")
async def get_target_data() -> dict[str, Any]:
    snapshot = state_snapshot()
    has_radar = bool(snapshot["radar_online"]) and snapshot["target_distance"] > 0
    return {
        "heart_rate": snapshot["heart_rate"],
        "breath_rate": snapshot["breath_rate"],
        "target_distance": snapshot["target_distance"],
        "target_bin": snapshot["target_bin"],
        "phase_values": snapshot["phase_values"][-80:],
        "snore_score": snapshot["snore_score"],
        "snore_dbfs": snapshot["snore_dbfs"],
        "snore_level": snore_level_from_dbfs(snapshot["snore_dbfs"], snapshot["snore_score"]),
        "snore_detected": snapshot["snore_detected"],
        "sleep_stage": sleep_stage_for(
            snapshot["heart_rate"] if snapshot["radar_online"] else None,
            snapshot["breath_rate"] if snapshot["radar_online"] else None,
            snapshot["target_distance"],
            snapshot["snore_score"],
            snapshot["snore_detected"],
            snapshot["radar_online"],
        ),
        "timestamp": time.time(),
        "status": "ok" if has_radar else "no_data",
    }


@app.get("/detailed")
async def get_detailed_data() -> dict[str, Any]:
    snapshot = state_snapshot()
    snapshot["timestamp"] = time.time()
    snapshot["processing_count"] = snapshot["frame_count"]
    snapshot["status"] = "ok" if snapshot["radar_online"] and snapshot["target_distance"] > 0 else "no_data"
    return snapshot


@app.get("/status")
async def get_status() -> dict[str, Any]:
    snapshot = state_snapshot()
    radar_age = seconds_since(snapshot["last_radar_received_at"])
    snore_age = seconds_since(snapshot["last_snore_heartbeat_at"])
    return {
        "running": snapshot["running"],
        "radar_online": snapshot["radar_online"],
        "radar_board_online": snapshot["radar_board_online"],
        "snore_board_online": snapshot["snore_board_online"],
        "scenario": current_scenario(time.time() - snapshot["start_time"]),
        "total_frames": snapshot["frame_count"],
        "processed_frames": snapshot["frame_count"],
        "uptime": time.time() - snapshot["start_time"],
        "last_frame": snapshot["frame_count"],
        "last_radar_frame_number": snapshot["last_radar_frame_number"],
        "last_radar_received_at": snapshot["last_radar_received_at"],
        "last_snore_heartbeat_at": snapshot["last_snore_heartbeat_at"],
        "radar_age_seconds": round(radar_age, 2) if radar_age is not None else None,
        "snore_age_seconds": round(snore_age, 2) if snore_age is not None else None,
        "audio_upload_count": snapshot["audio_upload_count"],
        "last_audio_received_at": snapshot["last_audio_received_at"],
        "last_audio_file": snapshot["last_audio_file"],
        "last_audio_seconds": snapshot["last_audio_seconds"],
        "last_audio_dbfs": snapshot["last_audio_dbfs"],
        "snore_score": snapshot["snore_score"],
        "snore_dbfs": snapshot["snore_dbfs"],
        "snore_level": snore_level_from_dbfs(snapshot["snore_dbfs"], snapshot["snore_score"]),
        "snore_detected": snapshot["snore_detected"],
        "snore_event_count": snapshot["snore_event_count"],
        "last_snore_at": snapshot["last_snore_at"],
        "sleep_stage": sleep_stage_for(
            snapshot["heart_rate"] if snapshot["radar_online"] else None,
            snapshot["breath_rate"] if snapshot["radar_online"] else None,
            snapshot["target_distance"],
            snapshot["snore_score"],
            snapshot["snore_detected"],
            snapshot["radar_online"],
        ),
        "timeline_points": len(snapshot["timeline"]),
        "timestamp": time.time(),
    }


@app.get("/timeline")
async def get_timeline(seconds: int = Query(180, ge=10, le=1800)) -> dict[str, Any]:
    cutoff = time.time() - float(seconds)
    with STATE_LOCK:
        upsert_timeline_locked()
        rows = [
            row
            for row in state["timeline"]
            if (parse_iso_seconds(row.get("timestamp", "")) or 0) >= cutoff
        ]
        rows = json.loads(json.dumps(rows))
    return {
        "code": 200,
        "status": "success",
        "seconds": seconds,
        "data": rows,
        "summary": timeline_summary(rows),
    }


@app.get("/sleep/overview")
async def get_sleep_overview(
    mode: str = Query("live"),
    seconds: int = Query(1800, ge=60, le=7200),
    date: Optional[str] = Query(None),
    userID: Optional[int] = Query(None),
) -> dict[str, Any]:
    selected_mode = "history" if mode == "history" else "live"
    if selected_mode == "history":
        history_rows = load_history_rows(date, userID)
        history_events = load_sleep_events(date=date, user_id=userID, limit=400)
        return build_sleep_overview(
            history_rows,
            history_events,
            "history",
            seconds,
            date,
            userID,
            devices={"radar_board_online": None, "snore_board_online": None},
        )

    cutoff = time.time() - float(seconds)
    cutoff_iso = datetime.fromtimestamp(cutoff).isoformat(timespec="seconds")
    with STATE_LOCK:
        upsert_timeline_locked()
        rows = rows_between(state["timeline"], cutoff)
        rows = json.loads(json.dumps(rows))
        devices = {
            "radar_board_online": bool(state["radar_board_online"]),
            "snore_board_online": bool(state["snore_board_online"]),
            "radar_age_seconds": seconds_since(state["last_radar_received_at"]),
            "snore_age_seconds": seconds_since(state["last_snore_heartbeat_at"]),
            "audio_upload_count": state["audio_upload_count"],
            "last_audio_received_at": state["last_audio_received_at"],
        }
    events = load_sleep_events(start_iso=cutoff_iso, limit=260)
    return build_sleep_overview(rows, events, "live", seconds, date, userID, devices)


@app.post("/mock/radar-frame")
async def receive_mock_radar_frame(frame: RadarFrameData) -> dict[str, Any]:
    with STATE_LOCK:
        state["frame_count"] += 1
        state["last_radar_frame_number"] = int(frame.frame_number)
        state["last_radar_received_at"] = now_iso()
        state["radar_online"] = True
        state["radar_board_online"] = True
        state["heart_rate"] = round(float(frame.heart_rate), 2)
        state["breath_rate"] = round(float(frame.breath_rate), 2)
        state["target_distance"] = round(float(frame.target_distance), 3)
        state["target_bin"] = int(frame.target_bin)
        state["phase_values"] = [round(float(v), 4) for v in frame.phase_values[-240:]]
        state["last_device_message"] = f"radar frame #{frame.frame_number} from {frame.source}"
        upsert_timeline_locked()
    return {
        "code": 200,
        "status": "success",
        "message": "雷达模拟帧已接收",
        "frame_number": frame.frame_number,
    }


@app.post("/mock/snore-heartbeat")
async def receive_mock_snore_heartbeat(heartbeat: SnoreHeartbeat) -> dict[str, Any]:
    score = max(0.0, min(1.0, float(heartbeat.snore_score)))
    with STATE_LOCK:
        state["last_snore_heartbeat_at"] = now_iso()
        state["snore_board_online"] = True
        state["snore_score"] = round(score, 3)
        if heartbeat.dbfs is not None:
            state["snore_dbfs"] = heartbeat.dbfs
            state["last_audio_dbfs"] = heartbeat.dbfs
        state["last_device_message"] = f"snore heartbeat from {heartbeat.source}"
        if heartbeat.snore_detected:
            state["snore_detected"] = True
            state["snore_event_count"] += 1
            state["last_snore_at"] = now_iso()
        else:
            recent_snore = seconds_since(state["last_snore_at"])
            state["snore_detected"] = recent_snore is not None and recent_snore <= SNORE_EVENT_HOLD_SECONDS
        upsert_timeline_locked()
    return {
        "code": 200,
        "status": "success",
        "message": "呼噜检测板心跳已接收",
        "snore_score": round(score, 3),
        "snore_dbfs": heartbeat.dbfs,
        "snore_level": snore_level_from_dbfs(heartbeat.dbfs, score),
        "snore_detected": state_snapshot()["snore_detected"],
    }


@app.post("/register")
async def register(user: UserRegister) -> dict[str, Any]:
    try:
        with db_connect() as conn:
            cursor = conn.execute(
                "INSERT INTO user_info (userName, passWord, email) VALUES (?, ?, ?)",
                (user.userName, password_hash(user.passWord), user.email),
            )
            conn.commit()
            user_id = cursor.lastrowid
        return {
            "code": 200,
            "status": "success",
            "message": "用户注册成功",
            "user_id": user_id,
            "userName": user.userName,
        }
    except sqlite3.IntegrityError:
        return {"code": 409, "status": "error", "message": "用户名已存在"}


@app.post("/login")
async def login(user: UserLogin) -> dict[str, Any]:
    with db_connect() as conn:
        row = conn.execute(
            "SELECT * FROM user_info WHERE userName = ?",
            (user.userName,),
        ).fetchone()
    if row is None:
        return {"code": 404, "status": "error", "message": "用户名不存在，请先注册"}
    if row["passWord"] != password_hash(user.passWord):
        return {"code": 401, "status": "error", "message": "密码错误"}
    return {
        "code": 200,
        "status": "success",
        "message": "登录成功",
        "user_id": row["userID"],
        "userName": row["userName"],
        "email": row["email"],
    }


@app.post("/save-vitals-with-user")
async def save_vitals_with_user_endpoint(data: VitalsData) -> dict[str, Any]:
    timestamp = data.timestamp
    if timestamp:
        try:
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).isoformat(timespec="seconds")
        except ValueError:
            timestamp = now_iso()
    else:
        timestamp = now_iso()

    with db_connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO heart_data (userID, heart_rate, breath_rate, target_distance, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (data.userID, data.heart_rate, data.breath_rate, data.target_distance, timestamp),
        )
        conn.commit()
        data_id = cursor.lastrowid
    return {"code": 200, "status": "success", "message": "生命体征数据保存成功", "dataID": data_id}


@app.get("/heartdata/selectPage")
async def select_heart_data_page(
    pageNum: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    date: Optional[str] = Query(None),
    userID: Optional[int] = Query(None),
) -> dict[str, Any]:
    offset = (pageNum - 1) * pageSize
    where_parts: list[str] = []
    params: list[Any] = []

    if userID:
        where_parts.append("userID = ?")
        params.append(userID)

    normalized_date = normalize_date_filter(date)
    if normalized_date:
        where_parts.append("date(timestamp) = ?")
        params.append(normalized_date)

    where_sql = " WHERE " + " AND ".join(where_parts) if where_parts else ""
    with db_connect() as conn:
        total_row = conn.execute(f"SELECT COUNT(*) AS total FROM heart_data{where_sql}", params).fetchone()
        rows = conn.execute(
            f"""
            SELECT dataID, userID, heart_rate, breath_rate, target_distance, timestamp
            FROM heart_data
            {where_sql}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
            """,
            params + [pageSize, offset],
        ).fetchall()
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "list": [row_to_frontend(row) for row in rows],
            "total": int(total_row["total"] if total_row else 0),
        },
    }


@app.post("/ai/analyze-vitals")
async def analyze_vitals(req: AiAnalysisRequest) -> dict[str, Any]:
    rows = req.rows[:100]
    if not rows:
        return {
            "code": 400,
            "status": "error",
            "provider": "local",
            "report": "暂无数据，无法进行 AI 分析。",
        }

    local_report = local_vitals_report(rows)
    prompt = build_ai_prompt(rows, req.date, req.userID)
    try:
        report = await asyncio.to_thread(call_deepseek, prompt)
        return {
            "code": 200,
            "status": "success",
            "provider": "deepseek",
            "model": config_value("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            "fallback": False,
            "report": report,
        }
    except HTTPError as exc:
        reason = f"DeepSeek HTTP {exc.code}，已使用本地规则兜底"
    except URLError as exc:
        reason = f"DeepSeek 网络不可达：{exc.reason}，已使用本地规则兜底"
    except Exception as exc:
        reason = f"{exc}，已使用本地规则兜底"

    return {
        "code": 200,
        "status": "fallback",
        "provider": "local",
        "fallback": True,
        "warning": reason,
        "report": local_vitals_report(rows, reason),
        "local_report": local_report,
    }


@app.post("/audio")
async def receive_audio(request: Request) -> dict[str, Any]:
    body = await request.body()
    if not body:
        return {"code": 400, "status": "error", "message": "没有收到音频数据"}

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if body[:4] == b"RIFF":
        output_file = AUDIO_DIR / f"received_audio_{timestamp}.wav"
        output_file.write_bytes(body)
        seconds = 0.0
        try:
            with wave.open(str(output_file), "rb") as wav_file:
                seconds = wav_file.getnframes() / float(wav_file.getframerate())
        except wave.Error:
            seconds = len(body) / float(SAMPLE_RATE * SAMPLE_WIDTH * NUM_CHANNELS)
        raw_for_db = body[44:] if len(body) > 44 else body
    else:
        output_file = AUDIO_DIR / f"received_audio_{timestamp}.wav"
        seconds = save_raw_audio_as_wav(body, output_file)
        raw_for_db = body

    dbfs = estimate_dbfs(raw_for_db)
    if dbfs is None:
        snore_score = 0.0
    else:
        snore_score = max(0.0, min(1.0, (dbfs + 45.0) / 35.0))
    snore_detected = snore_score >= 0.55 or seconds >= 8.0

    with STATE_LOCK:
        state["audio_upload_count"] += 1
        state["last_audio_received_at"] = now_iso()
        state["last_snore_heartbeat_at"] = state["last_audio_received_at"]
        state["snore_board_online"] = True
        state["last_audio_file"] = str(output_file)
        state["last_audio_seconds"] = round(seconds, 2)
        state["last_audio_dbfs"] = dbfs
        state["snore_dbfs"] = dbfs
        state["snore_score"] = round(snore_score, 3)
        state["snore_detected"] = bool(snore_detected)
        state["last_device_message"] = f"received audio {output_file.name}"
        if snore_detected:
            state["snore_event_count"] += 1
            state["last_snore_at"] = now_iso()
        upsert_timeline_locked()

    return {
        "code": 200,
        "status": "success",
        "message": "音频已接收",
        "file": str(output_file),
        "seconds": round(seconds, 2),
        "dbfs": dbfs,
        "snore_score": round(snore_score, 3),
        "snore_level": snore_level_from_dbfs(dbfs, snore_score),
        "snore_detected": snore_detected,
    }


@app.post("/mock/scenario")
async def set_mock_scenario(req: ScenarioRequest) -> dict[str, Any]:
    valid = {"auto", "normal", "abnormal", "no_person", "snore_hint"}
    scenario = req.scenario if req.scenario in valid else "auto"
    with STATE_LOCK:
        state["scenario"] = scenario
        state["scenario_until"] = time.time() + max(1.0, req.seconds)
        if req.message:
            state["last_device_message"] = req.message
    return {"code": 200, "status": "success", "scenario": scenario, "seconds": req.seconds}


def main() -> None:
    if uvicorn is None:
        raise RuntimeError("缺少 uvicorn。请先在 conda 环境 radar 中安装 backend/requirements.txt。")
    uvicorn.run("mock_hardware_api:app", host=API_HOST, port=API_PORT, reload=False)


if __name__ == "__main__":
    main()
