#!/usr/bin/env python3
"""Package Master:frontier V5 source and runner into an immutable Docker volume."""

from __future__ import annotations

import hashlib
import argparse
import io
import json
import subprocess
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "plugins/wasm-agent/server/master_frontier"
RUNNER = ROOT / "labs/wasm-agent/master-frontier-v5-live-runner.py"
VOLUME = "wasm-agent-adapter-master-frontier-v5-20260712-direct-v4"
IMAGE = "wasm-agent-frontier:latest"
STAGING = ROOT / "labs/wasm-agent/staging/master-frontier-v5-adapter.tar"
REPORT = ROOT / "reports/context/latest/master-frontier-v5-adapter-package-result.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_files() -> list[tuple[Path, Path]]:
    owned = [SOURCE / name for name in ("__init__.py", "code_memory.py", "evidence.py", "route_contracts.py")]
    owned.extend(sorted((SOURCE / "v5").glob("*.py")))
    files = [(RUNNER, Path("master-frontier-v5-live-runner.py"))]
    files.extend((path, Path("plugins/wasm-agent/server/master_frontier") / path.relative_to(SOURCE)) for path in owned)
    return files


def preflight_import(volume: str = VOLUME) -> None:
    completed = subprocess.run(
        [
            "docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--user", "10000:10000", "-v", f"{volume}:/adapter:ro",
            "--entrypoint", "python3", IMAGE, "-c",
            "import sys; sys.path.insert(0,'/adapter/plugins/wasm-agent/server'); "
            "from master_frontier.v5 import loop,trajectory; "
            "state=trajectory.new('probe','probe','hello','fixture'); "
            "outcome=loop.run('hello',{'route_id':'fixture'},state,complete=lambda *_:{'reply':'Hello'},execute=lambda *_:{}); "
            "raise SystemExit(0 if outcome.answer == 'Hello' else 4)",
        ],
        capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr or "packaged Master:frontier V5 import preflight failed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant-slot")
    parser.add_argument("--strategy")
    parser.add_argument("--volume", default=VOLUME)
    parser.add_argument("--report", default=str(REPORT))
    args = parser.parse_args()
    volume = args.volume
    report_path = Path(args.report)
    if bool(args.variant_slot) != bool(args.strategy): raise SystemExit("variant slot and strategy must be provided together")
    variant = {"schema":"wasm-agent.safe-lab.v5-variant-contract.v1","slot":args.variant_slot,"strategy":args.strategy} if args.strategy else {}
    files = source_files()
    if not RUNNER.is_file() or not any(relative == Path("plugins/wasm-agent/server/master_frontier/v5/loop.py") for _path, relative in files):
        raise SystemExit("Master:frontier V5 source or runner is missing")
    file_receipts = [{"path": str(relative), "sha256": sha256(path), "bytes": path.stat().st_size} for path, relative in files]
    artifact_sha = hashlib.sha256(json.dumps({"files":file_receipts,"variant":variant}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    manifest = {
        "schema": "wasm-agent.safe-lab.adapter-package.v1",
        "adapter": "master-frontier-v5",
        "version": f"v5-{artifact_sha[:12]}",
        "volume": volume,
        "artifactSha256": artifact_sha,
        "files": file_receipts,
        "source": "owned Master:frontier Python modules plus safe-lab runner",
        "secretsIncluded": False,
        "runtimeStateIncluded": False,
        "variant": variant,
    }
    created = subprocess.run(["docker", "volume", "create", volume], capture_output=True, text=True, check=False)
    if created.returncode != 0:
        raise SystemExit(created.stderr)
    existing = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "-v", f"{volume}:/adapter:ro", "--entrypoint", "cat", IMAGE, "/adapter/adapter-package.json"],
        capture_output=True, text=True, check=False,
    )
    if existing.returncode == 0:
        receipt = json.loads(existing.stdout)
        if receipt.get("artifactSha256") != artifact_sha:
            raise SystemExit(f"refusing to overwrite changed adapter artifact in {VOLUME}")
        preflight_import(volume)
        receipt["preflightImportPassed"] = True
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt, indent=2))
        return 0
    emptiness = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "0", "-v", f"{volume}:/adapter", "--entrypoint", "python3", IMAGE, "-c", "import os; raise SystemExit(0 if not os.listdir('/adapter') else 3)"],
        capture_output=True, text=True, check=False,
    )
    if emptiness.returncode != 0:
        raise SystemExit(f"refusing to overwrite non-empty adapter volume without matching receipt: {VOLUME}")
    started = time.monotonic()
    STAGING.parent.mkdir(parents=True, exist_ok=True)
    manifest_payload = json.dumps(manifest, indent=2) + "\n"
    with tarfile.open(STAGING, mode="w") as archive:
        for path, relative in files:
            archive.add(path, arcname=str(relative), recursive=False)
        if variant:
            variant_payload = (json.dumps(variant, indent=2) + "\n").encode()
            variant_info = tarfile.TarInfo("variant-contract.json"); variant_info.size=len(variant_payload); variant_info.mode=0o444
            archive.addfile(variant_info, io.BytesIO(variant_payload))
        info = tarfile.TarInfo("adapter-package.json")
        encoded = manifest_payload.encode()
        info.size = len(encoded); info.mode = 0o444
        archive.addfile(info, io.BytesIO(encoded))
    archive_sha = sha256(STAGING)
    with STAGING.open("rb") as handle:
        imported = subprocess.run(
            ["docker", "run", "--rm", "-i", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "0", "-v", f"{volume}:/adapter", "--entrypoint", "tar", IMAGE, "--no-same-owner", "--no-same-permissions", "-xf", "-", "-C", "/adapter"],
            stdin=handle, capture_output=True, check=False,
        )
    STAGING.unlink(missing_ok=True)
    if imported.returncode != 0:
        raise SystemExit(imported.stderr.decode("utf-8", "replace"))
    preflight_import(volume)
    report = {**manifest, "archiveSha256": archive_sha, "preflightImportPassed": True, "durationMs": round((time.monotonic() - started) * 1000)}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
