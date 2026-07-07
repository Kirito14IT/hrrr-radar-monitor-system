#!/usr/bin/env python3
"""Convert the DEEPCRAFT snore Keras model to a verified full-int8 TFLite header."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import wave
from pathlib import Path
from typing import Iterable

import numpy as np
from scipy import signal
import tensorflow as tf


INPUT_SHAPE = (1, 60, 20)
CALIBRATION_MIN = -8.1
CALIBRATION_MAX = 2.0
SAMPLE_RATE = 16000
INPUT_SAMPLES = 32000
FFT_SIZE = 512
HOP_SIZE = 160
NUM_FRAMES = 60
MEL_BINS = 20
FEATURE_WINDOW_SAMPLES = FFT_SIZE + (NUM_FRAMES - 1) * HOP_SIZE
MEL_CLIP_MIN = 0.000316227766016
MEL_FILTER_POINTS = np.array(
    [9, 13, 16, 21, 25, 31, 37, 43, 50, 58, 67, 77, 87, 99, 113, 127, 144, 162, 182, 204, 229, 256],
    dtype=np.int32,
)
EXPECTED_OPS = {
    "SHAPE",
    "STRIDED_SLICE",
    "PACK",
    "RESHAPE",
    "CONV_2D",
    "MAX_POOL_2D",
    "MEAN",
    "FULLY_CONNECTED",
    "SOFTMAX",
}


def build_mel_weights() -> np.ndarray:
    weights = np.zeros((MEL_BINS, FFT_SIZE // 2 + 1), dtype=np.float32)
    for m in range(MEL_BINS):
        n0, n1, n2 = MEL_FILTER_POINTS[m : m + 3]
        for k in range(n0, min(n1, weights.shape[1])):
            if n1 > n0:
                weights[m, k] = (k - n0) / float(n1 - n0)
        for k in range(n1, min(n2, weights.shape[1])):
            if n2 > n1:
                weights[m, k] = 1.0 - ((k - n1) / float(n2 - n1))
    return weights


MEL_WEIGHTS = build_mel_weights()
HANN = signal.windows.hann(FFT_SIZE, sym=True).astype(np.float32)


def make_feature_samples(count: int, seed: int) -> np.ndarray:
    """Create deterministic log-mel calibration data covering expected firmware input."""
    rng = np.random.default_rng(seed)
    samples = np.empty((count, *INPUT_SHAPE[1:]), dtype=np.float32)
    times = np.linspace(0.0, 1.0, INPUT_SHAPE[1], dtype=np.float32)[:, None]
    freqs = np.linspace(0.0, 1.0, INPUT_SHAPE[2], dtype=np.float32)[None, :]

    for index in range(count):
        feature = rng.normal(-3.2, 1.45, INPUT_SHAPE[1:]).astype(np.float32)

        # Add broad temporal and spectral structures instead of calibrating with
        # independent noise alone. These resemble sustained and pulsed sound bands.
        feature += rng.uniform(-0.8, 0.8) * np.sin(
            (1 + index % 6) * np.pi * times + rng.uniform(0.0, np.pi)
        )
        feature += rng.uniform(-0.7, 0.7) * np.cos(
            (1 + index % 5) * np.pi * freqs + rng.uniform(0.0, np.pi)
        )
        if index % 3 == 0:
            center = rng.integers(2, INPUT_SHAPE[2] - 2)
            feature[:, center - 1 : center + 2] += rng.uniform(1.0, 2.8)
        if index % 5 == 0:
            start = rng.integers(0, INPUT_SHAPE[1] - 12)
            feature[start : start + 12, :] += rng.uniform(0.8, 2.2)

        samples[index] = np.clip(feature, CALIBRATION_MIN, CALIBRATION_MAX)

    # Force exact endpoints so the int8 input range remains stable and reproducible.
    samples[0].fill(CALIBRATION_MIN)
    samples[0, -1, -1] = CALIBRATION_MAX
    samples[1] = np.linspace(
        CALIBRATION_MIN,
        CALIBRATION_MAX,
        INPUT_SHAPE[1] * INPUT_SHAPE[2],
        dtype=np.float32,
    ).reshape(INPUT_SHAPE[1:])
    return samples


def read_wav_mono(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    if sample_width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 1:
        data = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
        data = (data - 128.0) / 128.0
    elif sample_width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise RuntimeError(f"Unsupported wav sample width {sample_width}: {path}")

    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)

    if sr != SAMPLE_RATE:
        gcd = math.gcd(sr, SAMPLE_RATE)
        data = signal.resample_poly(data, SAMPLE_RATE // gcd, sr // gcd).astype(np.float32)

    return np.clip(data, -1.0, 0.9999695).astype(np.float32)


def extract_board_features(buffer_2s: np.ndarray) -> np.ndarray:
    if len(buffer_2s) != INPUT_SAMPLES:
        raise ValueError(f"Expected {INPUT_SAMPLES} samples, got {len(buffer_2s)}")
    feature_start = INPUT_SAMPLES - FEATURE_WINDOW_SAMPLES
    feats = np.zeros((NUM_FRAMES, MEL_BINS), dtype=np.float32)
    for frame in range(NUM_FRAMES):
        offset = feature_start + frame * HOP_SIZE
        frame_samples = buffer_2s[offset : offset + FFT_SIZE] * HANN
        magnitude = np.abs(np.fft.rfft(frame_samples, n=FFT_SIZE)).astype(np.float32)
        mel = MEL_WEIGHTS @ magnitude
        feats[frame] = np.log(np.maximum(mel, MEL_CLIP_MIN))
    return feats


def iter_calibration_windows(audio: np.ndarray, hop_samples: int) -> Iterable[np.ndarray]:
    if len(audio) <= INPUT_SAMPLES:
        padded = np.zeros(INPUT_SAMPLES, dtype=np.float32)
        padded[-len(audio) :] = audio
        yield padded
        return

    for start in range(0, len(audio) - INPUT_SAMPLES + 1, hop_samples):
        yield audio[start : start + INPUT_SAMPLES]

    if (len(audio) - INPUT_SAMPLES) % hop_samples != 0:
        yield audio[-INPUT_SAMPLES:]


def make_wav_feature_samples(
    data_dir: Path, count: int, seed: int, hop_seconds: float
) -> tuple[np.ndarray, dict[str, object]]:
    wav_paths = sorted(data_dir.rglob("*.wav"))
    if not wav_paths:
        raise RuntimeError(f"No wav files found under {data_dir}")

    rng = np.random.default_rng(seed)
    hop_samples = max(1, int(round(hop_seconds * SAMPLE_RATE)))
    candidates: list[tuple[str, np.ndarray]] = []

    for wav_path in wav_paths:
        audio = read_wav_mono(wav_path)
        for window in iter_calibration_windows(audio, hop_samples):
            candidates.append((str(wav_path), extract_board_features(window)))

    if not candidates:
        raise RuntimeError(f"No calibration windows extracted from {data_dir}")

    take = min(count, len(candidates))
    indices = rng.choice(len(candidates), size=take, replace=False)
    samples = np.stack([candidates[int(index)][1] for index in indices]).astype(np.float32)
    selected_files = sorted({candidates[int(index)][0] for index in indices})
    return samples, {
        "mode": "wav",
        "data_dir": str(data_dir),
        "wav_files_total": len(wav_paths),
        "candidate_windows": len(candidates),
        "selected_windows": int(take),
        "selected_files": len(selected_files),
        "window_hop_seconds": hop_seconds,
        "feature_min": float(np.min(samples)),
        "feature_max": float(np.max(samples)),
        "feature_mean": float(np.mean(samples)),
        "feature_std": float(np.std(samples)),
    }


def representative_dataset(samples: np.ndarray) -> Iterable[list[np.ndarray]]:
    for sample in samples:
        yield [sample[None, ...]]


def convert_model(model: tf.keras.Model, calibration: np.ndarray) -> bytes:
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = lambda: representative_dataset(calibration)
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    return converter.convert()


def quantize(values: np.ndarray, scale: float, zero_point: int) -> np.ndarray:
    return np.clip(np.rint(values / scale) + zero_point, -128, 127).astype(np.int8)


def validate_model(
    keras_model: tf.keras.Model, tflite_model: bytes, samples: np.ndarray
) -> dict[str, object]:
    interpreter = tf.lite.Interpreter(model_content=tflite_model)
    interpreter.allocate_tensors()
    input_info = interpreter.get_input_details()[0]
    output_info = interpreter.get_output_details()[0]

    if input_info["dtype"] != np.int8 or output_info["dtype"] != np.int8:
        raise RuntimeError("Converted model is not full int8")
    if tuple(input_info["shape"]) != INPUT_SHAPE:
        raise RuntimeError(f"Unexpected input shape: {input_info['shape']}")
    if tuple(output_info["shape"]) != (1, 2):
        raise RuntimeError(f"Unexpected output shape: {output_info['shape']}")

    ops = [
        op["op_name"]
        for op in interpreter._get_ops_details()  # pylint: disable=protected-access
        if op["op_name"] != "DELEGATE"
    ]
    unsupported = set(ops) - EXPECTED_OPS
    if unsupported:
        raise RuntimeError(f"Unexpected TFLite operators: {sorted(unsupported)}")

    input_scale, input_zero_point = input_info["quantization"]
    output_scale, output_zero_point = output_info["quantization"]
    float_outputs = keras_model(samples, training=False).numpy()
    int8_outputs = np.empty_like(float_outputs)

    for index, sample in enumerate(samples):
        interpreter.set_tensor(
            input_info["index"],
            quantize(sample[None, ...], input_scale, input_zero_point),
        )
        interpreter.invoke()
        quantized_output = interpreter.get_tensor(output_info["index"])
        int8_outputs[index] = (
            quantized_output.astype(np.float32) - output_zero_point
        ) * output_scale

    absolute_error = np.abs(float_outputs - int8_outputs)
    class_agreement = np.mean(
        np.argmax(float_outputs, axis=1) == np.argmax(int8_outputs, axis=1)
    )
    return {
        "model_bytes": len(tflite_model),
        "input_shape": input_info["shape"].tolist(),
        "input_scale": float(input_scale),
        "input_zero_point": int(input_zero_point),
        "output_shape": output_info["shape"].tolist(),
        "output_scale": float(output_scale),
        "output_zero_point": int(output_zero_point),
        "operators": ops,
        "mean_absolute_error": float(np.mean(absolute_error)),
        "max_absolute_error": float(np.max(absolute_error)),
        "class_agreement": float(class_agreement),
    }


def write_header(path: Path, model_data: bytes, source_model: Path, report: dict) -> None:
    digest = hashlib.sha256(source_model.read_bytes()).hexdigest()
    rows = []
    for offset in range(0, len(model_data), 12):
        chunk = model_data[offset : offset + 12]
        rows.append("    " + ", ".join(f"0x{value:02x}" for value in chunk) + ",")

    text = f"""#pragma once
#include <cstddef>

/* Model labels */
#define snore_MODEL_LABEL_UNLABELLED  0
#define snore_MODEL_LABEL_snore       1
#define snore_MODEL_NUM_CLASSES        2

/* Model input/preprocessing parameters matched to models/model.py. */
#define snore_MODEL_INPUT_FRAMES       60
#define snore_MODEL_INPUT_FREQ_BINS    20
#define snore_MODEL_INPUT_CHANNELS     1
#define snore_MODEL_SAMPLE_RATE        16000
#define snore_MODEL_FFT_SIZE           512
#define snore_MODEL_FFT_HOP            160
#define snore_MODEL_MEL_BINS           20

#if defined __GNUC__
#define ALIGN(X) __attribute__((aligned(X)))
#elif defined _MSC_VER
#define ALIGN(X) __declspec(align(X))
#else
#define ALIGN(X)
#endif

/*
 * Full-int8 TFLite model converted from models/{source_model.name}.
 * Source SHA-256: {digest}
 * Input: int8 [1,60,20], scale={report['input_scale']:.10g}, zero_point={report['input_zero_point']}.
 * Output: int8 [1,2], scale={report['output_scale']:.10g}, zero_point={report['output_zero_point']}.
 * Class 0 is unlabelled; class 1 is snore.
 * Calibration range: [{CALIBRATION_MIN}, {CALIBRATION_MAX}] log-mel features.
 * Runtime acceleration: CMSIS-NN/Helium on Cortex-M55.
 * NNLite is a Cortex-M33-only backend on PSOC Edge E84.
 */

ALIGN(16) static const unsigned char snore_model_tflite[] = {{
{chr(10).join(rows)}
}};

static const size_t snore_model_tflite_len = {len(model_data)};
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="ascii", newline="\n")


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    default_header = (
        repo_root
        / "Edgi_Talk_M55_XiaoZhi"
        / "edge-impulse"
        / "tflite-model"
        / "snore_model_data.h"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=repo_root / "models" / "conv2d-medium-balanced-0.h5",
    )
    parser.add_argument(
        "--tflite",
        type=Path,
        default=repo_root / "models" / "conv2d-medium-balanced-0-int8.tflite",
    )
    parser.add_argument("--header", type=Path, default=default_header)
    parser.add_argument(
        "--report",
        type=Path,
        default=repo_root / "models" / "conv2d-medium-balanced-0-int8.json",
    )
    parser.add_argument("--calibration-samples", type=int, default=256)
    parser.add_argument("--validation-samples", type=int, default=256)
    parser.add_argument(
        "--calibration-data",
        type=Path,
        default=None,
        help="Optional wav dataset directory used as the TFLite representative dataset.",
    )
    parser.add_argument(
        "--calibration-hop-seconds",
        type=float,
        default=1.0,
        help="Sliding-window hop for extracting real wav calibration features.",
    )
    parser.add_argument(
        "--no-header",
        action="store_true",
        help="Write only the .tflite and report; do not overwrite the board header.",
    )
    parser.add_argument("--seed", type=int, default=5172)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model = tf.keras.models.load_model(args.input, compile=False)
    model(np.zeros(INPUT_SHAPE, dtype=np.float32), training=False)

    if args.calibration_data:
        calibration, calibration_meta = make_wav_feature_samples(
            args.calibration_data,
            args.calibration_samples,
            args.seed,
            args.calibration_hop_seconds,
        )
    else:
        calibration = make_feature_samples(args.calibration_samples, args.seed)
        calibration_meta = {
            "mode": "synthetic",
            "samples": int(args.calibration_samples),
            "feature_min": float(np.min(calibration)),
            "feature_max": float(np.max(calibration)),
            "feature_mean": float(np.mean(calibration)),
            "feature_std": float(np.std(calibration)),
        }
    tflite_model = convert_model(model, calibration)
    if args.calibration_data:
        validation, validation_meta = make_wav_feature_samples(
            args.calibration_data,
            args.validation_samples,
            args.seed + 1,
            args.calibration_hop_seconds,
        )
    else:
        validation = make_feature_samples(args.validation_samples, args.seed + 1)
        validation_meta = {
            "mode": "synthetic",
            "samples": int(args.validation_samples),
            "feature_min": float(np.min(validation)),
            "feature_max": float(np.max(validation)),
            "feature_mean": float(np.mean(validation)),
            "feature_std": float(np.std(validation)),
        }
    report = validate_model(model, tflite_model, validation)
    report["source_model"] = str(args.input)
    report["source_sha256"] = hashlib.sha256(args.input.read_bytes()).hexdigest()
    report["calibration"] = calibration_meta
    report["validation"] = validation_meta
    report["runtime_acceleration"] = "CMSIS-NN/Helium on Cortex-M55"
    report["nnlite_status"] = "not applicable: NNLite is only available on Cortex-M33"

    if report["class_agreement"] < 0.98:
        raise RuntimeError(
            f"Class agreement is too low: {report['class_agreement']:.2%}"
        )

    args.tflite.parent.mkdir(parents=True, exist_ok=True)
    args.tflite.write_bytes(tflite_model)
    if not args.no_header:
        write_header(args.header, tflite_model, args.input, report)
    args.report.write_text(
        json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="ascii"
    )
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
