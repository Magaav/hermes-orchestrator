#!/usr/bin/env python3
"""Train a repo-local baseline Hermes wake model and export ONNX.

This is a real binary classifier training path, but it is intentionally labeled
as a baseline candidate. It exists to make the Android raw-PCM ONNX contract
reproducible from local WAV data; it is not a production-quality wake-word
pipeline by itself.
"""

from __future__ import annotations

import argparse
import random
import subprocess
import sys
import wave
from pathlib import Path


SAMPLE_RATE = 16_000
WINDOW = 16_000


def load_wav(path: Path) -> "np.ndarray":
    import numpy as np

    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        rate = wav.getframerate()
        width = wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())
    if width != 2:
        raise ValueError(f"{path} must be PCM16 WAV, got sample_width={width}")
    audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE and audio.size:
        duration = audio.size / float(rate)
        old_x = np.linspace(0.0, duration, num=audio.size, endpoint=False)
        new_count = max(1, int(round(duration * SAMPLE_RATE)))
        new_x = np.linspace(0.0, duration, num=new_count, endpoint=False)
        audio = np.interp(new_x, old_x, audio).astype(np.float32)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 1.0:
        audio = audio / peak
    if audio.size < WINDOW:
        audio = np.pad(audio, (WINDOW - audio.size, 0))
    elif audio.size > WINDOW:
        start = random.randint(0, audio.size - WINDOW)
        audio = audio[start : start + WINDOW]
    return audio.astype(np.float32)


def wavs(path: Path) -> list[Path]:
    return sorted(item for item in path.glob("*.wav") if item.is_file() and item.stat().st_size > 0)


def collect(dataset: Path) -> tuple[list[Path], list[Path]]:
    positives = wavs(dataset / "positive")
    negatives = []
    for subdir in ("negative/silence", "negative/speech", "negative/noise"):
        negatives.extend(wavs(dataset / subdir))
    return positives, sorted(negatives)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="data/voice/hermes")
    parser.add_argument("--output", default="build/voice/hermes.onnx")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--skip-verify", action="store_true")
    args = parser.parse_args()

    try:
        import numpy as np
        import torch
        from torch import nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError as error:
        raise SystemExit(
            "Missing training dependencies. Run tools/voice/fetch-or-setup-wake-training.sh "
            f"or install numpy torch onnx onnxruntime. Details: {error}"
        ) from error

    random.seed(7)
    torch.manual_seed(7)
    dataset = Path(args.dataset)
    positives, negatives = collect(dataset)
    if len(positives) < 5 or len(negatives) < 10:
        raise SystemExit(
            "Not enough real audio for a tiny smoke baseline. Need at least 5 positive "
            f"and 10 negative WAVs; found positive={len(positives)} negative={len(negatives)}."
        )

    paths = positives + negatives
    labels = [1.0] * len(positives) + [0.0] * len(negatives)
    pairs = list(zip(paths, labels, strict=True))
    random.shuffle(pairs)
    x = np.stack([load_wav(path) for path, _ in pairs])
    y = np.array([label for _, label in pairs], dtype=np.float32)

    loader = DataLoader(
        TensorDataset(torch.from_numpy(x[:, None, :]), torch.from_numpy(y[:, None])),
        batch_size=args.batch_size,
        shuffle=True,
    )

    class BaselineWakeCnn(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.net = nn.Sequential(
                nn.Conv1d(1, 8, kernel_size=251, stride=8, padding=125),
                nn.BatchNorm1d(8),
                nn.ReLU(),
                nn.MaxPool1d(4),
                nn.Conv1d(8, 16, kernel_size=31, stride=2, padding=15),
                nn.BatchNorm1d(16),
                nn.ReLU(),
                nn.MaxPool1d(4),
                nn.Conv1d(16, 32, kernel_size=15, stride=2, padding=7),
                nn.ReLU(),
                nn.AdaptiveAvgPool1d(1),
                nn.Flatten(),
                nn.Linear(32, 1),
                nn.Sigmoid(),
            )

        def forward(self, samples: "torch.Tensor") -> "torch.Tensor":
            if samples.dim() == 2:
                samples = samples.unsqueeze(1)
            return self.net(samples)

    model = BaselineWakeCnn()
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate)
    loss_fn = nn.BCELoss()
    for epoch in range(args.epochs):
        total = 0.0
        for batch_x, batch_y in loader:
            optimizer.zero_grad()
            loss = loss_fn(model(batch_x), batch_y)
            loss.backward()
            optimizer.step()
            total += float(loss.item()) * batch_x.size(0)
        if epoch == 0 or (epoch + 1) % 10 == 0:
            print(f"epoch={epoch + 1} loss={total / len(loader.dataset):.6f}")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    model.eval()
    dummy = torch.zeros(1, WINDOW, dtype=torch.float32)
    torch.onnx.export(
        model,
        dummy,
        str(output),
        input_names=["pcm"],
        output_names=["wake_confidence"],
        opset_version=17,
        dynamic_axes=None,
    )
    print(f"Exported baseline candidate: {output}")

    if not args.skip_verify:
        result = subprocess.run(
            [
                sys.executable,
                "tools/voice/verify-hermes-wake-model.py",
                "--model",
                str(output),
                "--validation-dir",
                str(dataset / "validation"),
            ],
            check=False,
        )
        return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
