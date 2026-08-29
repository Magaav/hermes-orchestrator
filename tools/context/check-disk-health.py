#!/usr/bin/env python3
"""Bounded disk-health proof and stale known-temporary cleanup."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = ROOT / "reports/context/latest/disk-health-result.json"
GIT_TEMP_PREFIXES = ("tmp_pack_", "tmp_obj_")
BUILD_TEMP_PREFIXES = ("wasm-agent-installer-", "wasm-agent-asar-", "wasm-agent-release-")
GIT_MAINTENANCE_TERMS = ("git gc", "git repack", "git pack-objects", "git index-pack", "git maintenance")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    parser.add_argument("--tmp-root", type=Path, default=Path("/tmp"), help="temporary-directory root")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="JSON report path")
    parser.add_argument("--cleanup", action="store_true", help="remove only stale known temporary artifacts")
    parser.add_argument("--stale-minutes", type=float, default=5.0)
    parser.add_argument("--warn-percent", type=float, default=75.0)
    parser.add_argument("--fail-percent", type=float, default=85.0)
    return parser.parse_args()


def active_git_maintenance() -> list[dict[str, object]]:
    active: list[dict[str, object]] = []
    proc = Path("/proc")
    if not proc.exists():
        return active
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        except (OSError, PermissionError):
            continue
        if any(term in command for term in GIT_MAINTENANCE_TERMS):
            active.append({"pid": int(entry.name), "command": command[:300]})
    return sorted(active, key=lambda item: int(item["pid"]))


def candidates(root: Path, tmp_root: Path) -> tuple[list[Path], list[Path]]:
    git_candidates: list[Path] = []
    pack_root = root / ".git" / "objects"
    if pack_root.is_dir():
        for path in pack_root.rglob("tmp_*"):
            if path.is_file() and path.name.startswith(GIT_TEMP_PREFIXES):
                git_candidates.append(path)
    build_candidates: list[Path] = []
    if tmp_root.is_dir():
        for path in tmp_root.iterdir():
            if path.is_dir() and path.name.startswith(BUILD_TEMP_PREFIXES):
                build_candidates.append(path)
    return git_candidates, build_candidates


def total_bytes(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        if path.is_file():
            total += path.stat().st_size
        elif path.is_dir():
            total += sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    return total


def main() -> int:
    args = parse_args()
    if args.stale_minutes < 1 or not 0 < args.warn_percent < args.fail_percent < 100:
        raise SystemExit("invalid thresholds: stale-minutes >= 1 and 0 < warn < fail < 100 are required")
    root = args.root.resolve()
    tmp_root = args.tmp_root.resolve()
    if not (root / ".git").is_dir():
        raise SystemExit(f"repository .git directory missing: {root}")

    now = datetime.now(timezone.utc)
    stale_before = now.timestamp() - args.stale_minutes * 60
    active = active_git_maintenance()
    git_paths, build_paths = candidates(root, tmp_root)
    stale_git_paths = [path for path in git_paths if path.stat().st_mtime < stale_before]
    stale_build_paths = [path for path in build_paths if path.stat().st_mtime < stale_before]
    before = {"gitFiles": len(git_paths), "gitBytes": total_bytes(git_paths), "buildDirs": len(build_paths), "buildBytes": total_bytes(build_paths)}
    removed = {"gitFiles": 0, "gitBytes": 0, "buildDirs": 0, "buildBytes": 0}

    if args.cleanup:
        if not active:
            for path in stale_git_paths:
                size = path.stat().st_size
                path.unlink()
                removed["gitFiles"] += 1
                removed["gitBytes"] += size
        for path in stale_build_paths:
            size = total_bytes([path])
            shutil.rmtree(path)
            removed["buildDirs"] += 1
            removed["buildBytes"] += size

    git_paths, build_paths = candidates(root, tmp_root)
    remaining = {"gitFiles": len(git_paths), "gitBytes": total_bytes(git_paths), "buildDirs": len(build_paths), "buildBytes": total_bytes(build_paths)}
    usage = shutil.disk_usage(root)
    used_percent = round((usage.total - usage.free) * 100 / usage.total, 2)
    failure_reasons = []
    if used_percent >= args.fail_percent:
        failure_reasons.append("disk_usage_above_fail_threshold")
    if remaining["gitFiles"] or remaining["buildDirs"]:
        failure_reasons.append("stale_temporary_artifacts_remain")
    classification = "disk_health_fail" if failure_reasons else ("disk_health_warn" if used_percent >= args.warn_percent else "disk_health_pass")
    report = {
        "status": "fail" if failure_reasons else "pass",
        "classification": classification,
        "checkedAt": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "root": str(root),
        "disk": {"usedPercent": used_percent, "freeBytes": usage.free, "warnPercent": args.warn_percent, "failPercent": args.fail_percent},
        "cleanupAgeMinutes": args.stale_minutes,
        "cleanupRequested": args.cleanup,
        "activeGitMaintenance": active,
        "before": before,
        "removed": removed,
        "remaining": remaining,
        "failureReasons": failure_reasons,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("DISK_HEALTH/1 " + json.dumps({"s": report["status"], "c": classification, "use": used_percent, "free": usage.free, "git": remaining["gitBytes"], "tmp": remaining["buildBytes"]}, separators=(",", ":")))
    return 1 if failure_reasons else 0


if __name__ == "__main__":
    sys.exit(main())
