#!/usr/bin/env python3
"""Audit the local Hermes wake-word dataset."""

from __future__ import annotations

import argparse
import wave
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


CATEGORIES = {
    "positive": "positive",
    "negative/silence": "negative/silence",
    "negative/speech": "negative/speech",
    "negative/noise": "negative/noise",
    "validation": "validation",
}

TINY_POSITIVE = 5
TINY_NEGATIVE = 10
USEFUL_POSITIVE = 50
USEFUL_NEGATIVE = 150
PRODUCTION_POSITIVE = 100
PRODUCTION_NEGATIVE = 300


@dataclass
class WavInfo:
    path: Path
    size: int
    valid: bool
    duration: float = 0.0
    sample_rate: int | None = None
    channels: int | None = None
    sample_width: int | None = None
    warning: str | None = None


def inspect_wav(path: Path) -> WavInfo:
    size = path.stat().st_size
    if size == 0:
        return WavInfo(path=path, size=size, valid=False, warning="zero-byte placeholder")
    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_rate = wav.getframerate()
            sample_width = wav.getsampwidth()
            frames = wav.getnframes()
    except wave.Error as error:
        return WavInfo(path=path, size=size, valid=False, warning=f"invalid WAV: {error}")

    duration = frames / float(sample_rate) if sample_rate else 0.0
    warning = None
    if channels != 1 or sample_rate != 16_000 or sample_width != 2:
        warning = f"non-contract WAV channels={channels} sample_rate={sample_rate} sample_width={sample_width}"
    if frames == 0:
        warning = "WAV contains no audio frames"
    return WavInfo(
        path=path,
        size=size,
        valid=frames > 0,
        duration=duration,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
        warning=warning,
    )


def wavs(root: Path, relative: str) -> list[Path]:
    path = root / relative
    if not path.exists():
        return []
    return sorted(item for item in path.glob("*.wav") if item.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="data/voice/hermes")
    args = parser.parse_args()

    dataset = Path(args.dataset)
    all_infos: dict[str, list[WavInfo]] = {}
    print(f"Hermes dataset audit: {dataset}")

    for label, relative in CATEGORIES.items():
        infos = [inspect_wav(path) for path in wavs(dataset, relative)]
        all_infos[label] = infos
        real = [info for info in infos if info.valid and info.size > 0]
        duration = sum(info.duration for info in real)
        print(f"{label}: real={len(real)} files={len(infos)} duration={duration:.2f}s")

    print()
    print("Audio formats:")
    formats: Counter[tuple[int | None, int | None, int | None]] = Counter()
    for infos in all_infos.values():
        for info in infos:
            if info.sample_rate is not None:
                formats[(info.sample_rate, info.channels, info.sample_width)] += 1
    if formats:
        for (sample_rate, channels, sample_width), count in sorted(formats.items()):
            print(f"- {count} file(s): sample_rate={sample_rate} channels={channels} sample_width={sample_width}")
    else:
        print("- no readable non-empty WAV files")

    warnings: defaultdict[str, list[str]] = defaultdict(list)
    for label, infos in all_infos.items():
        for info in infos:
            if info.warning:
                warnings[label].append(f"{info.path} ({info.warning})")
    print()
    print("Warnings:")
    if warnings:
        for label in CATEGORIES:
            for warning in warnings.get(label, []):
                print(f"- {label}: {warning}")
    else:
        print("- none")

    positive = len([info for info in all_infos["positive"] if info.valid and info.size > 0])
    negative = sum(
        len([info for info in all_infos[label] if info.valid and info.size > 0])
        for label in ("negative/silence", "negative/speech", "negative/noise")
    )
    validation = len([info for info in all_infos["validation"] if info.valid and info.size > 0])

    print()
    print("Training readiness:")
    print(f"- tiny smoke: {'PASS' if positive >= TINY_POSITIVE and negative >= TINY_NEGATIVE else 'FAIL'} "
          f"(need positive>={TINY_POSITIVE}, negative>={TINY_NEGATIVE}; found positive={positive}, negative={negative})")
    print(f"- useful baseline: {'PASS' if positive >= USEFUL_POSITIVE and negative >= USEFUL_NEGATIVE else 'FAIL'} "
          f"(need positive>={USEFUL_POSITIVE}, negative>={USEFUL_NEGATIVE})")
    print(f"- production candidate: {'PASS' if positive >= PRODUCTION_POSITIVE and negative >= PRODUCTION_NEGATIVE else 'FAIL'} "
          f"(aim positive>={PRODUCTION_POSITIVE}, negative>={PRODUCTION_NEGATIVE}, plus device diversity)")
    print(f"- validation fixtures: {'PASS' if validation >= 4 else 'FAIL'} (need four held-out real validation WAVs)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
