#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path("/local")
DEFAULT_IMAGE = os.getenv("HORC_APP_IMAGE", "debian:bookworm-slim")
DEFAULT_MEMORY = os.getenv("HORC_APP_MEMORY", "512m")
DEFAULT_CPUS = os.getenv("HORC_APP_CPUS", "1")
DEFAULT_PIDS = os.getenv("HORC_APP_PIDS_LIMIT", "128")


class AppManagerError(RuntimeError):
    pass


@dataclass(frozen=True)
class AppSpec:
    key: str
    aliases: tuple[str, ...]
    container: str
    root: Path
    bin_path: Path
    build_cwd: Path
    build_command: list[str]
    build_inputs: tuple[Path, ...]
    command: list[str]
    env_file: Path | None
    env: dict[str, str]
    mounts: tuple[tuple[Path, Path, str], ...]
    port: int
    container_port: int
    health_path: str


APPS: tuple[AppSpec, ...] = (
    AppSpec(
        key="zaiaecainelli",
        aliases=("zaiaecainelli", "zaiaecanelli", "zaia", "fernanda"),
        container="horc-app-zaiaecainelli",
        root=ROOT / "projects" / "zaiaecainelli",
        bin_path=ROOT / "projects" / "zaiaecainelli" / "backend" / "bin" / "zaiaecainelli",
        build_cwd=ROOT / "projects" / "zaiaecainelli" / "backend",
        build_command=["go", "build", "-o", "/local/projects/zaiaecainelli/backend/bin/zaiaecainelli", "./cmd/server"],
        build_inputs=(
            ROOT / "projects" / "zaiaecainelli" / "backend" / "cmd",
            ROOT / "projects" / "zaiaecainelli" / "backend" / "internal",
            ROOT / "projects" / "zaiaecainelli" / "backend" / "go.mod",
            ROOT / "projects" / "zaiaecainelli" / "backend" / "go.sum",
        ),
        command=[
            "/local/projects/zaiaecainelli/backend/bin/zaiaecainelli",
            "-env",
            "/local/projects/zaiaecainelli/app.env",
            "-command",
            "serve",
        ],
        env_file=None,
        env={
            "HTTP_BIND": "0.0.0.0",
            "HTTP_PORT": "18081",
            "STAGE_HMR_ENABLED": "false",
        },
        mounts=(
            (ROOT / "projects" / "zaiaecainelli" / "app.env", ROOT / "projects" / "zaiaecainelli" / "app.env", "ro"),
            (ROOT / "projects" / "zaiaecainelli" / "backend" / "bin", ROOT / "projects" / "zaiaecainelli" / "backend" / "bin", "ro"),
            (ROOT / "projects" / "zaiaecainelli" / "backend" / "internal" / "migrations", ROOT / "projects" / "zaiaecainelli" / "backend" / "internal" / "migrations", "ro"),
            (ROOT / "projects" / "zaiaecainelli" / "frontend" / "dist", ROOT / "projects" / "zaiaecainelli" / "frontend" / "dist", "ro"),
            (ROOT / "projects" / "zaiaecainelli" / "stages", ROOT / "projects" / "zaiaecainelli" / "stages", "ro"),
            (ROOT / "projects" / "zaiaecainelli" / "data", ROOT / "projects" / "zaiaecainelli" / "data", "rw"),
        ),
        port=18081,
        container_port=18081,
        health_path="/healthz",
    ),
    AppSpec(
        key="fredericochaves",
        aliases=("fredericochaves", "frederico", "fred", "dci"),
        container="horc-app-fredericochaves",
        root=ROOT / "projects" / "paracelsus" / "apps" / "dci",
        bin_path=ROOT / "projects" / "paracelsus" / "apps" / "dci" / "bin" / "dci",
        build_cwd=ROOT / "projects" / "paracelsus" / "apps" / "dci",
        build_command=["go", "build", "-o", "bin/dci", "./cmd/server"],
        build_inputs=(
            ROOT / "projects" / "paracelsus" / "apps" / "dci" / "cmd",
            ROOT / "projects" / "paracelsus" / "apps" / "dci" / "internal",
            ROOT / "projects" / "paracelsus" / "apps" / "dci" / "web" / "templates",
            ROOT / "projects" / "paracelsus" / "apps" / "dci" / "go.mod",
            ROOT / "projects" / "paracelsus" / "apps" / "dci" / "go.sum",
        ),
        command=["/local/projects/paracelsus/apps/dci/bin/dci"],
        env_file=None,
        env={
            "APP_NAME": "dci",
            "APP_DISPLAY_NAME": "DCI",
            "APP_OWNER_DISPLAY_NAME": "Dr. Frederico Chaves",
            "APP_PUBLIC_HOST": "localhost:18082",
            "APP_PUBLIC_ORIGIN": "http://localhost:18082",
            "APP_WORKSPACE_DIR": "/local/projects/paracelsus/apps/dci",
            "APP_BIN_PATH": "/local/projects/paracelsus/apps/dci/bin/dci",
            "APP_DATA_DIR": "/local/datas/paracelsus",
            "APP_DB_PATH": "/local/datas/paracelsus/dci.db",
            "APP_RUN_DIR": "/local/run",
            "APP_LISTEN_MODE": "tcp",
            "APP_ADDR": "0.0.0.0:8080",
            "APP_HMR": "false",
        },
        mounts=(
            (ROOT / "projects" / "paracelsus" / "apps" / "dci" / "bin", ROOT / "projects" / "paracelsus" / "apps" / "dci" / "bin", "ro"),
            (ROOT / "projects" / "paracelsus" / "apps" / "dci" / "web", ROOT / "projects" / "paracelsus" / "apps" / "dci" / "web", "ro"),
            (ROOT / "datas" / "paracelsus", ROOT / "datas" / "paracelsus", "rw"),
            (ROOT / "run", ROOT / "run", "rw"),
        ),
        port=18082,
        container_port=8080,
        health_path="/health",
    ),
)


def run(argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, text=True, capture_output=True, check=check)


def docker_available() -> None:
    if shutil.which("docker") is None:
        raise AppManagerError("docker CLI not found on host")


def resolve_app(name: str) -> AppSpec:
    normalized = name.strip().lower()
    for spec in APPS:
        if normalized in spec.aliases:
            return spec
    known = ", ".join(spec.key for spec in APPS)
    raise AppManagerError(f"unknown app {name!r}; known apps: {known}")


def docker_state(container: str) -> dict[str, Any]:
    proc = run(["docker", "inspect", container], check=False)
    if proc.returncode != 0:
        return {"exists": False, "running": False, "status": "missing"}
    try:
        data = json.loads(proc.stdout)[0]
    except (json.JSONDecodeError, IndexError, KeyError):
        return {"exists": True, "running": False, "status": "unknown"}
    state = data.get("State") if isinstance(data.get("State"), dict) else {}
    return {
        "exists": True,
        "running": bool(state.get("Running")),
        "status": str(state.get("Status") or "unknown"),
        "container_id": str(data.get("Id") or "")[:12],
    }


def ensure_path(path: Path, *, kind: str) -> None:
    if kind == "file" and not path.is_file():
        raise AppManagerError(f"required file missing: {path}")
    if kind == "dir":
        path.mkdir(parents=True, exist_ok=True)


def newest_mtime(paths: tuple[Path, ...]) -> float:
    newest = 0.0
    for path in paths:
        if not path.exists():
            continue
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
            continue
        for child in path.rglob("*"):
            if child.is_file():
                newest = max(newest, child.stat().st_mtime)
    return newest


def ensure_fresh_binary(spec: AppSpec) -> dict[str, Any]:
    if not spec.bin_path.exists():
        reason = "missing"
    elif newest_mtime(spec.build_inputs) > spec.bin_path.stat().st_mtime:
        reason = "stale"
    else:
        return {"rebuilt": False, "reason": "fresh"}
    if shutil.which("go") is None:
        raise AppManagerError(f"app binary is {reason} and go is not installed on host: {spec.bin_path}")
    spec.bin_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(spec.build_command, cwd=str(spec.build_cwd), text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip()
        raise AppManagerError(f"go build failed for {spec.key}: {message}")
    return {"rebuilt": True, "reason": reason}


def base_docker_run(spec: AppSpec) -> list[str]:
    ensure_path(spec.bin_path, kind="file")
    if spec.env_file is not None:
        ensure_path(spec.env_file, kind="file")
    for host, _container, mode in spec.mounts:
        if mode == "rw":
            ensure_path(host, kind="dir")
        elif not host.exists():
            raise AppManagerError(f"required mount path missing: {host}")
    cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        spec.container,
        "--restart",
        "unless-stopped",
        "--memory",
        DEFAULT_MEMORY,
        "--cpus",
        DEFAULT_CPUS,
        "--pids-limit",
        DEFAULT_PIDS,
        "--network",
        "bridge",
        "-p",
        f"127.0.0.1:{spec.port}:{spec.container_port}",
        "--workdir",
        str(spec.root),
    ]
    if spec.env_file is not None:
        cmd.extend(["--env-file", str(spec.env_file)])
    for key, value in spec.env.items():
        cmd.extend(["--env", f"{key}={value}"])
    for host, container, mode in spec.mounts:
        cmd.extend(["--mount", f"type=bind,src={host},dst={container},readonly" if mode == "ro" else f"type=bind,src={host},dst={container}"])
    cmd.append(DEFAULT_IMAGE)
    cmd.extend(spec.command)
    return cmd


def action_start(spec: AppSpec) -> dict[str, Any]:
    docker_available()
    state = docker_state(spec.container)
    if state.get("running"):
        return {"app": spec.key, "action": "start", "result": "already-running", **state, "url": f"http://127.0.0.1:{spec.port}", "build": {"rebuilt": False, "reason": "already-running"}}
    if state.get("exists"):
        run(["docker", "rm", "-f", spec.container], check=False)
    build = ensure_fresh_binary(spec)
    proc = run(base_docker_run(spec))
    return {
        "app": spec.key,
        "action": "start",
        "result": "started",
        "container": spec.container,
        "container_id": proc.stdout.strip()[:12],
        "url": f"http://127.0.0.1:{spec.port}",
        "limits": {"memory": DEFAULT_MEMORY, "cpus": DEFAULT_CPUS, "pids": DEFAULT_PIDS},
        "build": build,
    }


def action_stop(spec: AppSpec) -> dict[str, Any]:
    docker_available()
    state = docker_state(spec.container)
    if not state.get("exists"):
        return {"app": spec.key, "action": "stop", "result": "already-stopped", **state}
    run(["docker", "rm", "-f", spec.container], check=False)
    return {"app": spec.key, "action": "stop", "result": "stopped", "container": spec.container}


def action_restart(spec: AppSpec) -> dict[str, Any]:
    stop = action_stop(spec)
    start = action_start(spec)
    return {"app": spec.key, "action": "restart", "result": start.get("result"), "stop": stop, "start": start}


def action_status(spec: AppSpec) -> dict[str, Any]:
    docker_available()
    state = docker_state(spec.container)
    payload = {"app": spec.key, "action": "status", "container": spec.container, "url": f"http://127.0.0.1:{spec.port}", **state}
    if state.get("running"):
        if shutil.which("curl"):
            health = run(["curl", "-fsS", f"http://127.0.0.1:{spec.port}{spec.health_path}"], check=False)
            payload["health_check_exit"] = health.returncode
        else:
            payload["health_check_exit"] = None
            payload["health_check_skipped"] = "curl_missing"
    return payload


def action_logs(spec: AppSpec, lines: int) -> dict[str, Any]:
    docker_available()
    state = docker_state(spec.container)
    if not state.get("exists"):
        raise AppManagerError(f"container not found: {spec.container}")
    proc = run(["docker", "logs", "--tail", str(lines), spec.container], check=False)
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return {"app": spec.key, "action": "logs", "result": "printed", "lines": lines, "exit_code": proc.returncode}


def dispatch(spec: AppSpec, action: str, lines: int) -> dict[str, Any]:
    if action == "start":
        return action_start(spec)
    if action == "stop":
        return action_stop(spec)
    if action == "restart":
        return action_restart(spec)
    if action == "status":
        return action_status(spec)
    if action == "logs":
        return action_logs(spec, lines)
    raise AppManagerError(f"unsupported action: {action}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage local app containers")
    parser.add_argument("app", help="App name: zaiaecainelli or fredericochaves")
    parser.add_argument("action", choices=["start", "stop", "restart", "status", "logs"])
    parser.add_argument("--lines", type=int, default=80)
    args = parser.parse_args(argv)
    try:
        result = dispatch(resolve_app(args.app), args.action, args.lines)
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or str(exc)).strip()
        print(json.dumps({"ok": False, "error": "command_failed", "message": message, "exit_code": exc.returncode}, sort_keys=True), file=sys.stderr)
        return exc.returncode or 1
    except AppManagerError as exc:
        print(json.dumps({"ok": False, "error": "app_manager_error", "message": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
