#!/usr/bin/env python3
"""Shared helpers for repo-side Hermes wake dataset tooling."""

from __future__ import annotations

import json
import math
import wave
from dataclasses import dataclass
from pathlib import Path


SAMPLE_RATE = 16_000
WINDOW_SAMPLES = 16_000
SMOKE_POSITIVE = 5
SMOKE_NEGATIVE = 10
RECOMMENDED_POSITIVE = 50
RECOMMENDED_NEGATIVE = 200
NEGATIVE_KINDS = ("silence", "speech", "noise")
REQUIRED_DIRS = (
    "positive",
    "negative/silence",
    "negative/speech",
    "negative/noise",
)


@dataclass
class WavReport:
    path: Path
    ok: bool
    duration: float = 0.0
    sample_rate: int | None = None
    channels: int | None = None
    sample_width: int | None = None
    frames: int = 0
    rms: float | None = None
    issue: str | None = None
    convertible: bool = False
    too_short: bool = False
    too_quiet: bool = False


def print_gate(label: str, positive: int, negative: int, min_positive: int, min_negative: int) -> bool:
    passed = positive >= min_positive and negative >= min_negative
    status = "PASS" if passed else "FAIL"
    print(
        f"{label}: {status} "
        f"(positive={positive}/{min_positive}, total_negative={negative}/{min_negative})"
    )
    return passed


def dataset_counts(dataset: Path) -> tuple[int, dict[str, int]]:
    positive = len(list((dataset / "positive").glob("*.wav"))) if (dataset / "positive").exists() else 0
    negatives = {
        kind: len(list((dataset / "negative" / kind).glob("*.wav")))
        if (dataset / "negative" / kind).exists()
        else 0
        for kind in NEGATIVE_KINDS
    }
    return positive, negatives


def inspect_wav(path: Path, min_duration: float = 0.20, quiet_rms: float = 0.002) -> WavReport:
    if not path.exists():
        return WavReport(path=path, ok=False, issue="missing")
    if path.stat().st_size == 0:
        return WavReport(path=path, ok=False, issue="zero-byte")
    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_rate = wav.getframerate()
            sample_width = wav.getsampwidth()
            frames = wav.getnframes()
            raw = wav.readframes(frames)
    except (wave.Error, EOFError) as error:
        return WavReport(path=path, ok=False, issue=f"invalid WAV: {error}")

    duration = frames / float(sample_rate) if sample_rate else 0.0
    convertible = channels >= 1 and sample_rate > 0 and sample_width in (1, 2, 4) and frames > 0
    too_short = duration < min_duration
    rms = None
    too_quiet = False
    if sample_width == 2 and raw:
        total = 0.0
        samples = 0
        for index in range(0, len(raw) - 1, 2):
            value = int.from_bytes(raw[index : index + 2], "little", signed=True) / 32768.0
            total += value * value
            samples += 1
        rms = math.sqrt(total / samples) if samples else 0.0
        too_quiet = rms < quiet_rms
    issue = None
    if not convertible:
        issue = (
            f"not convertible channels={channels} sample_rate={sample_rate} "
            f"sample_width={sample_width} frames={frames}"
        )
    return WavReport(
        path=path,
        ok=convertible,
        duration=duration,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
        frames=frames,
        rms=rms,
        issue=issue,
        convertible=convertible,
        too_short=too_short,
        too_quiet=too_quiet,
    )


def load_audio(path: Path, window_samples: int = WINDOW_SAMPLES):
    import numpy as np

    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        rate = wav.getframerate()
        width = wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())
    if width == 1:
        audio = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        audio = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"{path} has unsupported sample width: {width}")
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE and audio.size:
        duration = audio.size / float(rate)
        old_x = np.linspace(0.0, duration, num=audio.size, endpoint=False)
        new_count = max(1, int(round(duration * SAMPLE_RATE)))
        new_x = np.linspace(0.0, duration, num=new_count, endpoint=False)
        audio = np.interp(new_x, old_x, audio).astype(np.float32)
    audio = np.clip(audio, -1.0, 1.0).astype(np.float32)
    if audio.size < window_samples:
        audio = np.pad(audio, (0, window_samples - audio.size))
    elif audio.size > window_samples:
        audio = audio[:window_samples]
    return audio.astype(np.float32)


def write_threshold(path: Path, threshold: float, metrics: dict[str, float | int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"threshold": threshold, "sample_rate": SAMPLE_RATE, "window_samples": WINDOW_SAMPLES, **metrics}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
