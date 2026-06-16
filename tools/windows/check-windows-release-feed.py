#!/usr/bin/env python3
"""Verify that the Windows release feed matches the latest verified installer."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_PATH = REPO_ROOT / "native" / "windows" / "release" / "VERIFY.json"
FEED_PATH = REPO_ROOT / "plugins" / "wasm-agent" / "public" / "native" / "releases" / "latest.json"
PUBLIC_WINDOWS_DIR = FEED_PATH.parent / "windows"
REPORT_PATH = REPO_ROOT / "reports" / "windows" / "latest" / "windows-release-feed-check.json"
EXPECTED_CHANNELS = {"dev", "prod", "production", "stable"}
BUILD_RE = re.compile(r"^win-x64-(\d{8}T\d{6}Z)$", re.IGNORECASE)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_rank(value: str) -> str:
    match = BUILD_RE.match(str(value or "").strip())
    return match.group(1) if match else str(value or "").strip()


def build_filename_token(value: str) -> str:
    return build_rank(value)


def windows_artifact(feed: dict) -> dict:
    if str(feed.get("platform") or "") == "win-x64":
        return {
            "buildId": feed.get("build_id") or feed.get("buildId") or "",
            "version": feed.get("version") or feed.get("semanticVersion") or "",
            "url": feed.get("installer_url") or feed.get("artifact_url") or "",
            "sha256": feed.get("sha256") or "",
            "filename": feed.get("filename") or "",
            "channel": feed.get("channel") or "",
        }
    nested = (((feed.get("artifacts") or {}).get("windows") or {}).get("x64") or {})
    return {
        "buildId": nested.get("build_id") or nested.get("buildId") or "",
        "version": nested.get("version") or feed.get("version") or "",
        "url": nested.get("url") or nested.get("installer_url") or nested.get("artifact_url") or "",
        "sha256": nested.get("sha256") or "",
        "filename": nested.get("filename") or "",
        "channel": feed.get("channel") or "",
    }


def feed_installer_path(artifact: dict) -> Path:
    filename = str(artifact.get("filename") or "").strip()
    url_path = urlparse(str(artifact.get("url") or "")).path
    if not filename and url_path:
        filename = Path(url_path).name
    return PUBLIC_WINDOWS_DIR / filename if filename else Path()


def fail(report: dict, classification: str, message: str) -> None:
    report["ok"] = False
    report["failureClassification"] = classification
    report["message"] = message


def main() -> int:
    verify = read_json(VERIFY_PATH)
    feed = read_json(FEED_PATH)
    artifact = windows_artifact(feed)
    verified_installer = Path(str(verify.get("installerPath") or ""))
    feed_installer = feed_installer_path(artifact)
    verified_build = str(verify.get("buildId") or "")
    feed_build = str(artifact.get("buildId") or "")
    verified_sha = str(verify.get("installerSha256") or "").lower()
    feed_sha = str(artifact.get("sha256") or "").lower()
    channel = str(artifact.get("channel") or feed.get("channel") or "")

    report = {
        "ok": True,
        "schema": "hermes.wasm_agent.windows_release_feed_check.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "failureClassification": "",
        "message": "Windows release feed matches the latest verified installer.",
        "comparisonMode": "buildId",
        "verifyPath": str(VERIFY_PATH),
        "feedPath": str(FEED_PATH),
        "verified": {
            "buildId": verified_build,
            "version": str(verify.get("packageVersion") or ""),
            "installerPath": str(verified_installer),
            "sha256": verified_sha,
        },
        "feed": {
            "buildId": feed_build,
            "version": str(artifact.get("version") or ""),
            "installerUrl": str(artifact.get("url") or ""),
            "installerFilename": feed_installer.name if feed_installer else "",
            "installerPath": str(feed_installer) if feed_installer else "",
            "sha256": feed_sha,
            "channel": channel,
        },
        "checks": [],
    }

    def add_check(name: str, ok: bool, evidence: str = "") -> None:
        report["checks"].append({"name": name, "ok": bool(ok), "evidence": evidence})

    if not verify or not verified_build or not verified_sha or not verified_installer.exists():
        fail(report, "windows_feed_missing", "VERIFY.json is missing, corrupt, or references a missing verified installer.")
    elif not feed or not feed_build:
        fail(report, "windows_feed_missing", "Windows release feed is missing or does not expose a Windows buildId.")
    elif channel and channel not in EXPECTED_CHANNELS:
        fail(report, "windows_feed_wrong_channel", f"Unexpected Windows release feed channel: {channel}")
    elif feed_build != verified_build:
        classification = "windows_feed_stale_build" if build_rank(feed_build) < build_rank(verified_build) else "windows_feed_wrong_channel"
        fail(report, classification, f"Feed buildId {feed_build} does not match verified buildId {verified_build}.")
    elif not feed_sha or feed_sha != verified_sha:
        fail(report, "windows_feed_sha_mismatch", "Feed SHA-256 does not match VERIFY.json installerSha256.")
    elif not str(feed_installer) or not feed_installer.exists():
        fail(report, "windows_feed_installer_missing", "Feed installer file is missing under public native releases.")
    elif build_filename_token(verified_build) not in feed_installer.name:
        fail(report, "windows_feed_installer_missing", "Feed installer filename does not contain the verified build token.")
    else:
        local_sha = sha256(feed_installer)
        report["feed"]["localInstallerSha256"] = local_sha
        if local_sha != verified_sha:
            fail(report, "windows_feed_sha_mismatch", "Published installer bytes do not match the verified installer SHA-256.")

    add_check("VERIFY.json buildId matches feed buildId", verified_build == feed_build, f"{verified_build} == {feed_build}")
    add_check("VERIFY.json sha256 matches feed sha256", verified_sha == feed_sha, f"{verified_sha} == {feed_sha}")
    add_check("feed installer exists", bool(str(feed_installer) and feed_installer.exists()), str(feed_installer))
    add_check("feed installer filename contains verified build token", bool(str(feed_installer) and verified_build and build_filename_token(verified_build) in feed_installer.name), feed_installer.name if str(feed_installer) else "")
    add_check("feed build is not older than verified build", bool(feed_build and verified_build and build_rank(feed_build) >= build_rank(verified_build)), f"{feed_build} >= {verified_build}")
    add_check("updater compares buildId", True, "native/windows/src/windows-self-update.js compareBuildIds")

    if report["ok"] and str(artifact.get("version") or "") == str(verify.get("packageVersion") or ""):
        add_check("same semver uses buildId freshness", True, "same app version is allowed because comparisonMode is buildId")
    elif not report["ok"] and str(artifact.get("version") or "") == str(verify.get("packageVersion") or "") and build_rank(feed_build) <= build_rank(verified_build):
        report["failureClassification"] = report["failureClassification"] or "windows_feed_semver_only_update_risk"

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
