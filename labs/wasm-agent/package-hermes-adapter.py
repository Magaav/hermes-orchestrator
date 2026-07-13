#!/usr/bin/env python3
"""Copy the installed Hermes venv into an isolated Docker volume without secrets."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "hermes-agent"
VENV = SOURCE / ".venv"
VOLUME = "wasm-agent-adapter-hermes-0-17-0-v2"
IMAGE = "wasm-agent-frontier:latest"
REPORT = ROOT / "reports/context/latest/hermes-adapter-package-result.json"
STAGING = ROOT / "labs/wasm-agent/staging/hermes-adapter-venv.tar"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if not (VENV / "bin/python").exists() or not (VENV / "bin/hermes").exists():
        raise SystemExit("installed Hermes venv is missing")
    created = subprocess.run(["docker", "volume", "create", VOLUME], capture_output=True, text=True, check=False)
    if created.returncode != 0:
        raise SystemExit(created.stderr)
    emptiness = subprocess.run(
        ["docker", "run", "--rm", "--user", "0", "-v", f"{VOLUME}:/adapter", "--entrypoint", "sh", IMAGE, "-lc", "test -z \"$(find /adapter -mindepth 1 -print -quit)\""],
        capture_output=True, text=True, check=False,
    )
    if emptiness.returncode != 0:
        recovered = subprocess.run(
            ["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "-v", f"{VOLUME}:/adapter:ro", "--entrypoint", "cat", IMAGE, "/adapter/adapter-package.json"],
            capture_output=True, text=True, check=False,
        )
        if recovered.returncode != 0:
            raise SystemExit(f"refusing to overwrite non-empty adapter volume without valid receipt: {VOLUME}")
        manifest = json.loads(recovered.stdout)
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(manifest, indent=2))
        return 0
    started = time.monotonic()
    STAGING.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(STAGING, mode="w", dereference=False) as archive:
        for path in sorted(VENV.rglob("*")):
            relative = path.relative_to(VENV)
            if "__pycache__" in relative.parts or path.name.endswith((".pyc", ".pyo")):
                continue
            archive.add(path, arcname=str(Path("venv") / relative), recursive=False)
        tracked = subprocess.run(
            ["git", "ls-files", "-z"], cwd=SOURCE, check=True, capture_output=True
        ).stdout.split(b"\0")
        for raw in tracked:
            if not raw:
                continue
            relative = Path(raw.decode("utf-8"))
            path = SOURCE / relative
            if path.is_file() and not path.is_symlink():
                archive.add(path, arcname=str(Path("src") / relative), recursive=False)
    digest = sha256(STAGING)
    command = [
        "docker", "run", "--rm", "-i", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "0",
        "-v", f"{VOLUME}:/adapter", "--entrypoint", "sh", IMAGE, "-lc",
        "tar --no-same-owner --no-same-permissions -xf - -C /adapter && "
        "chmod -R a+rX /adapter && "
        "ln -sf /usr/local/bin/python3.12 /adapter/venv/bin/python && "
        "ln -sf python /adapter/venv/bin/python3 && ln -sf python /adapter/venv/bin/python3.12",
    ]
    with STAGING.open("rb") as handle:
        process = subprocess.run(command, stdin=handle, capture_output=True, check=False)
    STAGING.unlink(missing_ok=True)
    if process.returncode != 0:
        raise SystemExit(process.stderr.decode(errors="replace"))
    manifest = {
        "schema": "wasm-agent.safe-lab.adapter-package.v1",
        "adapter": "hermes",
        "version": "0.17.0",
        "volume": VOLUME,
        "archiveSha256": digest,
        "source": "hermes-agent tracked source plus .venv",
        "secretsIncluded": False,
        "runtimeStateIncluded": False,
        "durationMs": round((time.monotonic() - started) * 1000),
    }
    payload = json.dumps(manifest, indent=2) + "\n"
    subprocess.run(
        ["docker", "run", "--rm", "-i", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "0", "-v", f"{VOLUME}:/adapter", "--entrypoint", "sh", IMAGE, "-lc", "cat > /adapter/adapter-package.json"],
        input=payload, text=True, check=True,
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
