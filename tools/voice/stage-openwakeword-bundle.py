#!/usr/bin/env python3
"""Stage an OpenWakeWord Android bundle as the next wake install candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


REQUIRED_MODELS = {
    "melspectrogram.onnx",
    "embedding_model.onnx",
    "hey_jarvis.onnx",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_model(args: argparse.Namespace, name: str) -> Path:
    explicit = getattr(args, name.replace(".", "_").replace("-", "_"), "")
    if explicit:
        return Path(explicit)
    source_dir = Path(args.source_dir)
    return source_dir / name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", default="", help="Directory containing melspectrogram.onnx, embedding_model.onnx, and hey_jarvis.onnx.")
    parser.add_argument("--melspectrogram-onnx", default="", help="Path to melspectrogram.onnx.")
    parser.add_argument("--embedding-model-onnx", default="", help="Path to embedding_model.onnx.")
    parser.add_argument("--hey-jarvis-onnx", default="", help="Path to hey_jarvis.onnx classifier.")
    parser.add_argument("--wake-phrase", default="hey jarvis")
    parser.add_argument("--model-name", default="openWakeWord hey jarvis")
    parser.add_argument("--source", default="https://github.com/dscripka/openWakeWord")
    parser.add_argument("--stage-dir", default="plugins/wasm-agent/state/native-diagnostics/android-hermes-wake-models/latest")
    args = parser.parse_args()

    if not args.source_dir and not (args.melspectrogram_onnx and args.embedding_model_onnx and args.hey_jarvis_onnx):
        raise SystemExit("Provide --source-dir or all three explicit ONNX paths.")

    models = {
        "melspectrogram.onnx": resolve_model(args, "melspectrogram.onnx"),
        "embedding_model.onnx": resolve_model(args, "embedding_model.onnx"),
        "hey_jarvis.onnx": resolve_model(args, "hey_jarvis.onnx"),
    }
    missing = [f"{name}: {path}" for name, path in models.items() if not path.is_file() or path.stat().st_size <= 0]
    if missing:
        raise SystemExit("Missing required OpenWakeWord models: " + "; ".join(missing))

    stage_dir = Path(args.stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)
    target = stage_dir / "openwakeword.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(REQUIRED_MODELS):
            archive.write(models[name], arcname=name)

    digest = sha256_file(target)
    metadata = {
        "schema": "hermes.wasm_agent.android_openwakeword_bundle_candidate.v1",
        "modelRole": "wake_phrase_candidate",
        "modelName": args.model_name,
        "wakePhrase": args.wake_phrase.strip().lower()[:80] or "hey jarvis",
        "engineContract": "openwakeword_bundle",
        "installPath": "files/voice/openwakeword",
        "source": args.source,
        "sourcePaths": {name: str(path) for name, path in models.items()},
        "stagedPath": str(target),
        "sha256": digest,
        "sizeBytes": target.stat().st_size,
        "requiredFiles": sorted(REQUIRED_MODELS),
    }
    (stage_dir / "openwakeword.zip.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
