#!/usr/bin/env python3
"""Import an Android Tune Voice hermes-dataset archive into data/voice/hermes."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from hermes_wake_lib import (
    NEGATIVE_KINDS,
    RECOMMENDED_NEGATIVE,
    RECOMMENDED_POSITIVE,
    REQUIRED_DIRS,
    SMOKE_NEGATIVE,
    SMOKE_POSITIVE,
    dataset_counts,
    print_gate,
)


def safe_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError(f"unsafe zip member path: {name}")
    return path


def normalized_payload_path(path: PurePosixPath) -> PurePosixPath | None:
    parts = path.parts
    if len(parts) >= 2 and parts[0] == "positive":
        return path if path.suffix.lower() in (".wav", ".json") else None
    if len(parts) >= 3 and parts[0] == "negative" and parts[1] in NEGATIVE_KINDS:
        return path if path.suffix.lower() in (".wav", ".json") else None
    if len(parts) == 1 and parts[0] == "metadata.json":
        return path
    if len(parts) >= 2 and parts[0] not in ("positive", "negative", "metadata.json"):
        candidate = PurePosixPath(*parts[1:])
        return normalized_payload_path(candidate)
    return None


def import_archive(archive_path: Path, out: Path) -> tuple[int, dict[str, int]]:
    if not archive_path.exists():
        raise SystemExit(f"Dataset archive not found: {archive_path}")
    with open_archive(archive_path) as archive:
        payload = archive.payload()
        if not payload:
            raise SystemExit("No usable dataset files found in archive.")
        wav_payload = [target for item in payload if (target := item[1]).suffix.lower() == ".wav"]
        if not wav_payload:
            raise SystemExit("No usable WAVs found in archive.")

        with tempfile.TemporaryDirectory(prefix="hermes-dataset-import-") as temp_dir:
            temp = Path(temp_dir)
            for relative in REQUIRED_DIRS:
                (temp / relative).mkdir(parents=True, exist_ok=True)
            copied: set[PurePosixPath] = set()
            for member, target_path in payload:
                destination = temp / Path(*target_path.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open_member(member) as source, destination.open("wb") as dest:
                    shutil.copyfileobj(source, dest)
                copied.add(target_path)
            if PurePosixPath("metadata.json") not in copied:
                (temp / "metadata.json").write_text(
                    json.dumps({"source": archive_path.name, "generated_by": "import-hermes-dataset.py"}, indent=2)
                    + "\n",
                    encoding="utf-8",
                )
            if out.exists():
                shutil.rmtree(out)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(temp), str(out))
    return dataset_counts(out)


class ZipDatasetArchive:
    def __init__(self, path: Path):
        self.archive = zipfile.ZipFile(path)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.archive.close()

    def payload(self):
        payload = []
        for member in self.archive.infolist():
            if member.is_dir():
                continue
            target_path = normalized_payload_path(safe_member_path(member.filename))
            if target_path is not None:
                payload.append((member, target_path))
        return payload

    def open_member(self, member):
        return self.archive.open(member)


class TarDatasetArchive:
    def __init__(self, path: Path):
        self.archive = tarfile.open(path)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.archive.close()

    def payload(self):
        payload = []
        for member in self.archive.getmembers():
            if not member.isfile():
                continue
            target_path = normalized_payload_path(safe_member_path(member.name))
            if target_path is not None:
                payload.append((member, target_path))
        return payload

    def open_member(self, member):
        source = self.archive.extractfile(member)
        if source is None:
            raise ValueError(f"cannot read tar member: {member.name}")
        return source


def open_archive(path: Path):
    if zipfile.is_zipfile(path):
        return ZipDatasetArchive(path)
    if tarfile.is_tarfile(path):
        return TarDatasetArchive(path)
    raise ValueError(f"unsupported dataset archive: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive_path", help="hermes-dataset.zip exported from Android Tune Voice, or a tar made with adb run-as.")
    parser.add_argument("--out", default="data/voice/hermes", help="Dataset output folder. Default: %(default)s")
    args = parser.parse_args()

    try:
        positive, negatives = import_archive(Path(args.archive_path), Path(args.out))
    except (zipfile.BadZipFile, tarfile.TarError, ValueError) as error:
        print(f"Import failed: {error}", file=sys.stderr)
        return 1

    total_negative = sum(negatives.values())
    print(f"Imported Hermes dataset: {args.out}")
    print(f"positive: {positive}")
    for kind in NEGATIVE_KINDS:
        print(f"negative/{kind}: {negatives[kind]}")
    print(f"total_negative: {total_negative}")
    print_gate("smoke gate", positive, total_negative, SMOKE_POSITIVE, SMOKE_NEGATIVE)
    print_gate("recommended gate", positive, total_negative, RECOMMENDED_POSITIVE, RECOMMENDED_NEGATIVE)
    if positive + total_negative == 0:
        print("Import failed: no usable WAVs exist.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
