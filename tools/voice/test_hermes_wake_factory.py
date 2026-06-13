#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


def write_wav(path: Path, freq: float = 440.0, duration: float = 0.5) -> None:
    import math
    import struct

    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(16_000 * duration)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        data = bytearray()
        for index in range(frames):
            value = int(10_000 * math.sin(2.0 * math.pi * freq * index / 16_000))
            data.extend(struct.pack("<h", value))
        wav.writeframes(bytes(data))


def write_fixture_dataset(root: Path, positives: int = 5, negatives: int = 10) -> Path:
    dataset = root / "dataset"
    for i in range(positives):
        path = dataset / "positive" / f"hermes-{i}.wav"
        write_wav(path, 440.0 + i)
        path.with_suffix(".json").write_text('{"label":"positive"}\n', encoding="utf-8")
    kinds = ["silence", "speech", "noise"]
    for i in range(negatives):
        path = dataset / "negative" / kinds[i % len(kinds)] / f"negative-{i}.wav"
        write_wav(path, 220.0 + i)
        path.with_suffix(".json").write_text('{"label":"negative"}\n', encoding="utf-8")
    (dataset / "metadata.json").write_text("{}\n", encoding="utf-8")
    return dataset


class HermesWakeFactoryTest(unittest.TestCase):
    def run_cmd(self, args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)

    def test_import_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "bad.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("../escape.wav", b"bad")
            result = self.run_cmd([PYTHON, "tools/voice/import-hermes-dataset.py", str(archive), "--out", str(Path(temp) / "out")])
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("unsafe zip member path", result.stdout)

    def test_import_preserves_folder_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = write_fixture_dataset(Path(temp), positives=1, negatives=3)
            archive = Path(temp) / "hermes-dataset.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                for path in source.rglob("*"):
                    if path.is_file():
                        zf.write(path, path.relative_to(source).as_posix())
            out = Path(temp) / "out"
            result = self.run_cmd([PYTHON, "tools/voice/import-hermes-dataset.py", str(archive), "--out", str(out)])
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertTrue((out / "positive" / "hermes-0.wav").exists())
            self.assertTrue((out / "negative" / "speech" / "negative-1.json").exists())
            self.assertIn("smoke gate: FAIL", result.stdout)

    def test_import_accepts_android_run_as_tar_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = write_fixture_dataset(Path(temp), positives=1, negatives=3)
            archive = Path(temp) / "hermes-dataset.tar"
            with tarfile.open(archive, "w") as tf:
                tf.add(source, arcname="hermes-dataset")
            out = Path(temp) / "out"
            result = self.run_cmd([PYTHON, "tools/voice/import-hermes-dataset.py", str(archive), "--out", str(out)])
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertTrue((out / "positive" / "hermes-0.wav").exists())
            self.assertTrue((out / "negative" / "noise" / "negative-2.wav").exists())
            self.assertIn("positive: 1", result.stdout)

    def test_verifier_detects_counts_and_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            dataset = write_fixture_dataset(Path(temp), positives=5, negatives=10)
            result = self.run_cmd([PYTHON, "tools/voice/verify-hermes-dataset.py", str(dataset)])
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("smoke gate: PASS", result.stdout)
            self.assertIn("recommended gate: FAIL", result.stdout)

    def test_verifier_rejects_zero_byte_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            dataset = write_fixture_dataset(Path(temp), positives=1, negatives=1)
            bad = dataset / "positive" / "bad.wav"
            bad.write_bytes(b"")
            bad.with_suffix(".json").write_text("{}\n", encoding="utf-8")
            result = self.run_cmd([PYTHON, "tools/voice/verify-hermes-dataset.py", str(dataset)])
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("zero-byte WAV", result.stdout)

    @unittest.skipUnless(
        all(shutil.which(executable) or executable == "python" for executable in ["python"]),
        "python unavailable",
    )
    def test_trainer_and_checker_on_tiny_fixture_when_dependencies_exist(self) -> None:
        try:
            import numpy  # noqa: F401
            import onnx  # noqa: F401
            import onnxruntime  # noqa: F401
            import torch  # noqa: F401
        except ImportError as error:
            self.skipTest(f"ML dependencies unavailable: {error}")
        with tempfile.TemporaryDirectory() as temp:
            dataset = write_fixture_dataset(Path(temp), positives=2, negatives=2)
            out = Path(temp) / "base_hermes.onnx"
            train = self.run_cmd(
                [
                    PYTHON,
                    "tools/voice/train-hermes-wake.py",
                    "--dataset",
                    str(dataset),
                    "--out",
                    str(out),
                    "--allow-tiny",
                    "--epochs",
                    "1",
                ]
            )
            self.assertEqual(train.returncode, 0, train.stdout)
            self.assertTrue(out.exists())
            check = self.run_cmd([PYTHON, "tools/voice/check-hermes-onnx.py", str(out), "--dataset", str(dataset)])
            self.assertEqual(check.returncode, 0, check.stdout)

    def test_apk_inspection_no_model_mode_still_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            apk = Path(temp) / "app-debug.apk"
            with zipfile.ZipFile(apk, "w") as zf:
                for abi in ["arm64-v8a", "armeabi-v7a", "x86", "x86_64"]:
                    zf.writestr(f"lib/{abi}/libonnxruntime.so", b"lib")
                zf.writestr("assets/voice/README.md", b"contract")
            result = self.run_cmd(["native/android/scripts/inspect-wake-apk.sh", str(apk), "--expect-no-model"])
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_apk_inspection_base_model_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            apk = Path(temp) / "app-debug.apk"
            with zipfile.ZipFile(apk, "w") as zf:
                for abi in ["arm64-v8a", "armeabi-v7a", "x86", "x86_64"]:
                    zf.writestr(f"lib/{abi}/libonnxruntime.so", b"lib")
                zf.writestr("assets/voice/README.md", b"contract")
                zf.writestr("assets/voice/base_hermes.onnx", b"onnx")
            result = self.run_cmd(["native/android/scripts/inspect-wake-apk.sh", str(apk), "--expect-base-model"])
            self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
