#!/usr/bin/env python3
"""Bootstrap Camofox defaults from .env flags.

Goal:
- Treat BROWSER_CAMOFOX=1 as an intent flag.
- If enabled and CAMOFOX_URL is missing, set a deterministic default URL.
- Optionally ensure a host-level Camofox Docker service exists.

This script is designed to be safe/idempotent:
- Never rotates or mutates unrelated env keys.
- Service bring-up is best-effort (does not hard-fail by default).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Tuple


VALID_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _read_env(path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if not path.exists():
        return env
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not VALID_ENV_KEY_RE.fullmatch(key):
            continue
        value = value.strip()
        if len(value) >= 2 and (
            (value.startswith('"') and value.endswith('"'))
            or (value.startswith("'") and value.endswith("'"))
        ):
            value = value[1:-1]
        env[key] = value
    return env


def _upsert_env_value(path: Path, key: str, value: str) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")

    changed = False
    replaced = False
    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if pattern.match(raw):
            new_line = f"{key}={value}"
            if raw != new_line:
                lines[idx] = new_line
                changed = True
            replaced = True
            break

    if not replaced:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"{key}={value}")
        changed = True

    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def _run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail or f"command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc


def _docker_has_container(name: str) -> bool:
    proc = _run(
        ["docker", "ps", "-a", "--filter", f"name=^/{name}$", "--format", "{{.ID}}"],
        check=False,
    )
    return bool((proc.stdout or "").strip())


def _docker_is_running(name: str) -> bool:
    proc = _run(
        ["docker", "ps", "--filter", f"name=^/{name}$", "--format", "{{.ID}}"],
        check=False,
    )
    return bool((proc.stdout or "").strip())


def _docker_has_image(image: str) -> bool:
    proc = _run(["docker", "image", "inspect", image], check=False)
    return proc.returncode == 0


def _resolve_build_context(explicit: str) -> Path | None:
    raw = str(explicit or "").strip()
    if raw:
        path = Path(raw).expanduser()
        if path.exists() and (path / "Dockerfile").exists():
            return path
        return None

    candidates = [
        Path("/local/workspace/camofox-browser"),
        Path("/local/camofox-browser"),
        Path("/opt/camofox-browser"),
    ]
    for candidate in candidates:
        if candidate.exists() and (candidate / "Dockerfile").exists():
            return candidate
    return None


def _wait_for_health(url: str, timeout_sec: int) -> Tuple[bool, str]:
    try:
        import urllib.request
    except Exception as exc:
        return False, f"urllib unavailable: {exc}"

    health_url = f"{url.rstrip('/')}/health"
    deadline = time.time() + max(5, int(timeout_sec))
    last_err = ""
    while time.time() < deadline:
        try:
            req = urllib.request.Request(health_url, method="GET")
            with urllib.request.urlopen(req, timeout=3.0) as resp:  # nosec B310
                status = int(getattr(resp, "status", 0) or 0)
                if 200 <= status < 300:
                    return True, f"healthy ({status})"
                last_err = f"unexpected HTTP status {status}"
        except Exception as exc:
            last_err = str(exc)
        time.sleep(1.5)
    return False, last_err or "health timeout"


def _ensure_camofox_service(
    *,
    service_name: str,
    image: str,
    host_port: int,
    health_url: str,
    timeout_sec: int,
    build_context: str,
) -> Dict[str, object]:
    result: Dict[str, object] = {
        "attempted": True,
        "service_name": service_name,
        "image": image,
        "host_port": host_port,
        "running": False,
        "created": False,
        "started": False,
        "built": False,
        "health_ok": False,
        "message": "",
    }

    if shutil.which("docker") is None:
        result["message"] = "docker CLI not found; skipping service bootstrap"
        return result

    if _docker_is_running(service_name):
        result["running"] = True
    elif _docker_has_container(service_name):
        proc = _run(["docker", "start", service_name], check=False)
        if proc.returncode == 0:
            result["started"] = True
            result["running"] = True
        else:
            result["message"] = (proc.stderr or proc.stdout or "").strip() or "failed to start existing container"
            return result
    else:
        if not _docker_has_image(image):
            context_dir = _resolve_build_context(build_context)
            if context_dir is not None:
                build_cmd = ["docker", "build", "-t", image, str(context_dir)]
                build_proc = _run(build_cmd, check=False)
                if build_proc.returncode == 0:
                    result["built"] = True
                else:
                    result["message"] = (
                        (build_proc.stderr or build_proc.stdout or "").strip()
                        or f"failed to build image {image}"
                    )
                    return result

        cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            service_name,
            "--restart",
            "unless-stopped",
            "-p",
            f"{host_port}:9377",
            "-e",
            "CAMOFOX_PORT=9377",
            image,
        ]
        proc = _run(cmd, check=False)
        if proc.returncode == 0:
            result["created"] = True
            result["running"] = True
        else:
            result["message"] = (proc.stderr or proc.stdout or "").strip() or "failed to create container"
            return result

    ok, detail = _wait_for_health(health_url, timeout_sec=timeout_sec)
    result["health_ok"] = ok
    result["message"] = detail
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap CAMOFOX_URL from BROWSER_CAMOFOX in .env")
    parser.add_argument("--env-file", required=True, help="Path to env file")
    parser.add_argument("--enable-var", default="BROWSER_CAMOFOX", help="Boolean enable env var key")
    parser.add_argument("--url-var", default="CAMOFOX_URL", help="Camofox URL env var key")
    parser.add_argument("--default-url", default="http://127.0.0.1:9377", help="Default CAMOFOX_URL when enabled")
    parser.add_argument("--ensure-service", action="store_true", help="Ensure a host Docker camofox service is running")
    parser.add_argument("--service-name", default="camofox", help="Docker container name")
    parser.add_argument("--service-image", default="camofox-browser", help="Docker image")
    parser.add_argument("--service-port", type=int, default=9377, help="Host port to publish for camofox")
    parser.add_argument(
        "--build-context",
        default="",
        help="Optional local directory containing a Dockerfile to auto-build service-image when missing",
    )
    parser.add_argument("--health-timeout-sec", type=int, default=120, help="Health wait timeout")
    parser.add_argument("--strict-service", action="store_true", help="Fail if ensure-service cannot become healthy")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    env_path = Path(str(args.env_file)).expanduser()

    if not env_path.exists():
        print(json.dumps({"ok": False, "error": f"env file not found: {env_path}"}))
        return 1

    env = _read_env(env_path)
    enabled = _is_truthy(env.get(args.enable_var, ""))

    payload: Dict[str, object] = {
        "ok": True,
        "env_file": str(env_path),
        "enabled": enabled,
        "enable_var": args.enable_var,
        "url_var": args.url_var,
        "default_url": args.default_url,
        "changed": False,
        "effective_url": str(env.get(args.url_var, "") or ""),
        "service": {
            "attempted": False,
            "message": "not requested",
        },
    }

    if not enabled:
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    effective_url = str(env.get(args.url_var, "") or "").strip()
    if not effective_url:
        changed = _upsert_env_value(env_path, args.url_var, args.default_url)
        env = _read_env(env_path)
        effective_url = str(env.get(args.url_var, "") or "").strip()
        payload["changed"] = bool(changed)

    payload["effective_url"] = effective_url

    if args.ensure_service:
        service = _ensure_camofox_service(
            service_name=str(args.service_name),
            image=str(args.service_image),
            host_port=int(args.service_port),
            health_url=effective_url or args.default_url,
            timeout_sec=int(args.health_timeout_sec),
            build_context=str(args.build_context or ""),
        )
        payload["service"] = service
        if args.strict_service and not bool(service.get("health_ok")):
            payload["ok"] = False
            print(json.dumps(payload, ensure_ascii=False))
            return 1

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
