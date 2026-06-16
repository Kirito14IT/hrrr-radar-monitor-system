#!/usr/bin/env python3
"""Convert the DEEPCRAFT snore Keras model to a verified full-int8 TFLite header."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import tensorflow as tf


INPUT_SHAPE = (1, 60, 20)
CALIBRATION_MIN = -8.1
CALIBRATION_MAX = 2.0
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
    parser.add_argument("--seed", type=int, default=5172)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model = tf.keras.models.load_model(args.input, compile=False)
    model(np.zeros(INPUT_SHAPE, dtype=np.float32), training=False)

    calibration = make_feature_samples(args.calibration_samples, args.seed)
    tflite_model = convert_model(model, calibration)
    validation = make_feature_samples(args.validation_samples, args.seed + 1)
    report = validate_model(model, tflite_model, validation)
    report["source_model"] = str(args.input)
    report["source_sha256"] = hashlib.sha256(args.input.read_bytes()).hexdigest()
    report["runtime_acceleration"] = "CMSIS-NN/Helium on Cortex-M55"
    report["nnlite_status"] = "not applicable: NNLite is only available on Cortex-M33"

    if report["class_agreement"] < 0.98:
        raise RuntimeError(
            f"Class agreement is too low: {report['class_agreement']:.2%}"
        )

    args.tflite.parent.mkdir(parents=True, exist_ok=True)
    args.tflite.write_bytes(tflite_model)
    write_header(args.header, tflite_model, args.input, report)
    args.report.write_text(
        json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="ascii"
    )
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
