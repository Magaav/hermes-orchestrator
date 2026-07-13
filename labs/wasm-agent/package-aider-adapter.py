#!/usr/bin/env python3
"""Package official Aider into an immutable credential-free Python volume."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.86.2"
PACKAGE_SPEC = f"aider-chat=={VERSION}"
VOLUME = "wasm-agent-adapter-aider-0-86-2-v2"
IMAGE = "wasm-agent-frontier:latest"
RUNNER = ROOT / "labs/wasm-agent/aider-live-runner.py"
STAGING = ROOT / "labs/wasm-agent/staging/aider-runner.tar"
REPORT = ROOT / "reports/context/latest/aider-adapter-package-result.json"


def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, check=False, **kwargs)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_receipt() -> dict:
    script = (
        "import hashlib,json,pathlib; root=pathlib.Path('/adapter'); rows=[]; total=0; "
        "files=sorted(p for p in root.rglob('*') if p.is_file() and p.name!='adapter-package.json'); "
        "[(rows.append((str(p.relative_to(root)),p.stat().st_size,hashlib.sha256(p.read_bytes()).hexdigest())),globals().__setitem__('total',total+p.stat().st_size)) for p in files]; "
        "print(json.dumps({'fileCount':len(rows),'totalBytes':total,'treeSha256':hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest()}))"
    )
    completed = run(["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "-v", f"{VOLUME}:/adapter:ro", "--entrypoint", "python3", IMAGE, "-c", script], text=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or "adapter tree receipt failed")
    return json.loads(completed.stdout)


def freeze_sha256() -> str:
    completed = run(["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "10000:10000", "-v", f"{VOLUME}:/adapter:ro", "--entrypoint", "/adapter/venv/bin/pip", IMAGE, "freeze", "--all"], text=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or "Aider dependency freeze failed")
    return hashlib.sha256(completed.stdout.encode()).hexdigest()


def preflight() -> None:
    completed = run(["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "10000:10000", "-v", f"{VOLUME}:/adapter:ro", "--entrypoint", "/adapter/venv/bin/aider", IMAGE, "--version"], text=True)
    if completed.returncode != 0 or VERSION not in completed.stdout:
        raise RuntimeError(completed.stderr or "packaged Aider version preflight failed")


def write_receipt(receipt: dict) -> None:
    STAGING.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(receipt, indent=2) + "\n").encode()
    with tarfile.open(STAGING, mode="w") as archive:
        info = tarfile.TarInfo("adapter-package.json")
        info.size = len(payload)
        info.mode = 0o444
        archive.addfile(info, io.BytesIO(payload))
    with STAGING.open("rb") as handle:
        completed = subprocess.run(["docker", "run", "--rm", "-i", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "0", "-v", f"{VOLUME}:/adapter", "--entrypoint", "tar", IMAGE, "--no-same-owner", "--no-same-permissions", "-xf", "-", "-C", "/adapter"], stdin=handle, capture_output=True, check=False)
    STAGING.unlink(missing_ok=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode("utf-8", "replace"))


def main() -> int:
    if not RUNNER.is_file():
        raise SystemExit("Aider runner is missing")
    inspected = run(["docker", "volume", "inspect", VOLUME], text=True)
    if inspected.returncode == 0:
        existing = run(["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "-v", f"{VOLUME}:/adapter:ro", "--entrypoint", "cat", IMAGE, "/adapter/adapter-package.json"], text=True)
        if existing.returncode != 0:
            raise SystemExit(f"refusing to reuse non-empty adapter volume without receipt: {VOLUME}")
        receipt = json.loads(existing.stdout)
        if receipt.get("tree") != tree_receipt() or receipt.get("dependencyFreezeSha256") != freeze_sha256():
            raise SystemExit(f"refusing changed Aider artifact in {VOLUME}")
        preflight()
        receipt["preflightVersionPassed"] = True
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt, indent=2))
        return 0
    created = run(["docker", "volume", "create", VOLUME], text=True)
    if created.returncode != 0:
        raise SystemExit(created.stderr)
    started = time.monotonic()
    try:
        created_venv = run(["docker", "run", "--rm", "--network", "none", "--user", "0", "-v", f"{VOLUME}:/adapter", "--entrypoint", "python3", IMAGE, "-m", "venv", "/adapter/venv"], text=True)
        if created_venv.returncode != 0:
            raise RuntimeError(created_venv.stderr or "Aider venv creation failed")
        installed = run(["docker", "run", "--rm", "--network", "bridge", "--user", "0", "-v", f"{VOLUME}:/adapter", "--entrypoint", "/adapter/venv/bin/pip", IMAGE, "install", "--no-cache-dir", "--disable-pip-version-check", PACKAGE_SPEC], text=True)
        if installed.returncode != 0:
            raise RuntimeError(installed.stderr or "official Aider install failed")
        with tarfile.open(STAGING, mode="w") as archive:
            archive.add(RUNNER, arcname="aider-live-runner.py", recursive=False)
        with STAGING.open("rb") as handle:
            imported = subprocess.run(["docker", "run", "--rm", "-i", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "0", "-v", f"{VOLUME}:/adapter", "--entrypoint", "tar", IMAGE, "--no-same-owner", "--no-same-permissions", "-xf", "-", "-C", "/adapter"], stdin=handle, capture_output=True, check=False)
        STAGING.unlink(missing_ok=True)
        if imported.returncode != 0:
            raise RuntimeError(imported.stderr.decode("utf-8", "replace"))
        tree = tree_receipt()
        freeze = freeze_sha256()
        artifact_sha = hashlib.sha256(json.dumps({"version": VERSION, "runnerSha256": sha256(RUNNER), "tree": tree, "dependencyFreezeSha256": freeze}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        receipt = {
            "schema": "wasm-agent.safe-lab.adapter-package.v1", "adapter": "aider", "version": VERSION,
            "volume": VOLUME, "artifactSha256": artifact_sha, "tree": tree,
            "dependencyFreezeSha256": freeze, "runnerSha256": sha256(RUNNER),
            "source": "official aider-chat PyPI distribution in an isolated Python venv plus safe-lab runner",
            "packageSpec": PACKAGE_SPEC, "secretsIncluded": False, "runtimeStateIncluded": False,
            "aiderConfigIncluded": False, "aiderHistoryIncluded": False,
        }
        write_receipt(receipt)
        preflight()
        report = {**receipt, "preflightVersionPassed": True, "durationMs": round((time.monotonic() - started) * 1000)}
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:
        STAGING.unlink(missing_ok=True)
        run(["docker", "volume", "rm", "-f", VOLUME], text=True)
        raise SystemExit(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
