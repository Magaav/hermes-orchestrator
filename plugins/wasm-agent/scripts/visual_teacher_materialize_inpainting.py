#!/usr/bin/env python3
"""Materialize immutable inpainting triplets without leaking private holdouts."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path

from PIL import Image

PAIR_ID = re.compile(r"pair_[0-9a-f]{24}")
SCHEMA = "hermes.property_photo_cleaner.inpainting_corpus.v1"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def blob_path(root: Path, digest: str) -> Path:
    return root / "blobs" / digest[:2] / digest


def lineage_group(pair_id: str, manifest: dict) -> str:
    text = " ".join([
        str(manifest.get("contract", {}).get("objective", "")),
        str(manifest.get("provenance", {}).get("session_id", "")),
    ])
    parents = [value for value in PAIR_ID.findall(text) if value != pair_id]
    return parents[0] if parents else pair_id


def inspect_triplet(root: Path, pair_id: str, partition: str) -> dict:
    manifest_path = root / "candidates" / f"{pair_id}.json"
    manifest_bytes = manifest_path.read_bytes().rstrip(b"\n")
    manifest = json.loads(manifest_bytes)
    blobs = manifest["blobs"]
    paths = {name: blob_path(root, detail["sha256"]) for name, detail in blobs.items()}
    for name, path in paths.items():
        content = path.read_bytes()
        if sha256(content) != blobs[name]["sha256"]:
            raise ValueError(f"{pair_id}: {name} blob digest mismatch")
    with Image.open(paths["source"]) as source, Image.open(paths["teacher_output"]) as target, Image.open(paths["mask"]) as mask:
        if source.size != target.size or source.size != mask.size:
            raise ValueError(f"{pair_id}: source, mask, and target dimensions differ")
        if mask.mode != "RGBA":
            raise ValueError(f"{pair_id}: mask must be RGBA")
        alpha = mask.getchannel("A")
        histogram = alpha.histogram()
        removed = sum(histogram[:128])
        total = mask.width * mask.height
        if removed == 0 or removed == total:
            raise ValueError(f"{pair_id}: mask must preserve and reconstruct non-empty regions")
        dimensions = [source.width, source.height]
    return {
        "pairId": pair_id,
        "partition": partition,
        "lineageGroup": lineage_group(pair_id, manifest),
        "manifestSha256": sha256(manifest_bytes),
        "dimensions": dimensions,
        "mask": {
            "sha256": blobs["mask"]["sha256"],
            "path": str(paths["mask"].relative_to(root)),
            "semantics": "alpha_lt_128_reconstruct",
            "reconstructFraction": round(removed / total, 8),
        },
        "source": {
            "sha256": blobs["source"]["sha256"],
            "path": str(paths["source"].relative_to(root)),
            "mediaType": blobs["source"]["media_type"],
        },
        "target": {
            "sha256": blobs["teacher_output"]["sha256"],
            "path": str(paths["teacher_output"].relative_to(root)),
            "mediaType": blobs["teacher_output"]["media_type"],
        },
        "contractSha256": sha256(canonical(manifest["contract"])),
    }


def approvals(root: Path, partition: str) -> list[Path]:
    directory = root / ("private/holdout" if partition == "holdout" else f"approved/{partition}")
    return sorted(directory.glob("pair_*.json"))


def approved_pair_ids(root: Path, partition: str) -> list[str]:
    return [
        json.loads(path.read_text(encoding="utf-8"))["pair_id"]
        for path in approvals(root, partition)
    ]


def approved_lineage_group(root: Path, pair_id: str) -> str:
    manifest = json.loads((root / "candidates" / f"{pair_id}.json").read_text(encoding="utf-8"))
    return lineage_group(pair_id, manifest)


def materialize(
    root: Path,
    corpus_id: str,
    output_root: Path | None = None,
    private_output_root: Path | None = None,
) -> dict:
    pair_ids = {
        partition: approved_pair_ids(root, partition)
        for partition in ("training", "gold", "holdout")
    }
    training = [inspect_triplet(root, pair_id, "training") for pair_id in pair_ids["training"]]
    training_groups = {entry["lineageGroup"] for entry in training}
    contaminated_gold = [
        pair_id for pair_id in pair_ids["gold"]
        if pair_id in training_groups or approved_lineage_group(root, pair_id) in training_groups
    ]
    admitted_gold = [
        inspect_triplet(root, pair_id, "gold")
        for pair_id in pair_ids["gold"]
        if pair_id not in contaminated_gold
    ]
    holdout = [inspect_triplet(root, pair_id, "holdout") for pair_id in pair_ids["holdout"]]
    public_root = (output_root or root / "corpora") / corpus_id
    private_root = private_output_root or root / "private" / "corpora"
    public_root.mkdir(parents=True, exist_ok=True)
    private_root.mkdir(parents=True, exist_ok=True)

    training_manifest = {
        "schema": SCHEMA,
        "corpusId": corpus_id,
        "partition": "training",
        "entries": training,
    }
    gold_manifest = {
        "schema": SCHEMA,
        "corpusId": corpus_id,
        "partition": "gold",
        "entries": admitted_gold,
        "excludedForLineageLeakage": contaminated_gold,
    }
    holdout_manifest = {
        "schema": SCHEMA,
        "corpusId": corpus_id,
        "partition": "holdout",
        "access": "private",
        "entries": holdout,
    }
    private_bytes = canonical(holdout_manifest)
    outputs = {
        public_root / "training.json": canonical(training_manifest),
        public_root / "gold.json": canonical(gold_manifest),
        private_root / f"{corpus_id}-holdout.json": private_bytes,
    }
    summary = {
        "schema": "hermes.property_photo_cleaner.inpainting_corpus_summary.v1",
        "corpusId": corpus_id,
        "maskSemantics": "alpha_lt_128_reconstruct",
        "training": len(training),
        "goldDeclared": len(pair_ids["gold"]),
        "goldAdmitted": len(admitted_gold),
        "goldExcludedForLineageLeakage": len(contaminated_gold),
        "holdout": len(holdout),
        "holdoutDetail": "withheld",
        "privateHoldoutManifestSha256": sha256(private_bytes),
        "trainingLineageGroups": len(training_groups),
    }
    outputs[public_root / "summary.json"] = canonical(summary)
    for path, content in outputs.items():
        path.write_bytes(content + b"\n")
    return summary


def check_materialization(root: Path, corpus_id: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="property-inpainting-check-") as temporary:
        temporary_root = Path(temporary)
        summary = materialize(
            root,
            corpus_id,
            temporary_root / "public",
            temporary_root / "private",
        )
        expected_public = root / "corpora" / corpus_id
        generated_public = temporary_root / "public" / corpus_id
        for name in ("training.json", "gold.json", "summary.json"):
            if (expected_public / name).read_bytes() != (generated_public / name).read_bytes():
                raise ValueError(f"{corpus_id}: stale or changed public {name}")
        private_name = f"{corpus_id}-holdout.json"
        if (
            root / "private" / "corpora" / private_name
        ).read_bytes() != (temporary_root / "private" / private_name).read_bytes():
            raise ValueError(f"{corpus_id}: stale or changed private holdout manifest")
        return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[1] / "state" / "visual-teacher"),
    )
    parser.add_argument("--corpus-id", default="property-inpainting-v1")
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    action = check_materialization if arguments.check else materialize
    summary = action(Path(arguments.root), arguments.corpus_id)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
