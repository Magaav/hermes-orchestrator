#!/usr/bin/env python3
"""Package the installed Claude Code binary into an immutable credential-free volume."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTENSION = Path("/home/ubuntu/.vscode-server/extensions/anthropic.claude-code-2.1.207-linux-arm64")
BINARY = EXTENSION / "resources/native-binary/claude"
RUNNER = ROOT / "labs/wasm-agent/claude-code-live-runner.py"
VOLUME = "wasm-agent-adapter-claude-code-2-1-207-v1"
IMAGE = "wasm-agent-frontier:latest"
STAGING = ROOT / "labs/wasm-agent/staging/claude-code-adapter.tar"
REPORT = ROOT / "reports/context/latest/claude-code-adapter-package-result.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def preflight() -> None:
    completed = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "10000:10000", "-v", f"{VOLUME}:/adapter:ro", "--entrypoint", "/adapter/claude", IMAGE, "--version"],
        capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0 or "2.1.207 (Claude Code)" not in completed.stdout:
        raise SystemExit(completed.stderr or "packaged Claude Code version preflight failed")


def main() -> int:
    files = [(RUNNER, Path("claude-code-live-runner.py")), (BINARY, Path("claude")), (EXTENSION / "package.json", Path("extension-package.json"))]
    if not all(path.is_file() for path, _relative in files):
        raise SystemExit("installed Claude Code distribution is incomplete")
    receipts = [{"path": str(relative), "sha256": sha256(path), "bytes": path.stat().st_size} for path, relative in files]
    artifact_sha = hashlib.sha256(json.dumps(receipts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    manifest = {
        "schema": "wasm-agent.safe-lab.adapter-package.v1", "adapter": "claude-code", "version": "2.1.207",
        "volume": VOLUME, "artifactSha256": artifact_sha, "files": receipts,
        "source": "installed Claude Code native binary plus safe-lab runner",
        "secretsIncluded": False, "runtimeStateIncluded": False, "claudeConfigIncluded": False,
    }
    created = subprocess.run(["docker", "volume", "create", VOLUME], capture_output=True, text=True, check=False)
    if created.returncode != 0:
        raise SystemExit(created.stderr)
    existing = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "-v", f"{VOLUME}:/adapter:ro", "--entrypoint", "cat", IMAGE, "/adapter/adapter-package.json"],
        capture_output=True, text=True, check=False,
    )
    if existing.returncode == 0:
        receipt = json.loads(existing.stdout)
        if receipt.get("artifactSha256") != artifact_sha:
            raise SystemExit(f"refusing to overwrite changed Claude Code artifact in {VOLUME}")
        preflight(); receipt["preflightVersionPassed"] = True
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt, indent=2)); return 0
    emptiness = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "0", "-v", f"{VOLUME}:/adapter", "--entrypoint", "python3", IMAGE, "-c", "import os; raise SystemExit(0 if not os.listdir('/adapter') else 3)"],
        capture_output=True, text=True, check=False,
    )
    if emptiness.returncode != 0:
        raise SystemExit(f"refusing to overwrite non-empty adapter volume without matching receipt: {VOLUME}")
    started = time.monotonic(); STAGING.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest, indent=2) + "\n"
    with tarfile.open(STAGING, mode="w") as archive:
        for path, relative in files:
            archive.add(path, arcname=str(relative), recursive=False)
        info = tarfile.TarInfo("adapter-package.json"); encoded = payload.encode(); info.size = len(encoded); info.mode = 0o444
        archive.addfile(info, io.BytesIO(encoded))
    archive_sha = sha256(STAGING)
    with STAGING.open("rb") as handle:
        imported = subprocess.run(
            ["docker", "run", "--rm", "-i", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "0", "-v", f"{VOLUME}:/adapter", "--entrypoint", "tar", IMAGE, "--no-same-owner", "--no-same-permissions", "-xf", "-", "-C", "/adapter"],
            stdin=handle, capture_output=True, check=False,
        )
    STAGING.unlink(missing_ok=True)
    if imported.returncode != 0:
        raise SystemExit(imported.stderr.decode("utf-8", "replace"))
    preflight()
    report = {**manifest, "archiveSha256": archive_sha, "preflightVersionPassed": True, "durationMs": round((time.monotonic() - started) * 1000)}
    REPORT.parent.mkdir(parents=True, exist_ok=True); REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
