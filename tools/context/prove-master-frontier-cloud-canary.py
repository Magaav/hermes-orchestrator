#!/usr/bin/env python3
"""Read-only public production canary for the Master:frontier host boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse


ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "https://wa.colmeio.com"
REPORT_PATH = ROOT / "reports/context/latest/master-frontier-cloud-canary.json"
MAX_BODY_BYTES = 128 * 1024
PROBES = (
    ("health_boundary", "/health", "json"),
    ("public_config", "/config.json", "json"),
    ("anonymous_session", "/auth/session", "json"),
    ("native_shell", "/home?native=electron", "html"),
)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _failure(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _local_urls(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for child in value.values():
            found.extend(_local_urls(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_local_urls(child))
    elif isinstance(value, str) and urlparse(value).hostname in LOCAL_HOSTS:
        found.append(value)
    return found


def fetch(url: str, timeout_sec: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "wasm-agent-mf-cloud-canary/1"})
    started = time.monotonic()
    try:
        response = urllib.request.urlopen(request, timeout=timeout_sec)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        body = response.read(MAX_BODY_BYTES + 1)
        final_url = response.geturl()
        status = int(response.status)
        content_type = str(response.headers.get("Content-Type") or "")
    if len(body) > MAX_BODY_BYTES:
        raise ValueError("response_too_large")
    return {
        "status": status,
        "finalUrl": final_url,
        "contentType": content_type,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "durationMs": int((time.monotonic() - started) * 1000),
        "body": body,
    }


def inspect_probe(name: str, result: dict[str, Any], body_kind: str) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    final = urlparse(str(result["finalUrl"]))
    if final.scheme != "https" or final.hostname != "wa.colmeio.com":
        failures.append(_failure("production_origin_escape", "probe left the allowlisted HTTPS production host"))
    body = result.pop("body")
    payload: Any = None
    if body_kind == "json":
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            failures.append(_failure("invalid_json", "expected a JSON response"))
            return failures
    if name == "health_boundary":
        error = payload.get("error") if isinstance(payload, dict) else None
        if result["status"] != 401 or not isinstance(error, dict) or error.get("code") != "auth_required":
            failures.append(_failure("health_boundary_open", "anonymous health must enforce auth_required"))
    elif name == "anonymous_session":
        if result["status"] != 200 or not isinstance(payload, dict) or payload.get("authenticated") is not False or payload.get("user") is not None:
            failures.append(_failure("anonymous_session_invalid", "anonymous session boundary returned an unexpected identity"))
    elif name == "public_config":
        if result["status"] != 200 or not isinstance(payload, dict):
            failures.append(_failure("public_config_unavailable", "public config must return an object"))
        else:
            local_urls = sorted(set(_local_urls(payload)))
            result["projection"] = {
                "appId": payload.get("appId"),
                "deploymentMode": (payload.get("deployment") or {}).get("mode"),
                "googleAuthConfigured": (payload.get("auth") or {}).get("googleClientIdConfigured"),
                "localOriginCount": len(local_urls),
            }
            if local_urls:
                failures.append(_failure("local_origin_exposed", "public config exposes a localhost or loopback URL"))
            if (payload.get("deployment") or {}).get("mode") != "cloud":
                failures.append(_failure("deployment_not_cloud", "public config does not declare cloud deployment mode"))
            if (payload.get("auth") or {}).get("googleClientIdConfigured") is not True:
                failures.append(_failure("production_auth_unconfigured", "Google authentication is not configured"))
    elif name == "native_shell":
        text = body.decode("utf-8", errors="replace").lower()
        if result["status"] != 200 or "<!doctype html" not in text or "wasm agent" not in text:
            failures.append(_failure("native_shell_unavailable", "native Electron route did not return the WASM Agent shell"))
    return failures


def run_canary(
    report_path: Path = REPORT_PATH,
    *,
    timeout_sec: float = 15.0,
    fetcher: Callable[[str, float], dict[str, Any]] = fetch,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for name, path, body_kind in PROBES:
        try:
            result = fetcher(urljoin(ORIGIN, path), timeout_sec)
            failures = inspect_probe(name, result, body_kind)
        except Exception as exc:
            result = {"durationMs": 0}
            failures = [_failure("probe_failed", f"{type(exc).__name__}: {exc}")]
        http_status = result.pop("status", None)
        results.append({
            "name": name,
            "status": "fail" if failures else "pass",
            "httpStatus": http_status,
            **result,
            "failures": failures,
        })
    failed = [item for item in results if item["status"] != "pass"]
    report = {
        "schema": "hermes.context.master_frontier.cloud_canary.v1",
        "ok": not failed,
        "checkedAt": utc_now(),
        "origin": ORIGIN,
        "mutation": "none",
        "authenticatedAgentTurn": "not_proven",
        "results": results,
        "failed": [failure for item in failed for failure in item["failures"]],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-sec", type=float, default=15.0)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = run_canary(args.report, timeout_sec=args.timeout_sec)
    summary = {
        "schema": "MF_CLOUD/1",
        "ok": report["ok"],
        "passed": sum(item["status"] == "pass" for item in report["results"]),
        "checked": len(report["results"]),
        "failed": [item["code"] for item in report["failed"]],
        "artifact": str(args.report.relative_to(ROOT)) if args.report.is_relative_to(ROOT) else str(args.report),
    }
    print(json.dumps(summary, separators=(",", ":")))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
