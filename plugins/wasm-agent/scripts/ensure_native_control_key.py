#!/usr/bin/env python3
"""Create or rotate the private native-control key without printing it."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets


NAME = "WASM_AGENT_NATIVE_CONTROL_KEY"
DEFAULT_ENV = Path(__file__).resolve().parents[1] / "conf" / "wa.env"


def existing_key(path: Path) -> str:
    if not path.exists():
        return ""
    prefix = f"{NAME}="
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip().strip("'\"")
    return ""


def ensure_key(path: Path, *, rotate: bool = False, value: str = "") -> str:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    prefix = f"{NAME}="
    existing = existing_key(path)
    if existing and not rotate:
        os.chmod(path, 0o600)
        return "existing"
    replacement = f"{NAME}={value or secrets.token_urlsafe(48)}"
    output: list[str] = []
    replaced = False
    for line in lines:
        if line.strip().startswith(prefix):
            if not replaced:
                output.append(replacement)
                replaced = True
            continue
        output.append(line)
    if not replaced:
        if output and output[-1].strip():
            output.append("")
        output.extend(["# Authenticates bounded native-control operator requests.", replacement])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    return "rotated" if rotate else "created"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--rotate", action="store_true")
    parser.add_argument("--sync-to", type=Path, action="append", default=[])
    args = parser.parse_args()
    source = args.env_file.expanduser().resolve()
    status = ensure_key(source, rotate=args.rotate)
    print(f"native-control key: {status}; file={args.env_file}; mode=0600; value=not-shown")
    value = existing_key(source)
    for raw_target in args.sync_to:
        target = raw_target.expanduser().resolve()
        sync_status = ensure_key(target, rotate=True, value=value)
        print(f"native-control key: synced; file={target}; mode=0600; value=not-shown; status={sync_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
