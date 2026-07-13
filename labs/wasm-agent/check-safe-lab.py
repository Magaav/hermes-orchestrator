#!/usr/bin/env python3
"""Statically reject dangerous safe-lab manifest and Compose configuration."""

from __future__ import annotations

import json
import re
from pathlib import Path

LAB = Path(__file__).resolve().parent
MANIFEST = LAB / "migration-manifest.json"
COMPOSE = LAB / "compose.yml"
DOCKERFILE = LAB / "Dockerfile"


def main() -> int:
    errors: list[str] = []
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    compose = COMPOSE.read_text(encoding="utf-8")
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    if manifest.get("schema") != "wasm-agent.safe-lab.migration-manifest.v1":
        errors.append("unsupported migration manifest schema")
    excluded = set(manifest.get("alwaysExclude") or [])
    required_exclusions = {
        "plugins/wasm-agent/state/**", "labs/wasm-agent/private_evaluator/**",
        "**/*secret*", "**/*.db", "**/*.sqlite3", "**/browser/**",
    }
    if not required_exclusions <= excluded:
        errors.append(f"missing required exclusions: {sorted(required_exclusions - excluded)}")
    forbidden_text = ("/var/run/docker.sock", "/run/containerd/containerd.sock", "privileged: true", "network_mode: host", "pid: host")
    for value in forbidden_text:
        if value in compose:
            errors.append(f"compose contains forbidden authority: {value}")
    if re.search(r"(?:^|\s)-\s*/local:/local(?::\w+)?\s*$", compose, re.MULTILINE):
        errors.append("compose bind-mounts host /local")
    for service in ("seed", "canary", "frontier"):
        match = re.search(rf"^  {service}:\n(?P<body>.*?)(?=^  \w|^volumes:)", compose, re.MULTILINE | re.DOTALL)
        body = match.group("body") if match else ""
        for requirement in ("network_mode: none", "read_only: true", "cap_drop: [\"ALL\"]", "no-new-privileges:true"):
            if requirement not in body:
                errors.append(f"{service} missing {requirement}")
    if "USER 10000:10000" not in dockerfile:
        errors.append("Dockerfile must run as the unprivileged frontier UID")
    if not re.search(r"^FROM \S+@sha256:[0-9a-f]{64}$", dockerfile, re.MULTILINE):
        errors.append("Dockerfile base image must be digest pinned")
    print(f"Safe lab static check: {'PASS' if not errors else 'FAIL'}")
    for error in errors:
        print(f"- {error}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
