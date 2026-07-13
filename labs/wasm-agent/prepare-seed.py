#!/usr/bin/env python3
"""Create a reviewed, secret-minimized /local seed archive for the safe lab."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = Path(__file__).resolve().parent
MANIFEST_PATH = LAB / "migration-manifest.json"
SEED_DIR = LAB / "seed"
ARCHIVE_PATH = SEED_DIR / "local-seed.tar"
INDEX_PATH = SEED_DIR / "local-seed-index.json"


def tracked_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def excluded(path: str, patterns: list[str]) -> bool:
    parts = path.split("/")
    basename = parts[-1]
    return any(
        fnmatch.fnmatch(path, pattern)
        or fnmatch.fnmatch(basename, pattern)
        or (pattern.endswith("/**") and path.startswith(pattern[:-3].rstrip("/") + "/"))
        for pattern in patterns
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    seed = manifest["seed"]
    patterns = manifest["alwaysExclude"]
    candidates = tracked_paths() if seed["trackedSource"] else []
    candidates.extend(seed.get("includeUntracked") or [])
    selected: list[str] = []
    seen: set[str] = set()
    total = 0
    for relative in candidates:
        if relative in seen or excluded(relative, patterns):
            continue
        source = ROOT / relative
        if not source.is_file() or source.is_symlink():
            continue
        resolved = source.resolve()
        if ROOT not in resolved.parents:
            raise RuntimeError(f"seed path escapes /local: {relative}")
        size = source.stat().st_size
        total += size
        if total > int(seed["maximumArchiveBytes"]):
            raise RuntimeError("seed exceeds maximumArchiveBytes")
        seen.add(relative)
        selected.append(relative)

    SEED_DIR.mkdir(parents=True, exist_ok=True)
    with tarfile.open(ARCHIVE_PATH, "w", format=tarfile.PAX_FORMAT) as archive:
        for relative in sorted(selected):
            archive.add(ROOT / relative, arcname=relative, recursive=False)
    index = {
        "schema": "wasm-agent.safe-lab.seed-index.v1",
        "manifestSha256": sha256(MANIFEST_PATH),
        "archiveSha256": sha256(ARCHIVE_PATH),
        "fileCount": len(selected),
        "sourceBytes": total,
        "archiveBytes": ARCHIVE_PATH.stat().st_size,
        "paths": sorted(selected),
    }
    INDEX_PATH.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in index.items() if key != "paths"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
