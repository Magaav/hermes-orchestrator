#!/usr/bin/env python3
"""Validate and stage an externally exported Hermes wake ONNX candidate."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, help="Externally exported Hermes ONNX candidate.")
    parser.add_argument("--validation-dir", default="data/voice/hermes/validation")
    parser.add_argument("--stage-to", default="build/voice/hermes.onnx")
    parser.add_argument("--install-asset", action="store_true", help="After validation, copy to Android assets/voice/hermes.onnx.")
    args = parser.parse_args()

    candidate = Path(args.candidate)
    staged = Path(args.stage_to)
    if not candidate.exists():
        raise SystemExit(f"Candidate not found: {candidate}")
    staged.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidate, staged)

    verifier = Path("tools/voice/verify-hermes-wake-model.py")
    result = subprocess.run(
        [sys.executable, str(verifier), "--model", str(staged), "--validation-dir", args.validation_dir],
        check=False,
    )
    if result.returncode != 0:
        return result.returncode
    if args.install_asset:
        subprocess.run(["native/android/scripts/install-wake-model.sh", "--model", str(staged)], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
