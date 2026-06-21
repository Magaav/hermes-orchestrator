#!/usr/bin/env python3
"""Stage a compatible wake model as the next Android install candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Compatible raw-PCM ONNX wake model.")
    parser.add_argument("--wake-phrase", default="hey jarvis", help="Phrase this model is expected to detect.")
    parser.add_argument("--model-name", default="", help="Human-readable model name.")
    parser.add_argument("--source", default="", help="Source URL, repo, or note for the candidate.")
    parser.add_argument("--skip-contract-check", action="store_true")
    parser.add_argument("--stage-dir", default="plugins/wasm-agent/state/native-diagnostics/android-hermes-wake-models/latest")
    args = parser.parse_args()

    model = Path(args.model)
    if not model.is_file() or model.stat().st_size <= 0:
        raise SystemExit(f"Wake model does not exist or is empty: {model}")

    if not args.skip_contract_check:
        result = subprocess.run(
            [sys.executable, "tools/voice/check-hermes-onnx.py", str(model)],
            check=False,
        )
        if result.returncode != 0:
            return result.returncode

    stage_dir = Path(args.stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)
    target = stage_dir / "hermes.onnx"
    shutil.copy2(model, target)
    digest = sha256_file(target)
    metadata = {
        "schema": "hermes.wasm_agent.android_wake_model_candidate.v1",
        "modelRole": "wake_phrase_candidate",
        "modelName": args.model_name or model.stem,
        "wakePhrase": args.wake_phrase.strip().lower()[:80] or "hey jarvis",
        "engineContract": "raw_pcm_onnx_single_confidence",
        "installPath": "files/voice/hermes.onnx",
        "source": args.source,
        "sourcePath": str(model),
        "stagedPath": str(target),
        "sha256": digest,
        "sizeBytes": target.stat().st_size,
    }
    (stage_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
