#!/usr/bin/env python3
"""Train a tiny raw-PCM Hermes wake classifier and export Android ONNX."""

from __future__ import annotations

import argparse
import random
import subprocess
import sys
import warnings
from pathlib import Path

from hermes_wake_lib import (
    RECOMMENDED_NEGATIVE,
    RECOMMENDED_POSITIVE,
    SAMPLE_RATE,
    SMOKE_NEGATIVE,
    SMOKE_POSITIVE,
    WINDOW_SAMPLES,
    load_audio,
    print_gate,
    write_threshold,
)


def collect(dataset: Path) -> tuple[list[Path], list[Path]]:
    positives = sorted(path for path in (dataset / "positive").glob("*.wav") if path.is_file() and path.stat().st_size > 0)
    negatives = sorted(path for path in (dataset / "negative").glob("**/*.wav") if path.is_file() and path.stat().st_size > 0)
    return positives, negatives


def split_indices(count: int) -> tuple[list[int], list[int]]:
    if count < 4:
        return list(range(count)), list(range(count))
    validation_count = max(2, int(round(count * 0.2)))
    return list(range(validation_count, count)), list(range(validation_count))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="data/voice/hermes")
    parser.add_argument("--out", default="native/android/app/src/main/assets/voice/base_hermes.onnx")
    parser.add_argument("--allow-tiny", action="store_true")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--threshold-out", default=None)
    args = parser.parse_args()

    try:
        import numpy as np
        import torch
        from torch import nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError as error:
        raise SystemExit(
            "Missing training dependencies. Install numpy, torch, and onnx before training. "
            f"Details: {error}"
        ) from error

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    dataset = Path(args.dataset)
    positives, negatives = collect(dataset)
    total_negative = len(negatives)
    print_gate("smoke gate", len(positives), total_negative, SMOKE_POSITIVE, SMOKE_NEGATIVE)
    print_gate("recommended gate", len(positives), total_negative, RECOMMENDED_POSITIVE, RECOMMENDED_NEGATIVE)
    if (len(positives) < SMOKE_POSITIVE or total_negative < SMOKE_NEGATIVE) and not args.allow_tiny:
        raise SystemExit("Dataset is below smoke gate; pass --allow-tiny for synthetic/dev fixtures.")
    if not positives or not negatives:
        raise SystemExit(f"Need both classes to train; found positive={len(positives)} negative={len(negatives)}")

    pairs = [(path, 1.0) for path in positives] + [(path, 0.0) for path in negatives]
    rng = random.Random(args.seed)
    rng.shuffle(pairs)
    x = np.stack([load_audio(path, WINDOW_SAMPLES) for path, _ in pairs]).astype(np.float32)
    y = np.array([label for _, label in pairs], dtype=np.float32)

    train_idx, val_idx = split_indices(len(pairs))
    train_x = torch.from_numpy(x[train_idx, None, :])
    train_y = torch.from_numpy(y[train_idx, None])
    val_x = torch.from_numpy(x[val_idx, None, :])
    val_y_np = y[val_idx]

    class HermesWakeCnn(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.net = nn.Sequential(
                nn.Conv1d(1, 8, kernel_size=251, stride=16, padding=125),
                nn.ReLU(),
                nn.MaxPool1d(4),
                nn.Conv1d(8, 16, kernel_size=31, stride=4, padding=15),
                nn.ReLU(),
                nn.AdaptiveAvgPool1d(1),
                nn.Flatten(),
                nn.Linear(16, 1),
                nn.Sigmoid(),
            )

        def forward(self, samples: "torch.Tensor") -> "torch.Tensor":
            if samples.dim() == 2:
                samples = samples.unsqueeze(1)
            return self.net(samples)

    model = HermesWakeCnn()
    loader = DataLoader(TensorDataset(train_x, train_y), batch_size=min(16, len(train_idx)), shuffle=True)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    loss_fn = nn.BCELoss()
    for epoch in range(max(1, args.epochs)):
        total = 0.0
        for batch_x, batch_y in loader:
            optimizer.zero_grad()
            loss = loss_fn(model(batch_x), batch_y)
            loss.backward()
            optimizer.step()
            total += float(loss.item()) * batch_x.size(0)
        if epoch == 0 or epoch + 1 == args.epochs:
            print(f"epoch={epoch + 1} loss={total / len(loader.dataset):.6f}")

    model.eval()
    with torch.no_grad():
        scores = model(val_x).numpy().reshape(-1)
    threshold = float(np.clip((scores[val_y_np == 1].mean() + scores[val_y_np == 0].mean()) / 2.0, 0.05, 0.95)) if len(scores) else 0.5
    predictions = scores >= threshold
    positives_mask = val_y_np == 1
    negatives_mask = val_y_np == 0
    accuracy = float((predictions == positives_mask).mean()) if len(scores) else 0.0
    recall = float(predictions[positives_mask].mean()) if positives_mask.any() else 0.0
    specificity = float((~predictions[negatives_mask]).mean()) if negatives_mask.any() else 0.0

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    dummy = torch.zeros(1, WINDOW_SAMPLES, dtype=torch.float32)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        torch.onnx.export(
            model,
            dummy,
            str(output),
            input_names=["pcm"],
            output_names=["wake_confidence"],
            opset_version=17,
            dynamic_axes=None,
            dynamo=False,
        )

    print(f"train count: {len(train_idx)}")
    print(f"validation count: {len(val_idx)}")
    print(f"positive count: {len(positives)}")
    print(f"negative count: {len(negatives)}")
    print(f"validation accuracy: {accuracy:.4f}")
    print(f"positive recall: {recall:.4f}")
    print(f"negative rejection / specificity: {specificity:.4f}")
    print(f"suggested wake threshold: {threshold:.4f}")
    print(f"exported ONNX: {output}")
    if args.threshold_out:
        write_threshold(
            Path(args.threshold_out),
            threshold,
            {
                "validation_accuracy": accuracy,
                "positive_recall": recall,
                "negative_specificity": specificity,
                "train_count": len(train_idx),
                "validation_count": len(val_idx),
            },
        )

    sys.stdout.flush()
    checker = Path(__file__).with_name("check-hermes-onnx.py")
    return subprocess.run([sys.executable, str(checker), str(output), "--dataset", str(dataset)], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
