from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


APNEA_MIN_SECONDS = 10.0
APNEA_LOOKAROUND_SECONDS = 20.0
APNEA_LOW_BREATH_RPM = 8.0
APNEA_SNORE_EVIDENCE_LEVEL = 0.45
APNEA_STRONG_SNORE_LEVEL = 0.62
APNEA_RECOVERY_RPM_DELTA = 4.0
APNEA_MAX_ROW_GAP_SECONDS = 4.5
APNEA_MIN_RUN_ROWS = 4
APNEA_MIN_RADAR_VALID_RATIO = 0.65
APNEA_LOW_OR_MISSING_RATIO = 0.72
APNEA_NORMAL_BREATH_RPM = 10.0
BREATH_ABNORMAL_LOW_RPM = 10.0
BREATH_ABNORMAL_HIGH_RPM = 24.0
BREATH_ABNORMAL_MIN_ROWS = 5
BREATH_ABNORMAL_RATIO = 0.60


def _parse_ts(value: Any) -> Optional[float]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float))


def _avg(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _median(values: list[float]) -> Optional[float]:
    if not values:
        return None
    sorted_values = sorted(values)
    mid = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2.0


def _event_id_for(start_ts: float) -> int:
    return int(start_ts * 1000)


def _fingerprint(start_ts: float) -> str:
    bucket = int(start_ts // 30)
    return f"suspected_apnea:{bucket}"


def _snore_level(row: dict[str, Any]) -> Optional[float]:
    level = row.get("snore_level")
    if _is_number(level):
        return max(0.0, min(1.0, float(level)))
    score = row.get("snore_score")
    if _is_number(score):
        return max(0.0, min(1.0, float(score)))
    return None


def _window_rows(rows: list[tuple[float, dict[str, Any]]], start_ts: float, end_ts: float) -> list[dict[str, Any]]:
    return [row for ts, row in rows if start_ts <= ts <= end_ts]


def _target_present(row: dict[str, Any]) -> bool:
    distance = float(row.get("target_distance") or 0.0)
    return bool(row.get("radar_online")) and 0.15 <= distance <= 3.0


def _radar_usable(row: dict[str, Any]) -> bool:
    return row.get("radar_board_stationary", True) is not False and _target_present(row)


def _breath_values(rows: list[dict[str, Any]]) -> list[float]:
    return [
        float(row["breath_rate"])
        for row in rows
        if _is_number(row.get("breath_rate")) and 0.0 <= float(row["breath_rate"]) <= 40.0
    ]


def breath_window_abnormal(rows: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Return a short-window abnormal breath summary, or None for isolated noisy points."""
    usable_rows = [row for row in rows if _radar_usable(row)]
    values = _breath_values(usable_rows)
    if len(values) < BREATH_ABNORMAL_MIN_ROWS:
        return None
    abnormal = [
        value for value in values
        if value < BREATH_ABNORMAL_LOW_RPM or value >= BREATH_ABNORMAL_HIGH_RPM
    ]
    if len(abnormal) / len(values) < BREATH_ABNORMAL_RATIO:
        return None
    median_value = _median(values)
    if median_value is None:
        return None
    if BREATH_ABNORMAL_LOW_RPM <= median_value < BREATH_ABNORMAL_HIGH_RPM:
        return None
    return {
        "median_breath_rate": round(median_value, 2),
        "min_breath_rate": round(min(values), 2),
        "max_breath_rate": round(max(values), 2),
        "sample_count": len(values),
        "abnormal_ratio": round(len(abnormal) / len(values), 2),
    }


def _snore_values(rows: list[dict[str, Any]]) -> list[float]:
    return [
        level
        for row in rows
        for level in [_snore_level(row)]
        if level is not None
    ]


def _build_event(
    run: list[tuple[float, dict[str, Any]]],
    parsed_rows: list[tuple[float, dict[str, Any]]],
) -> Optional[dict[str, Any]]:
    start_ts = run[0][0]
    end_ts = run[-1][0]
    if len(run) >= 2:
        step = max(1.0, min(3.0, (end_ts - start_ts) / max(1, len(run) - 1)))
    else:
        step = 1.0
    duration = (end_ts - start_ts) + step
    if duration < APNEA_MIN_SECONDS:
        return None

    during_rows = [row for _, row in run]
    if len(during_rows) < APNEA_MIN_RUN_ROWS:
        return None

    usable_count = sum(1 for row in during_rows if _radar_usable(row))
    if usable_count / max(1, len(during_rows)) < APNEA_MIN_RADAR_VALID_RATIO:
        return None

    low_or_missing = 0
    for row in during_rows:
        breath = row.get("breath_rate")
        if breath is None or (_is_number(breath) and float(breath) < APNEA_LOW_BREATH_RPM):
            low_or_missing += 1
    if low_or_missing / max(1, len(during_rows)) < APNEA_LOW_OR_MISSING_RATIO:
        return None

    around_rows = _window_rows(
        parsed_rows,
        start_ts - APNEA_LOOKAROUND_SECONDS,
        end_ts + APNEA_LOOKAROUND_SECONDS,
    )
    before_rows = _window_rows(parsed_rows, start_ts - APNEA_LOOKAROUND_SECONDS, start_ts - 0.001)
    after_rows = _window_rows(parsed_rows, end_ts + 0.001, end_ts + APNEA_LOOKAROUND_SECONDS)

    breath_values = _breath_values(during_rows)
    min_breath = min(breath_values) if breath_values else None
    median_breath = _median(breath_values)

    snore_levels = _snore_values(around_rows)
    max_snore = max(snore_levels) if snore_levels else 0.0
    snore_detected = any(bool(row.get("snore_detected")) for row in around_rows)
    max_dbfs = max(
        (float(row["snore_dbfs"]) for row in around_rows if _is_number(row.get("snore_dbfs"))),
        default=None,
    )

    before_snore = [_snore_level(row) or 0.0 for row in before_rows]
    after_snore = [_snore_level(row) or 0.0 for row in after_rows]
    sound_rebound = bool(after_snore and (max(after_snore) - (max(before_snore) if before_snore else 0.0)) >= 0.12)
    audio_evidence = snore_detected or max_snore >= APNEA_SNORE_EVIDENCE_LEVEL or sound_rebound
    if not audio_evidence:
        return None

    before_breath = _breath_values(before_rows)
    after_breath = _breath_values(after_rows)
    baseline_breath = _median(before_breath)
    after_median_breath = _median(after_breath)
    recovery = bool(after_breath and min_breath is not None and max(after_breath) - min_breath >= APNEA_RECOVERY_RPM_DELTA)
    baseline_or_recovery = (
        (baseline_breath is not None and baseline_breath >= APNEA_NORMAL_BREATH_RPM)
        or (after_median_breath is not None and after_median_breath >= APNEA_NORMAL_BREATH_RPM)
        or recovery
    )
    if not baseline_or_recovery:
        return None

    before_heart = [
        float(row["heart_rate"])
        for row in before_rows
        if _is_number(row.get("heart_rate"))
    ]
    after_heart = [
        float(row["heart_rate"])
        for row in after_rows
        if _is_number(row.get("heart_rate"))
    ]
    heart_delta = None
    if before_heart and after_heart:
        heart_delta = (_avg(after_heart) or 0.0) - (_avg(before_heart) or 0.0)

    confidence = 0.55
    reasons = ["radar_breath_pause"]
    if duration >= 15:
        confidence += 0.12
        reasons.append("long_pause")
    if max_snore >= APNEA_SNORE_EVIDENCE_LEVEL or snore_detected:
        confidence += 0.16
        reasons.append("snore_evidence")
    if max_snore >= APNEA_STRONG_SNORE_LEVEL:
        confidence += 0.08
        reasons.append("strong_snore")
    if sound_rebound:
        confidence += 0.08
        reasons.append("sound_rebound")
    if recovery:
        confidence += 0.08
        reasons.append("breath_recovery")
    if median_breath is None:
        confidence += 0.04
        reasons.append("breath_signal_lost")
    elif median_breath < APNEA_LOW_BREATH_RPM:
        confidence += 0.04
        reasons.append("low_median_breath")
    if baseline_breath is not None and baseline_breath >= APNEA_NORMAL_BREATH_RPM:
        confidence += 0.04
        reasons.append("normal_before_window")
    if heart_delta is not None and heart_delta >= 5.0:
        confidence += 0.05
        reasons.append("heart_rate_rise")
    confidence = min(0.98, confidence)
    if confidence < 0.68:
        return None

    severity = "critical" if confidence >= 0.82 or (duration >= 20 and max_snore >= APNEA_STRONG_SNORE_LEVEL) else "warning"
    start_text = datetime.fromtimestamp(start_ts).isoformat(timespec="seconds")
    end_text = datetime.fromtimestamp(end_ts).isoformat(timespec="seconds")
    message = f"雷达检测到呼吸减弱约 {duration:.0f} 秒，伴随呼噜声变化。"
    return {
        "eventID": _event_id_for(start_ts),
        "userID": None,
        "type": "suspected_apnea",
        "severity": severity,
        "title": "疑似呼吸暂停",
        "message": message,
        "timestamp": end_text,
        "source": "radar_snore_fusion",
        "score_delta": -22 if severity == "critical" else -14,
        "details": {
            "start_at": start_text,
            "end_at": end_text,
            "duration_seconds": round(duration, 1),
            "min_breath_rate": round(min_breath, 2) if min_breath is not None else None,
            "median_breath_rate": round(median_breath, 2) if median_breath is not None else None,
            "baseline_breath_rate": round(baseline_breath, 2) if baseline_breath is not None else None,
            "max_snore_level": round(max_snore, 3),
            "max_snore_dbfs": round(max_dbfs, 2) if max_dbfs is not None else None,
            "heart_delta": round(heart_delta, 2) if heart_delta is not None else None,
            "confidence": round(confidence, 2),
            "reasons": reasons,
        },
        "fingerprint": _fingerprint(start_ts),
        "status": "active",
    }


def detect_suspected_apnea_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parsed_rows: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        ts = _parse_ts(row.get("timestamp"))
        if ts is not None:
            parsed_rows.append((ts, row))
    parsed_rows.sort(key=lambda item: item[0])
    if len(parsed_rows) < 2:
        return []

    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    run: list[tuple[float, dict[str, Any]]] = []

    def flush_run() -> None:
        nonlocal run
        if run:
            event = _build_event(run, parsed_rows)
            if event and event["fingerprint"] not in seen:
                seen.add(event["fingerprint"])
                events.append(event)
            run = []

    for ts, row in parsed_rows:
        if run and ts - run[-1][0] > APNEA_MAX_ROW_GAP_SECONDS:
            flush_run()
        radar_usable = _radar_usable(row)
        breath_rate = row.get("breath_rate")
        weak_breath = breath_rate is None or (_is_number(breath_rate) and float(breath_rate) < APNEA_LOW_BREATH_RPM)
        if radar_usable and weak_breath:
            run.append((ts, row))
        else:
            flush_run()
    flush_run()
    return events
