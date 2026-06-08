#!/usr/bin/env python3
"""Verify the non-production Hermes wake ONNX fixture contract.

This verifier intentionally avoids claiming semantic wake-word accuracy. It
checks that the generated test model matches the Android raw PCM ONNX contract
and that the fixture amplitude rule can produce above/below-threshold outputs.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path


DEFAULT_MODEL = "native/android/build/generated/voice/hermes-test-only.onnx"
THRESHOLD = 0.58


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
    shift = 0
    value = 0
    while True:
        if offset >= len(data):
            raise ValueError("truncated varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7


def iter_fields(data: bytes):
    offset = 0
    while offset < len(data):
        tag, offset = read_varint(data, offset)
        field = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 0:
            value, offset = read_varint(data, offset)
            yield field, wire_type, value
        elif wire_type == 2:
            length, offset = read_varint(data, offset)
            value = data[offset : offset + length]
            offset += length
            yield field, wire_type, value
        else:
            raise ValueError(f"unsupported wire type {wire_type}")


def as_string(value: bytes) -> str:
    return value.decode("utf-8")


def parse_dimensions(value_info: bytes) -> list[int]:
    type_proto = next(value for field, _, value in iter_fields(value_info) if field == 2)
    tensor_type = next(value for field, _, value in iter_fields(type_proto) if field == 1)
    shape = next(value for field, _, value in iter_fields(tensor_type) if field == 2)
    dimensions: list[int] = []
    for field, _, dim in iter_fields(shape):
        if field != 1:
            continue
        dim_value = next(value for dim_field, _, value in iter_fields(dim) if dim_field == 1)
        dimensions.append(dim_value)
    return dimensions


def parse_model(path: Path) -> dict[str, object]:
    graph = None
    producer = ""
    doc = ""
    for field, _, value in iter_fields(path.read_bytes()):
        if field == 2:
            producer = as_string(value)
        elif field == 7:
            graph = value
        elif field == 10:
            doc = as_string(value)
    if graph is None:
        raise ValueError("missing GraphProto")

    nodes: list[str] = []
    inputs: dict[str, list[int]] = {}
    outputs: dict[str, list[int]] = {}
    for field, _, value in iter_fields(graph):
        if field == 1:
            op_type = ""
            for node_field, _, node_value in iter_fields(value):
                if node_field == 4:
                    op_type = as_string(node_value)
            nodes.append(op_type)
        elif field == 11:
            name = ""
            for vi_field, _, vi_value in iter_fields(value):
                if vi_field == 1:
                    name = as_string(vi_value)
            inputs[name] = parse_dimensions(value)
        elif field == 12:
            name = ""
            for vi_field, _, vi_value in iter_fields(value):
                if vi_field == 1:
                    name = as_string(vi_value)
            outputs[name] = parse_dimensions(value)
    return {"producer": producer, "doc": doc, "nodes": nodes, "inputs": inputs, "outputs": outputs}


def mean_abs_confidence(samples: list[float]) -> float:
    return sum(abs(sample) for sample in samples) / len(samples)


def assert_contract(model: dict[str, object]) -> None:
    inputs = model["inputs"]
    outputs = model["outputs"]
    nodes = model["nodes"]
    if inputs != {"waveform": [1, 16_000]}:
        raise AssertionError(f"unexpected inputs: {inputs}")
    if outputs != {"confidence": [1, 1]}:
        raise AssertionError(f"unexpected outputs: {outputs}")
    if nodes != ["Abs", "ReduceMean"]:
        raise AssertionError(f"unexpected nodes: {nodes}")
    if "NON_PRODUCTION" not in model["doc"]:
        raise AssertionError("model doc_string must mark fixture as NON_PRODUCTION")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Generated test ONNX path. Default: %(default)s")
    args = parser.parse_args()

    model_path = Path(args.model)
    model = parse_model(model_path)
    assert_contract(model)

    positive = [0.95 * math.sin(index * 0.05) for index in range(16_000)]
    positive_confidence = mean_abs_confidence(positive)
    if positive_confidence < THRESHOLD:
        raise AssertionError(f"positive fixture confidence {positive_confidence:.3f} below {THRESHOLD}")

    negative_silence = [0.0 for _ in range(16_000)]
    silence_confidence = mean_abs_confidence(negative_silence)
    if silence_confidence >= THRESHOLD:
        raise AssertionError(f"silence confidence {silence_confidence:.3f} above {THRESHOLD}")

    negative_speech_like = [0.12 * math.sin(index * 0.13) for index in range(16_000)]
    speech_confidence = mean_abs_confidence(negative_speech_like)
    if speech_confidence >= THRESHOLD:
        raise AssertionError(f"speech-like confidence {speech_confidence:.3f} above {THRESHOLD}")

    print(f"Verified non-production wake model fixture: {model_path}")
    print(f"Contract: waveform float32 [1,16000] -> confidence float32 [1,1]")
    print(f"positive_fixture_confidence={positive_confidence:.3f}")
    print(f"negative_silence_confidence={silence_confidence:.3f}")
    print(f"negative_speech_like_confidence={speech_confidence:.3f}")
    print("This proves fixture mechanics only; it is not real Hermes wake detection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
