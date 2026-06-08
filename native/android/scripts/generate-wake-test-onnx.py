#!/usr/bin/env python3
"""Generate a non-production Android Hermes wake ONNX fixture.

The model proves Android ONNX loader/package/evaluation mechanics only. It is
not trained on the Hermes wake word and must not be treated as production wake
detection.
"""

from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_OUTPUT = "native/android/build/generated/voice/hermes-test-only.onnx"
WINDOW_SAMPLES = 16_000


def varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break
    return bytes(out)


def key(field: int, wire_type: int) -> bytes:
    return varint((field << 3) | wire_type)


def int_field(field: int, value: int) -> bytes:
    return key(field, 0) + varint(value)


def string_field(field: int, value: str) -> bytes:
    encoded = value.encode("utf-8")
    return key(field, 2) + varint(len(encoded)) + encoded


def message_field(field: int, payload: bytes) -> bytes:
    return key(field, 2) + varint(len(payload)) + payload


def tensor_shape(dimensions: list[int]) -> bytes:
    payload = b""
    for dimension in dimensions:
        payload += message_field(1, int_field(1, dimension))
    return payload


def tensor_type(dimensions: list[int]) -> bytes:
    # TensorProto.FLOAT == 1.
    return int_field(1, 1) + message_field(2, tensor_shape(dimensions))


def value_info(name: str, dimensions: list[int]) -> bytes:
    # TypeProto.tensor_type is field 1.
    return string_field(1, name) + message_field(2, message_field(1, tensor_type(dimensions)))


def node(op_type: str, inputs: list[str], outputs: list[str], name: str) -> bytes:
    payload = b"".join(string_field(1, item) for item in inputs)
    payload += b"".join(string_field(2, item) for item in outputs)
    payload += string_field(3, name)
    payload += string_field(4, op_type)
    return payload


def graph() -> bytes:
    payload = b""
    payload += message_field(1, node("Abs", ["waveform"], ["abs_waveform"], "abs_waveform"))
    payload += message_field(1, node("ReduceMean", ["abs_waveform"], ["confidence"], "mean_abs_confidence"))
    payload += string_field(2, "hermes_test_only_amplitude_fixture")
    payload += message_field(11, value_info("waveform", [1, WINDOW_SAMPLES]))
    payload += message_field(12, value_info("confidence", [1, 1]))
    return payload


def model() -> bytes:
    payload = b""
    payload += int_field(1, 8)  # ir_version
    payload += string_field(2, "wasm-agent-non-production-test-fixture")
    payload += message_field(7, graph())
    payload += message_field(8, int_field(2, 13))  # default-domain opset_import.version
    payload += string_field(10, "NON_PRODUCTION: amplitude fixture, not Hermes-trained")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output .onnx path. Default: %(default)s")
    args = parser.parse_args()

    output = Path(args.output)
    if output.name == "hermes.onnx":
        raise SystemExit("Refusing to generate directly as production hermes.onnx; use install-wake-model.sh explicitly.")
    if not output.name.endswith(".onnx"):
        raise SystemExit("Output must end in .onnx")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(model())
    print(f"Generated non-production wake model fixture: {output}")
    print("Model: input waveform float32 [1,16000] -> confidence float32 [1,1] via mean(abs(waveform)).")
    print("This proves ONNX mechanics only; it is not a Hermes-trained wake model.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
