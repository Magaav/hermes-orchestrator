#!/usr/bin/env python3
"""Validate a Hermes wake dataset folder before ONNX training."""

from __future__ import annotations

import argparse
from pathlib import Path

from hermes_wake_lib import (
    NEGATIVE_KINDS,
    RECOMMENDED_NEGATIVE,
    RECOMMENDED_POSITIVE,
    REQUIRED_DIRS,
    SMOKE_NEGATIVE,
    SMOKE_POSITIVE,
    inspect_wav,
    print_gate,
)


def wavs(dataset: Path) -> list[Path]:
    paths = list((dataset / "positive").glob("*.wav"))
    paths.extend((dataset / "negative").glob("*/*.wav"))
    return sorted(path for path in paths if path.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", nargs="?", default="data/voice/hermes")
    args = parser.parse_args()
    dataset = Path(args.dataset)

    failures: list[str] = []
    warnings: list[str] = []
    print(f"Hermes dataset verification: {dataset}")

    for relative in REQUIRED_DIRS:
        if not (dataset / relative).is_dir():
            failures.append(f"missing required folder: {dataset / relative}")

    all_wavs = wavs(dataset)
    if not all_wavs:
        failures.append("no usable WAVs exist")

    positive = 0
    negatives = {kind: 0 for kind in NEGATIVE_KINDS}
    sidecars_missing = 0
    zero_byte = 0
    invalid = 0
    too_short = 0
    too_quiet = 0

    for path in all_wavs:
        relative = path.relative_to(dataset)
        if relative.parts[0] == "positive":
            positive += 1
        elif len(relative.parts) >= 3 and relative.parts[0] == "negative":
            negatives[relative.parts[1]] = negatives.get(relative.parts[1], 0) + 1
        sidecar = path.with_suffix(".json")
        if not sidecar.exists():
            sidecars_missing += 1
            warnings.append(f"missing sidecar JSON: {sidecar}")
        report = inspect_wav(path)
        if report.issue == "zero-byte":
            zero_byte += 1
            failures.append(f"zero-byte WAV: {path}")
        elif not report.ok:
            invalid += 1
            failures.append(f"invalid WAV: {path} ({report.issue})")
        if report.too_short:
            too_short += 1
            warnings.append(f"too-short WAV: {path} ({report.duration:.3f}s)")
        if report.too_quiet:
            too_quiet += 1
            warnings.append(f"too-quiet WAV: {path} (rms={report.rms:.6f})")

    total_negative = sum(negatives.values())
    print(f"positive: {positive}")
    for kind in NEGATIVE_KINDS:
        print(f"negative/{kind}: {negatives[kind]}")
    print(f"total_negative: {total_negative}")
    print(f"zero_byte: {zero_byte}")
    print(f"invalid: {invalid}")
    print(f"too_short: {too_short}")
    print(f"too_quiet: {too_quiet}")
    print(f"missing_sidecar_json: {sidecars_missing}")
    print_gate("smoke gate", positive, total_negative, SMOKE_POSITIVE, SMOKE_NEGATIVE)
    print_gate("recommended gate", positive, total_negative, RECOMMENDED_POSITIVE, RECOMMENDED_NEGATIVE)

    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    if failures:
        print("Failures:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
