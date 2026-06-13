#!/usr/bin/env python3
"""Validate a Hermes base wake ONNX against the Android raw-PCM contract."""

from __future__ import annotations

import argparse
from pathlib import Path

from hermes_wake_lib import WINDOW_SAMPLES, load_audio


def compatible_input_shape(shape: list[object]) -> tuple[bool, tuple[int, ...]]:
    resolved: list[int] = []
    for index, dim in enumerate(shape):
        if isinstance(dim, int) and dim > 0:
            resolved.append(dim)
        else:
            resolved.append(1 if index < len(shape) - 1 else WINDOW_SAMPLES)
    return tuple(resolved) in ((1, WINDOW_SAMPLES), (1, 1, WINDOW_SAMPLES)), tuple(resolved)


def fixture_paths(dataset: Path | None) -> list[tuple[str, Path]]:
    if dataset is None:
        return []
    result: list[tuple[str, Path]] = []
    positive = next(iter(sorted((dataset / "positive").glob("*.wav"))), None)
    negative = next(iter(sorted((dataset / "negative").glob("**/*.wav"))), None)
    if positive:
        result.append(("positive", positive))
    if negative:
        result.append(("negative", negative))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model")
    parser.add_argument("--dataset", default=None)
    args = parser.parse_args()
    model = Path(args.model)

    if not model.exists():
        raise SystemExit(f"ONNX model not found: {model}")
    if model.stat().st_size == 0:
        raise SystemExit(f"ONNX model is zero-byte: {model}")

    try:
        import numpy as np
        import onnx
        import onnxruntime as ort
    except ImportError as error:
        raise SystemExit(f"Missing ONNX check dependencies. Install numpy, onnx, and onnxruntime. Details: {error}") from error

    onnx_model = onnx.load(str(model))
    onnx.checker.check_model(onnx_model)
    session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1:
        raise SystemExit(f"Expected exactly one input, got {len(inputs)}")
    if not outputs:
        raise SystemExit("Expected at least one output")
    input_meta = inputs[0]
    output_meta = outputs[0]
    if input_meta.type != "tensor(float)":
        raise SystemExit(f"Input must be float32 tensor, got {input_meta.type}")
    shape_ok, resolved_shape = compatible_input_shape(list(input_meta.shape))
    if not shape_ok:
        raise SystemExit(f"Input shape must be [1,16000] or [1,1,16000], got {input_meta.shape}")

    def run(label: str, samples: "np.ndarray") -> float:
        if resolved_shape == (1, 1, WINDOW_SAMPLES):
            feed = samples.reshape(1, 1, WINDOW_SAMPLES).astype(np.float32)
        else:
            feed = samples.reshape(1, WINDOW_SAMPLES).astype(np.float32)
        output = session.run(None, {input_meta.name: feed})[0]
        flat = np.asarray(output).reshape(-1)
        if flat.size < 1 or flat.size > 4:
            raise SystemExit(f"Output must be scalar/small confidence tensor, got shape {np.asarray(output).shape}")
        confidence = float(flat[0])
        print(f"{label} confidence: {confidence:.6f}")
        return confidence

    zeros = np.zeros(WINDOW_SAMPLES, dtype=np.float32)
    rng = np.random.default_rng(123)
    noise = rng.normal(0.0, 0.02, WINDOW_SAMPLES).astype(np.float32)
    run("zeros/silence", zeros)
    run("random noise", noise)
    dataset = Path(args.dataset) if args.dataset else None
    for label, path in fixture_paths(dataset):
        run(f"{label} fixture {path}", load_audio(path, WINDOW_SAMPLES))

    print(
        f"ONNX contract PASS: {model} input={input_meta.name}{resolved_shape} "
        f"output={output_meta.name}{output_meta.shape}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
