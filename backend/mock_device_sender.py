#!/usr/bin/env python3
"""
Mock hardware sender for the no-board demo.

Modes:
- --audio: simulate the snore board uploading 10 seconds of raw PCM via HTTP.
- --radar-udp: simulate the radar Wi-Fi board sending UDP frames.
- --radar-board: keep sending radar readings like a real radar board.
- --snore-board: send 1-second snore features and periodic 10-second audio chunks.
- --demo: drive a short front-end visible demo through the mock API.
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import struct
import sys
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SAMPLE_RATE = 16000
CHANNELS = 2
SAMPLE_WIDTH = 2
RADAR_SAMPLES_PER_FRAME = 512
RADAR_FRAME_RATE = 30.0
NETWORK_ERRORS = (TimeoutError, OSError, HTTPError, URLError, ConnectionError)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def make_snore_like_pcm(seconds: float, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Create stereo int16 PCM that looks like a low-frequency snore burst."""
    total_frames = int(seconds * sample_rate)
    chunks = bytearray()
    for n in range(total_frames):
        t = n / sample_rate
        base = 0.15 * math.sin(2.0 * math.pi * 180.0 * t)
        room = 0.03 * math.sin(2.0 * math.pi * 50.0 * t)

        burst_window = 0.0
        # Three obvious snore-like bursts in the middle of the sample.
        for center in (2.3, 4.7, 7.1):
            distance = abs(t - center)
            if distance < 0.8:
                burst_window = max(burst_window, 0.5 + 0.5 * math.cos(math.pi * distance / 0.8))

        snore = burst_window * (
            0.52 * math.sin(2.0 * math.pi * 82.0 * t)
            + 0.25 * math.sin(2.0 * math.pi * 164.0 * t)
            + 0.12 * math.sin(2.0 * math.pi * 246.0 * t)
        )
        sample = int(clamp(base + room + snore, -0.95, 0.95) * 32767)
        # Board code treats interleaved stereo samples as consecutive PCM.
        chunks += struct.pack("<hh", sample, sample)
    return bytes(chunks)


def post_json(url: str, payload: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_audio(host: str, api_port: int, seconds: float) -> None:
    audio = make_snore_like_pcm(seconds)
    url = f"http://{host}:{api_port}/audio"
    print(f"[audio] POST {url} bytes={len(audio)} seconds={seconds:.1f}")
    req = Request(
        url,
        data=audio,
        headers={
            "Content-Type": "audio/wav",
            "Content-Length": str(len(audio)),
            "Connection": "close",
        },
        method="POST",
    )
    with urlopen(req, timeout=20) as resp:
        text = resp.read().decode("utf-8")
    print(f"[audio] response: {text}")


def radar_sample_value(frame_no: int, sample_idx: int, target_bin: int = 30) -> float:
    frame_phase = 2.0 * math.pi * (0.28 * frame_no / RADAR_FRAME_RATE)
    bin_phase = 2.0 * math.pi * target_bin * sample_idx / RADAR_SAMPLES_PER_FRAME
    vital_motion = 0.12 * math.sin(frame_phase) + 0.03 * math.sin(4.5 * frame_phase)
    carrier = math.sin(bin_phase + vital_motion)
    clutter = 0.05 * math.sin(2.0 * math.pi * 3.0 * sample_idx / RADAR_SAMPLES_PER_FRAME)
    return clamp(0.45 * carrier + clutter, -1.0, 1.0)


def make_radar_packet(frame_no: int) -> bytes:
    packet = bytearray()
    packet.append(1)  # RADAR_DATA_COMMAND
    packet.append(0)  # DUMMY_BYTE
    packet += int(frame_no).to_bytes(4, "little", signed=False)
    for i in range(RADAR_SAMPLES_PER_FRAME):
        packet += struct.pack("<e", radar_sample_value(frame_no, i))
    return bytes(packet)


def send_radar_udp(host: str, port: int, seconds: float, frame_rate: float) -> None:
    total_frames = max(1, int(seconds * frame_rate))
    interval = 1.0 / frame_rate
    print(f"[radar] UDP {host}:{port} frames={total_frames} rate={frame_rate:.1f}Hz")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        start = time.time()
        for frame_no in range(1, total_frames + 1):
            sock.sendto(make_radar_packet(frame_no), (host, port))
            next_time = start + frame_no * interval
            sleep_for = next_time - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)
    print("[radar] done")


def synthesize_phase(elapsed: float, n: int = 180) -> list[float]:
    points: list[float] = []
    for idx in range(n):
        t = elapsed + idx / 30.0
        breath = math.sin(2.0 * math.pi * 0.27 * t)
        heart = 0.16 * math.sin(2.0 * math.pi * 1.18 * t)
        drift = 0.08 * math.sin(2.0 * math.pi * 0.035 * t)
        points.append(round(breath + heart + drift, 4))
    return points


def make_radar_frame_payload(frame_no: int) -> dict[str, Any]:
    elapsed = frame_no
    cycle = elapsed % 90
    if cycle < 55:
        distance = 0.82 + 0.04 * math.sin(elapsed * 0.08)
        shared = math.sin(elapsed * 0.105)
        heart_rate = 73.0 + 4.3 * shared + 2.4 * math.sin(elapsed * 0.41 + 0.8)
        breath_rate = 18.0 + 1.5 * shared + 1.1 * math.sin(elapsed * 0.19 - 1.1)
        status = "ok"
    elif cycle < 72:
        distance = 0.79 + 0.03 * math.sin(elapsed * 0.11)
        surge = math.sin((cycle - 55) / 17.0 * math.pi)
        heart_rate = 96.0 + 13.0 * surge + 3.0 * math.sin(elapsed * 0.52)
        breath_rate = 23.0 + 5.0 * surge + 1.6 * math.sin(elapsed * 0.29 + 0.5)
        status = "abnormal"
    elif cycle < 82:
        distance = 0.0
        heart_rate = 0.0
        breath_rate = 0.0
        status = "no_person"
    else:
        distance = 0.85 + 0.03 * math.sin(elapsed * 0.09)
        snore_phase = (cycle - 82) / 8.0
        heart_rate = 70.0 + 4.5 * math.sin(elapsed * 0.24 + 1.2) + 2.5 * snore_phase
        breath_rate = 16.0 + 2.0 * math.sin(elapsed * 0.16 - 0.7) + 0.9 * math.sin(elapsed * 0.63)
        status = "snore_window"

    target_bin = int(round(distance / 0.027)) if distance > 0 else 0
    phase = synthesize_phase(elapsed) if distance > 0 else []
    return {
        "frame_number": frame_no,
        "heart_rate": round(heart_rate, 2),
        "breath_rate": round(breath_rate, 2),
        "target_distance": round(distance, 3),
        "target_bin": target_bin,
        "phase_values": phase,
        "status": status,
        "source": "mock_radar_board",
    }


def run_radar_board(
    host: str,
    api_port: int,
    interval: float,
    run_seconds: float,
    udp_host: str,
    udp_port: int,
    send_udp: bool,
) -> None:
    base = f"http://{host}:{api_port}"
    print(f"[radar-board] online -> {base}/mock/radar-frame")
    print("[radar-board] press Ctrl+C to simulate turning the radar board off")
    frame_no = 0
    start = time.time()
    try:
        while run_seconds <= 0 or time.time() - start < run_seconds:
            frame_no += 1
            payload = make_radar_frame_payload(frame_no)
            try:
                post_json(f"{base}/mock/radar-frame", payload, timeout=3)
                if send_udp:
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                        sock.sendto(make_radar_packet(frame_no), (udp_host, udp_port))
                print(
                    "[radar-board] frame={frame_number} status={status} "
                    "hr={heart_rate:.1f} br={breath_rate:.1f} dist={target_distance:.2f}m".format(**payload)
                )
            except NETWORK_ERRORS as exc:
                print(f"[radar-board] mock API temporarily unavailable, keep retrying: {exc}", file=sys.stderr)
            time.sleep(max(0.2, interval))
    except KeyboardInterrupt:
        print("\n[radar-board] stopped; mock API will mark radar board offline in a few seconds")


def heartbeat_payload(tick: int) -> dict[str, Any]:
    cycle = tick % 40
    detected = cycle in {8, 9, 10, 11, 24, 25, 26}
    score = 0.82 + 0.08 * math.sin(tick) if detected else 0.18 + 0.12 * math.sin(tick * 0.4)
    dbfs = -14.0 if detected else -34.0 + 2.0 * math.sin(tick * 0.2)
    return {
        "snore_score": round(clamp(score, 0.0, 1.0), 3),
        "snore_detected": detected,
        "dbfs": round(dbfs, 2),
        "source": "mock_snore_board",
    }


def run_snore_board(host: str, api_port: int, interval: float, audio_interval: float, run_seconds: float) -> None:
    base = f"http://{host}:{api_port}"
    print(f"[snore-board] online -> {base}/mock/snore-heartbeat")
    print(f"[snore-board] feature interval={interval:.1f}s, audio chunk interval={audio_interval:.1f}s")
    print("[snore-board] press Ctrl+C to simulate turning the snore board off")
    tick = 0
    start = time.time()
    last_audio = time.time()
    try:
        while run_seconds <= 0 or time.time() - start < run_seconds:
            tick += 1
            payload = heartbeat_payload(tick)
            try:
                post_json(f"{base}/mock/snore-heartbeat", payload, timeout=3)
                print(
                    "[snore-board] heartbeat score={snore_score:.2f} "
                    "snore={snore_detected} dbfs={dbfs:.1f}".format(**payload)
                )
                if audio_interval > 0 and time.time() - last_audio >= audio_interval:
                    send_audio(host, api_port, seconds=10.0)
                    last_audio = time.time()
            except NETWORK_ERRORS as exc:
                print(f"[snore-board] mock API temporarily unavailable, keep retrying: {exc}", file=sys.stderr)
            time.sleep(max(0.5, interval))
    except KeyboardInterrupt:
        print("\n[snore-board] stopped; mock API will mark snore board offline in a few seconds")


def demo(host: str, api_port: int, udp_host: str, udp_port: int) -> None:
    print("[demo] starting both mock boards for 30 seconds")
    radar_thread = threading.Thread(
        target=run_radar_board,
        args=(host, api_port, 1.0, 30.0, udp_host, udp_port, True),
        daemon=True,
    )
    snore_thread = threading.Thread(
        target=run_snore_board,
        args=(host, api_port, 1.0, 10.0, 30.0),
        daemon=True,
    )
    radar_thread.start()
    snore_thread.start()
    radar_thread.join()
    snore_thread.join()
    print("[demo] finished; both boards will appear offline after a few seconds")


def print_help_and_exit() -> None:
    parse_args(["--help"])
    sys.exit(1)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate radar UDP frames and snore-board HTTP audio uploads.")
    parser.add_argument("--host", default="127.0.0.1", help="Mock API host for HTTP calls.")
    parser.add_argument("--api-port", type=int, default=8081, help="Mock API HTTP port.")
    parser.add_argument("--udp-host", default="127.0.0.1", help="Radar UDP receiver host.")
    parser.add_argument("--udp-port", type=int, default=9988, help="Radar UDP receiver port.")
    parser.add_argument("--seconds", type=float, default=10.0, help="Duration for audio or UDP mode.")
    parser.add_argument("--run-seconds", type=float, default=0.0, help="Board mode duration. 0 means run forever.")
    parser.add_argument("--radar-interval", type=float, default=1.0, help="Seconds between radar board API updates.")
    parser.add_argument("--snore-interval", type=float, default=1.0, help="Seconds between snore board feature heartbeats.")
    parser.add_argument("--audio-interval", type=float, default=10.0, help="Seconds between snore-board 10-second audio chunk uploads. 0 disables periodic upload.")
    parser.add_argument("--send-udp", action="store_true", help="In radar-board mode, also send UDP packets to --udp-host/--udp-port.")
    parser.add_argument("--audio", action="store_true", help="Send one snore-like audio upload to /audio.")
    parser.add_argument("--radar-udp", action="store_true", help="Send radar UDP frames to the configured UDP receiver.")
    parser.add_argument("--radar-board", action="store_true", help="Run a continuous mock radar board until Ctrl+C.")
    parser.add_argument("--snore-board", action="store_true", help="Run a continuous mock snore board until Ctrl+C.")
    parser.add_argument("--demo", action="store_true", help="Run a short front-end visible demo.")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    if not args.audio and not args.radar_udp and not args.radar_board and not args.snore_board and not args.demo:
        print("No mode selected. Use --radar-board, --snore-board, --audio, --radar-udp, or --demo.\n")
        print_help_and_exit()

    if args.audio:
        send_audio(args.host, args.api_port, args.seconds)
    if args.radar_udp:
        send_radar_udp(args.udp_host, args.udp_port, args.seconds, RADAR_FRAME_RATE)
    if args.radar_board:
        run_radar_board(
            args.host,
            args.api_port,
            args.radar_interval,
            args.run_seconds,
            args.udp_host,
            args.udp_port,
            args.send_udp,
        )
    if args.snore_board:
        run_snore_board(args.host, args.api_port, args.snore_interval, args.audio_interval, args.run_seconds)
    if args.demo:
        demo(args.host, args.api_port, args.udp_host, args.udp_port)


if __name__ == "__main__":
    main()
