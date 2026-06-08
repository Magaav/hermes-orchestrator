#!/usr/bin/env python3
"""Validate a production-candidate Hermes wake ONNX model.

This script is intentionally stricter than the test-only fixture verifier. It
requires a real model candidate and real WAV validation fixtures, then checks
the Android raw-PCM ONNX contract and positive/negative confidence behavior.
"""

from __future__ import annotations

import argparse
import sys
import wave
from dataclasses import dataclass
from pathlib import Path


DEFAULT_MODEL = "native/android/app/src/main/assets/voice/hermes.onnx"
DEFAULT_VALIDATION = "data/voice/hermes/validation"
DEFAULT_THRESHOLD = 0.58
WINDOW_DEFAULT = 16_000
WINDOW_MIN = 4_000
WINDOW_MAX = 32_000


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


def fail(name: str, detail: str) -> Check:
    return Check(name, False, detail)


def ok(name: str, detail: str) -> Check:
    return Check(name, True, detail)


def load_wav(path: Path, window_samples: int) -> tuple["np.ndarray", str]:
    import numpy as np

    if not path.exists():
        raise FileNotFoundError(f"missing validation fixture: {path}")
    if path.stat().st_size == 0:
        raise ValueError(f"placeholder fixture is empty: {path}")
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_rate = wav.getframerate()
        sample_width = wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())
    if channels != 1 or sample_rate != 16_000 or sample_width != 2:
        raise ValueError(
            f"{path} must be mono 16 kHz PCM16 WAV; got channels={channels} "
            f"sample_rate={sample_rate} sample_width={sample_width}"
        )
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32767.0
    if samples.size == 0:
        raise ValueError(f"fixture contains no audio samples: {path}")
    if samples.size < window_samples:
        samples = np.pad(samples, (window_samples - samples.size, 0))
    elif samples.size > window_samples:
        samples = samples[-window_samples:]
    return samples.reshape(1, window_samples).astype(np.float32), f"{samples.size} samples"


def resolved_shape(shape: list[object]) -> list[int]:
    result: list[int] = []
    for dimension in shape:
        if isinstance(dimension, int):
            result.append(1 if dimension == 0 else dimension)
        else:
            result.append(WINDOW_DEFAULT)
    return result


def contract_check(session: "ort.InferenceSession") -> tuple[Check, str, int]:
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1:
        return fail("ONNX contract", f"expected exactly one input, got {len(inputs)}"), "", WINDOW_DEFAULT
    if len(outputs) < 1:
        return fail("ONNX contract", "expected at least one output"), inputs[0].name, WINDOW_DEFAULT
    input_meta = inputs[0]
    output_meta = outputs[0]
    if input_meta.type != "tensor(float)":
        return fail("ONNX contract", f"input must be tensor(float), got {input_meta.type}"), input_meta.name, WINDOW_DEFAULT
    shape = resolved_shape(list(input_meta.shape))
    if len(shape) == 1:
        shape = [1, shape[0]]
    concrete = [item for item in shape if item > 1]
    window = concrete[-1] if concrete else 0
    if len(shape) not in (1, 2, 3) or any(item != 1 for item in shape[:-1]) or not (WINDOW_MIN <= window <= WINDOW_MAX):
        return fail("ONNX contract", f"unsupported input shape {input_meta.shape} resolved to {shape}"), input_meta.name, WINDOW_DEFAULT
    output_shape = resolved_shape(list(output_meta.shape))
    if len(output_shape) > 3 or any(item > 2 for item in output_shape if item > 1):
        return fail("ONNX contract", f"unsupported output shape {output_meta.shape} resolved to {output_shape}"), input_meta.name, window
    return ok("ONNX contract", f"{input_meta.name} {shape} -> {output_meta.name} {output_shape}"), input_meta.name, window


def score(session: "ort.InferenceSession", input_name: str, samples: "np.ndarray") -> float:
    value = session.run(None, {input_name: samples})[0]
    return float(value.reshape(-1)[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Production candidate ONNX path. Default: %(default)s")
    parser.add_argument("--validation-dir", default=DEFAULT_VALIDATION, help="Validation fixture directory. Default: %(default)s")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="Wake confidence threshold. Default: %(default)s")
    args = parser.parse_args()

    checks: list[Check] = []
    model = Path(args.model)
    validation = Path(args.validation_dir)

    if not model.exists():
        checks.append(fail("model present", f"production candidate missing: {model}"))
    elif model.name != "hermes.onnx":
        checks.append(fail("model name", f"production candidate must be named hermes.onnx, got {model.name}"))
    elif b"NON_PRODUCTION" in model.read_bytes() or b"hermes-test-only" in model.read_bytes():
        checks.append(fail("model provenance", "candidate contains non-production fixture marker"))
    else:
        checks.append(ok("model present", str(model)))

    if checks[-1].passed:
        try:
            import numpy as np  # noqa: F401
            import onnxruntime as ort
        except ImportError as error:
            checks.append(fail("runtime available", f"install numpy and onnxruntime to validate candidates: {error}"))
        else:
            try:
                session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
                contract, input_name, window = contract_check(session)
                checks.append(contract)
                if contract.passed:
                    fixture_expectations = [
                        ("positive fixture", validation / "hermes-positive.wav", True),
                        ("negative silence", validation / "hermes-negative-silence.wav", False),
                        ("negative speech", validation / "hermes-negative-speech.wav", False),
                        ("negative noise", validation / "hermes-negative-noise.wav", False),
                    ]
                    for label, path, should_wake in fixture_expectations:
                        try:
                            samples, detail = load_wav(path, window)
                            confidence = score(session, input_name, samples)
                        except Exception as error:  # noqa: BLE001
                            checks.append(fail(label, str(error)))
                            continue
                        if should_wake and confidence >= args.threshold:
                            checks.append(ok(label, f"confidence={confidence:.6f} >= {args.threshold:.2f}; {detail}"))
                        elif not should_wake and confidence < args.threshold:
                            checks.append(ok(label, f"confidence={confidence:.6f} < {args.threshold:.2f}; {detail}"))
                        else:
                            comparator = ">=" if should_wake else "<"
                            checks.append(fail(label, f"confidence={confidence:.6f} must be {comparator} {args.threshold:.2f}; {detail}"))
            except Exception as error:  # noqa: BLE001
                checks.append(fail("ONNX load", str(error)))

    print("Hermes wake production-candidate validation")
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"[{status}] {check.name}: {check.detail}")

    if all(check.passed for check in checks):
        print("RESULT: PASS - candidate may be packaged as a production Hermes wake model.")
        return 0
    print("RESULT: FAIL - real wake-on-Hermes remains blocked.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
