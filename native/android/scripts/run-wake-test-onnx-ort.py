#!/usr/bin/env python3
"""Load and evaluate the non-production wake fixture with ONNX Runtime.

This is a mechanics proof for the generated ONNX contract. It does not prove
real Hermes wake-word accuracy.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path


DEFAULT_MODEL = "native/android/build/generated/voice/hermes-test-only.onnx"
THRESHOLD = 0.58


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Generated test ONNX path. Default: %(default)s")
    args = parser.parse_args()

    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError as error:
        raise SystemExit(
            "Missing optional proof dependency. Install onnxruntime and numpy in a venv, "
            f"then re-run this script. Import error: {error}"
        )

    model = Path(args.model)
    session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    inputs = [(item.name, item.shape, item.type) for item in session.get_inputs()]
    outputs = [(item.name, item.shape, item.type) for item in session.get_outputs()]
    if inputs != [("waveform", [1, 16_000], "tensor(float)")]:
        raise AssertionError(f"unexpected inputs: {inputs}")
    if outputs != [("confidence", [1, 1], "tensor(float)")]:
        raise AssertionError(f"unexpected outputs: {outputs}")

    fixtures = {
        "positive": np.array([[0.95 * math.sin(index * 0.05) for index in range(16_000)]], dtype=np.float32),
        "negative_silence": np.zeros((1, 16_000), dtype=np.float32),
        "negative_speech_like": np.array([[0.12 * math.sin(index * 0.13) for index in range(16_000)]], dtype=np.float32),
    }
    results: dict[str, float] = {}
    for name, samples in fixtures.items():
        value = session.run(None, {"waveform": samples})[0]
        results[name] = float(value.reshape(-1)[0])

    if results["positive"] < THRESHOLD:
        raise AssertionError(f"positive confidence {results['positive']:.3f} below {THRESHOLD}")
    for name in ("negative_silence", "negative_speech_like"):
        if results[name] >= THRESHOLD:
            raise AssertionError(f"{name} confidence {results[name]:.3f} above {THRESHOLD}")

    print(f"ONNX Runtime loaded test fixture: {model}")
    print(f"inputs={inputs}")
    print(f"outputs={outputs}")
    for name, value in results.items():
        print(f"{name}_confidence={value:.6f}")
    print("This proves compatible ONNX mechanics only; it is not real Hermes wake detection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
