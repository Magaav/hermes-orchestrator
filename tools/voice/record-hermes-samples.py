#!/usr/bin/env python3
"""Record Hermes wake samples as mono 16 kHz PCM16 WAV files."""

from __future__ import annotations

import argparse
import subprocess
import wave
from datetime import datetime, timezone
from pathlib import Path


def write_wav(path: Path, samples: "np.ndarray") -> None:
    import numpy as np

    pcm = np.clip(samples, -1.0, 1.0)
    pcm16 = (pcm * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(pcm16.tobytes())


def sample_path(out_dir: Path, kind: str, speaker: str, device_label: str, index: int) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    stem = f"{kind}_{speaker}_{device_label}_{stamp}_{index + 1:03d}"
    path = out_dir / f"{stem}.wav"
    suffix = 1
    while path.exists():
        path = out_dir / f"{stem}_{suffix:02d}.wav"
        suffix += 1
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=["positive", "negative-silence", "negative-speech", "negative-noise"], required=True)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--seconds", type=float, default=1.0)
    parser.add_argument("--speaker", default="dev")
    parser.add_argument("--device-label", default="desktop")
    parser.add_argument("--dataset", default="data/voice/hermes")
    args = parser.parse_args()

    subdir = {
        "positive": "positive",
        "negative-silence": "negative/silence",
        "negative-speech": "negative/speech",
        "negative-noise": "negative/noise",
    }[args.kind]
    out_dir = Path(args.dataset) / subdir
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        import sounddevice as sd
        import numpy as np
    except ImportError:
        print("sounddevice is unavailable; trying the system 'rec' command.")
        for index in range(args.count):
            path = sample_path(out_dir, args.kind, args.speaker, args.device_label, index)
            subprocess.run(["rec", "-q", "-r", "16000", "-c", "1", "-b", "16", str(path), "trim", "0", str(args.seconds)], check=True)
            print(path)
        return 0

    for index in range(args.count):
        input(f"Press Enter to record {args.kind} sample {index + 1}/{args.count}...")
        audio = sd.rec(int(args.seconds * 16_000), samplerate=16_000, channels=1, dtype="float32")
        sd.wait()
        samples = np.asarray(audio[:, 0], dtype=np.float32)
        path = sample_path(out_dir, args.kind, args.speaker, args.device_label, index)
        write_wav(path, samples)
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
