#!/usr/bin/env python3
"""Deterministic Hermes clone lifecycle manager.

This script manages Hermes orchestrator + clone nodes whose runtime
configuration is read from:
  /local/agents/envs/<clone_name>.env

Supported actions:
  - start   (idempotent spawn)
  - status
  - stop
  - delete
  - logs

Design goals:
  - No secrets in command payloads
  - Transactional spawn path (best-effort rollback on failure)
  - Deterministic filesystem layout under /local/agents/nodes/<clone_name>/
  - Per-clone management log at /local/logs/agents/<clone_name>.log

================================================================================
OPENVIKING ORCHESTRATION LAYER
================================================================================

OpenViking is a centralized memory/knowledge base service that provides:
  - Semantic search across all nodes
  - Tiered context (L0 ~100 tokens, L1 ~2k, L2 full)
  - Automatic memory extraction (6 categories)
  - Session management and continuity
  - Prefetch for intelligent context pre-loading

Architecture:
  - Server: Container `openviking` running on host, exposed at 0.0.0.0:1933
  - Host access: http://127.0.0.1:1933
  - Container access: http://host.docker.internal:1933

Per-clone configuration (in /local/agents/envs/<clone_name>.env):
  MEMORY_OPENVIKING=1           # Enable OpenViking (0 to disable)
  OPENVIKING_ENDPOINT=...       # Server URL (auto-set to host.docker.internal for clones)
  OPENVIKING_ACCOUNT=colmeio    # Tenant account (shared across nodes)
  OPENVIKING_USER=<clone_name>   # Per-node user identifier

The clone manager auto-configures OpenViking during `start` by calling
openviking_env_bootstrap.py which:
  1. Validates the provider plugin exists in hermes-agent/plugins/memory/openviking/
  2. Probes the endpoint health
  3. Updates config.yaml to set memory.provider=openviking
  4. Sets fail-open mode if endpoint is unreachable

New clones inherit OpenViking configuration automatically when MEMORY_OPENVIKING=1
is set in the clone's .env file before spawning.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


AGENTS_ROOT = Path(os.getenv("HERMES_AGENTS_ROOT", "/local/agents"))
ENVS_ROOT = Path(os.getenv("HERMES_AGENTS_ENVS_ROOT", str(AGENTS_ROOT / "envs")))
CLONES_ROOT = Path(os.getenv("HERMES_AGENTS_NODES_ROOT", str(AGENTS_ROOT / "nodes")))
LEGACY_CLONES_ROOT = Path("/local/clones")
LEGACY_AGENTS_NODES_ROOT = AGENTS_ROOT
LOG_ROOT = Path(os.getenv("HERMES_AGENTS_LOG_ROOT", "/local/logs/agents"))
LEGACY_LOG_ROOT = Path("/local/logs/clones")
REGISTRY_PATH = Path(os.getenv("HERMES_AGENTS_REGISTRY_PATH", str(AGENTS_ROOT / "registry.json")))
LEGACY_REGISTRY_PATH = LEGACY_CLONES_ROOT / "registry.json"

CANONICAL_ORCHESTRATOR_HOME = Path(
    os.getenv("HERMES_ORCHESTRATOR_HOME", str(CLONES_ROOT / "orchestrator" / ".hermes"))
)
PARENT_HERMES_HOME = CANONICAL_ORCHESTRATOR_HOME
PARENT_UV_STORE = Path(os.getenv("HERMES_PARENT_UV_STORE", str(Path.home() / ".local" / "share" / "uv")))
PARENT_WORKSPACE_ROOT = Path("/local/workspace")
LEGACY_DISCORD_PLUGIN_ROOT = PARENT_WORKSPACE_ROOT / "discord"
PARENT_WORKSPACE_BACKUP_SCRIPTS = PARENT_WORKSPACE_ROOT / "crons" / "scripts" / "backup"
SHARED_PLUGINS_ROOT = Path(os.getenv("HERMES_PLUGINS_ROOT", "/local/plugins"))
SHARED_SCRIPTS_ROOT = Path(os.getenv("HERMES_SCRIPTS_ROOT", "/local/scripts"))
SHARED_CRONS_ROOT = Path(os.getenv("HERMES_CRONS_ROOT", "/local/crons"))
SHARED_MEMORY_ROOT = Path(os.getenv("HERMES_MEMORY_ROOT", "/local/memory"))
HERMES_SOURCE_ROOT = Path(os.getenv("HERMES_SOURCE_ROOT", "/local/hermes-agent"))
HERMES_AGENT_UPSTREAM_REPO = str(
    os.getenv("HERMES_AGENT_UPSTREAM_REPO", "https://github.com/NousResearch/hermes-agent.git")
    or "https://github.com/NousResearch/hermes-agent.git"
).strip()
HERMES_AGENT_UPSTREAM_BRANCH = str(
    os.getenv("HERMES_AGENT_UPSTREAM_BRANCH", "main") or "main"
).strip() or "main"
DEFAULT_DISCORD_PLUGIN_ROOT = SHARED_PLUGINS_ROOT / "discord"
HOST_BOOTSTRAP_ENV_FILE = Path(os.getenv("HERMES_BOOTSTRAP_ENV_FILE", "/local/.env"))

DEFAULT_DOCKER_IMAGE = os.getenv("HERMES_CLONE_DOCKER_IMAGE", "ubuntu:24.04")
CONTAINER_PREFIX = "hermes-node-"
HOST_UID = os.getuid()
HOST_GID = os.getgid()
RUNTIME_UV_REL = Path(".runtime/uv")
BOOTSTRAP_META_REL = Path(".clone-meta/bootstrap.json")
CAMOFOX_DEFAULT_URL_CLONE = "http://host.docker.internal:9377"
OPENVIKING_DEFAULT_ENDPOINT_CLONE = "http://host.docker.internal:1933"
OPENVIKING_DEFAULT_ACCOUNT = "colmeio"

VALID_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
VALID_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

STATE_LABELS = {
    1: "orchestrator",           # bare-metal bootstrap node, symlinks to /local/plugins, /local/scripts
    2: "seed_from_parent_snapshot",
    3: "seed_from_backup",
    4: "fresh",                  # fresh containerized clone for testing/benchmarking/lab
}


class CloneManagerError(RuntimeError):
    """Custom error for user-friendly operation failures."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_dirs() -> None:
    AGENTS_ROOT.mkdir(parents=True, exist_ok=True)
    ENVS_ROOT.mkdir(parents=True, exist_ok=True)
    CLONES_ROOT.mkdir(parents=True, exist_ok=True)
    LOG_ROOT.mkdir(parents=True, exist_ok=True)


def _legacy_orchestrator_home_candidates() -> list[Path]:
    configured = str(os.getenv("HERMES_ORCHESTRATOR_LEGACY_HOME", "") or "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        [
            Path.home() / ".hermes",
            Path("/local/.hermes"),
        ]
    )

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _parent_hermes_home_source() -> Path:
    canonical = PARENT_HERMES_HOME
    if canonical.exists():
        try:
            if any(canonical.iterdir()):
                return canonical
        except Exception:
            pass
    for candidate in _legacy_orchestrator_home_candidates():
        if candidate.exists():
            return candidate
    raise CloneManagerError(
        "could not locate orchestrator state source. Checked: "
        + ", ".join([str(PARENT_HERMES_HOME)] + [str(p) for p in _legacy_orchestrator_home_candidates()])
    )


def _orchestrator_cron_host_dir(clone_name: str = "orchestrator") -> Path:
    return SHARED_CRONS_ROOT / clone_name


def _orchestrator_memory_home(clone_name: str = "orchestrator") -> Path:
    return SHARED_MEMORY_ROOT / "openviking" / clone_name


def _log(clone_name: str, message: str) -> None:
    line = f"[{_utc_now()}] {message}\n"
    candidates = [
        LOG_ROOT / f"{clone_name}.log",
        _clone_root_path(clone_name) / "logs" / "agents" / f"{clone_name}.log",
    ]
    for path in candidates:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.open("a", encoding="utf-8").write(line)
            return
        except PermissionError:
            continue
    raise CloneManagerError(f"unable to write log file for {clone_name}")


def _log_spawn_event(clone_name: str, phase: str, action: str, detail: str = "") -> None:
    """Deterministic spawn event logging for observability and replay."""
    msg = f"[{_utc_now()}] [SPAWN] phase={phase} action={action}"
    if detail:
        msg += f" detail={detail}"
    msg += "\n"
    candidates = [
        LOG_ROOT / f"{clone_name}.log",
        _clone_root_path(clone_name) / "logs" / "agents" / f"{clone_name}.log",
    ]
    for path in candidates:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.open("a", encoding="utf-8").write(msg)
            return
        except PermissionError:
            continue
    raise CloneManagerError(f"unable to write spawn log file for {clone_name}")


def _management_log_path(clone_name: str) -> Path:
    canonical = LOG_ROOT / f"{clone_name}.log"
    local_fallback = _clone_root_path(clone_name) / "logs" / "agents" / f"{clone_name}.log"
    legacy = LEGACY_LOG_ROOT / f"{clone_name}.log"
    if canonical.exists():
        return canonical
    if local_fallback.exists():
        return local_fallback
    if legacy.exists():
        return legacy
    return local_fallback


def _read_env_file(path: Path) -> Dict[str, str]:
    if not path.exists():
        raise CloneManagerError(f"clone env not found: {path}")

    env: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
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


def _load_optional_env_file(path: Path) -> None:
    """Load KEY=VALUE pairs into process env without overriding existing vars."""
    if not path.exists() or not path.is_file():
        return

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
        os.environ.setdefault(key, value)


def _upsert_env_value(path: Path, key: str, value: str) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")

    replaced = False
    changed = False
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


def _sync_discord_home_channel_env(clone_name: str, env_path: Path) -> Dict[str, Any]:
    """Map DISCORD_HOME_CHANNEL_ID -> DISCORD_HOME_CHANNEL for gateway runtime."""
    env = _read_env_file(env_path)
    source = str(env.get("DISCORD_HOME_CHANNEL_ID", "") or "").strip()
    current = str(env.get("DISCORD_HOME_CHANNEL", "") or "").strip()

    if not source:
        return {
            "mapped": False,
            "changed": False,
            "source": "",
            "effective": current,
        }

    changed = False
    if current != source:
        changed = _upsert_env_value(env_path, "DISCORD_HOME_CHANNEL", source)
        current = source if changed else str(_read_env_file(env_path).get("DISCORD_HOME_CHANNEL", "") or "").strip()
        _log(
            clone_name,
            f"discord home channel sync: mapped DISCORD_HOME_CHANNEL_ID -> DISCORD_HOME_CHANNEL ({source})",
        )

    return {
        "mapped": True,
        "changed": changed,
        "source": source,
        "effective": current or source,
    }


def _sync_restart_reboot_env(clone_name: str, env_path: Path) -> Dict[str, Any]:
    """Ensure restart/reboot commands are explicitly and safely separated.

    Contract:
    - restart => restart gateway process only (inside running container)
    - reboot  => restart container (PID 1)
    """
    env = _read_env_file(env_path)

    restart_cmd = str(env.get("COLMEIO_DISCORD_RESTART_CMD", "") or "").strip()
    reboot_cmd = str(env.get("COLMEIO_DISCORD_REBOOT_CMD", "") or "").strip()
    restart_delay = str(env.get("COLMEIO_DISCORD_RESTART_DELAY_SEC", "") or "").strip()
    reboot_delay = str(env.get("COLMEIO_DISCORD_REBOOT_DELAY_SEC", "") or "").strip()

    changed = False

    # Migrate legacy restart behavior (kill PID 1) to gateway-only restart.
    if (
        (not restart_cmd)
        or restart_cmd in {"kill -TERM 1", "kill -KILL 1"}
        or "/tmp/hermes-gateway.pid" in restart_cmd
    ):
        restart_cmd = (
            "if [ -s /tmp/hermes-gateway.pid ]; then "
            "kill -KILL $(cat /tmp/hermes-gateway.pid); "
            "else "
            "pkill -KILL -f '/local/hermes-agent/cli.py --gateway'; "
            "fi"
        )
        changed = _upsert_env_value(env_path, "COLMEIO_DISCORD_RESTART_CMD", restart_cmd) or changed

    if (
        (not reboot_cmd)
        or reboot_cmd in {"kill -TERM 1", "kill -KILL 1"}
        or "/tmp/hermes-gateway.pid" in reboot_cmd
    ):
        reboot_cmd = (
            "touch /tmp/hermes-reboot-requested; "
            "if [ -s /tmp/hermes-gateway.pid ]; then "
            "kill -KILL $(cat /tmp/hermes-gateway.pid); "
            "else "
            "pkill -KILL -f '/local/hermes-agent/cli.py --gateway'; "
            "fi"
        )
        changed = _upsert_env_value(env_path, "COLMEIO_DISCORD_REBOOT_CMD", reboot_cmd) or changed

    if not restart_delay:
        restart_delay = "0.2"
        changed = _upsert_env_value(env_path, "COLMEIO_DISCORD_RESTART_DELAY_SEC", restart_delay) or changed

    if not reboot_delay:
        reboot_delay = "0.2"
        changed = _upsert_env_value(env_path, "COLMEIO_DISCORD_REBOOT_DELAY_SEC", reboot_delay) or changed

    if changed:
        _log(
            clone_name,
            "restart/reboot env sync: "
            f"restart_cmd='{restart_cmd}' reboot_cmd='{reboot_cmd}' "
            f"restart_delay={restart_delay} reboot_delay={reboot_delay}",
        )

    return {
        "changed": changed,
        "restart_cmd": restart_cmd,
        "reboot_cmd": reboot_cmd,
        "restart_delay_sec": restart_delay,
        "reboot_delay_sec": reboot_delay,
    }


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _load_registry() -> Dict[str, Any]:
    source = REGISTRY_PATH
    if not source.exists() and LEGACY_REGISTRY_PATH.exists():
        source = LEGACY_REGISTRY_PATH
    if not source.exists():
        return {"version": 1, "clones": {}}
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "clones": {}}
    if not isinstance(data, dict):
        return {"version": 1, "clones": {}}
    clones = data.get("clones")
    if not isinstance(clones, dict):
        data["clones"] = {}
    data.setdefault("version", 1)
    return data


def _save_registry(data: Dict[str, Any]) -> None:
    _atomic_write_json(REGISTRY_PATH, data)


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise CloneManagerError(detail or f"command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc


def _docker_exists(container_name: str) -> bool:
    proc = _run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"name=^/{container_name}$",
            "--format",
            "{{.ID}}",
        ],
        check=False,
    )
    return bool((proc.stdout or "").strip())


def _docker_running(container_name: str) -> bool:
    proc = _run(
        [
            "docker",
            "ps",
            "--filter",
            f"name=^/{container_name}$",
            "--format",
            "{{.ID}}",
        ],
        check=False,
    )
    return bool((proc.stdout or "").strip())


def _docker_state(container_name: str) -> Dict[str, Any]:
    if not _docker_exists(container_name):
        return {
            "exists": False,
            "running": False,
            "status": "not_found",
        }
    proc = _run(
        ["docker", "inspect", container_name, "--format", "{{json .State}}"],
        check=False,
    )
    raw = (proc.stdout or "").strip()
    if proc.returncode != 0 or not raw:
        return {
            "exists": True,
            "running": _docker_running(container_name),
            "status": "unknown",
        }
    try:
        state = json.loads(raw)
    except Exception:
        return {
            "exists": True,
            "running": _docker_running(container_name),
            "status": "unknown",
        }
    return {
        "exists": True,
        "running": bool(state.get("Running")),
        "status": str(state.get("Status") or "unknown"),
        "started_at": str(state.get("StartedAt") or ""),
        "finished_at": str(state.get("FinishedAt") or ""),
        "exit_code": state.get("ExitCode"),
        "error": str(state.get("Error") or ""),
    }


def _normalize_clone_name(raw: str) -> str:
    name = str(raw or "").strip().lower()
    if not VALID_NAME_RE.fullmatch(name):
        raise CloneManagerError(
            "invalid clone name. Use lowercase letters, numbers, and dashes "
            "(2-63 chars), e.g. hermes-catatau"
        )
    return name


def _clone_env_path(clone_name: str) -> Path:
    canonical = ENVS_ROOT / f"{clone_name}.env"
    legacy_agents = LEGACY_AGENTS_NODES_ROOT / f"{clone_name}.env"
    legacy_clones = LEGACY_CLONES_ROOT / f"{clone_name}.env"
    for candidate in (canonical, legacy_agents, legacy_clones):
        if candidate.exists():
            return candidate
    return canonical


def _clone_root_path(clone_name: str) -> Path:
    canonical = CLONES_ROOT / clone_name
    legacy_agents = LEGACY_AGENTS_NODES_ROOT / clone_name
    legacy = LEGACY_CLONES_ROOT / clone_name
    for candidate in (canonical, legacy_agents, legacy):
        if candidate.exists():
            return candidate
    return canonical


def _container_name(clone_name: str) -> str:
    return f"{CONTAINER_PREFIX}{clone_name}"


def _ensure_hermes_source_checkout(clone_name: str = "orchestrator") -> Path:
    """Ensure /local/hermes-agent exists; clone upstream when absent."""
    source = HERMES_SOURCE_ROOT
    cli_entry = source / "cli.py"
    git_dir = source / ".git"

    if cli_entry.exists():
        return source

    if source.exists() and not git_dir.exists():
        raise CloneManagerError(
            f"hermes-agent source exists but is not a git checkout: {source}"
        )

    source.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        _log(
            clone_name,
            f"hermes-agent source missing; cloning {HERMES_AGENT_UPSTREAM_REPO} (branch={HERMES_AGENT_UPSTREAM_BRANCH}) to {source}",
        )
        _run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                HERMES_AGENT_UPSTREAM_BRANCH,
                HERMES_AGENT_UPSTREAM_REPO,
                str(source),
            ],
            check=True,
        )
    else:
        _log(
            clone_name,
            f"hermes-agent source incomplete; refreshing checkout in {source}",
        )
        _run(["git", "-C", str(source), "fetch", "--prune", "origin"], check=True)
        _run(["git", "-C", str(source), "checkout", HERMES_AGENT_UPSTREAM_BRANCH], check=True)
        _run(
            [
                "git",
                "-C",
                str(source),
                "pull",
                "--ff-only",
                "origin",
                HERMES_AGENT_UPSTREAM_BRANCH,
            ],
            check=True,
        )

    if not cli_entry.exists():
        raise CloneManagerError(
            f"hermes-agent checkout did not provide cli.py at {cli_entry}"
        )
    return source


def _parent_hermes_agent_source(clone_name: str = "orchestrator") -> Path:
    """Preferred source tree for clone seeding.

    Priority:
    1) /local/hermes-agent (canonical source checkout)
    2) <orchestrator-home>/hermes-agent (legacy runtime-patched source)
    """
    try:
        return _ensure_hermes_source_checkout(clone_name=clone_name)
    except Exception:
        pass

    candidates = [
        HERMES_SOURCE_ROOT,
        PARENT_HERMES_HOME / "hermes-agent",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise CloneManagerError("could not locate parent hermes-agent source tree")


def _clone_bootstrap_meta_path(clone_root: Path) -> Path:
    return clone_root / BOOTSTRAP_META_REL


def _is_truthy(value: Any) -> bool:
    raw = str(value or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _python_has_module(python_bin: Path, module: str) -> bool:
    if not python_bin.exists():
        return False
    probe = _run(
        [
            str(python_bin),
            "-c",
            (
                "import importlib.util,sys; "
                f"sys.exit(0 if importlib.util.find_spec('{module}') else 1)"
            ),
        ],
        check=False,
    )
    return probe.returncode == 0


def _host_python_candidates() -> list[Path]:
    """Bootstrap Python candidates (host-level, not tied to hermes-agent)."""
    configured = str(os.getenv("HERMES_CLONE_BOOTSTRAP_PYTHON", "") or "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())

    candidates.extend(
        [
            Path("/local/.venv/bin/python3"),
            Path("/usr/bin/python3"),
            Path("/usr/bin/python"),
            Path("/local/hermes-agent/.venv/bin/python3"),  # legacy fallback
        ]
    )

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _select_host_python(required_module: str | None = None) -> Path | None:
    for candidate in _host_python_candidates():
        if not candidate.exists():
            continue
        if required_module and not _python_has_module(candidate, required_module):
            continue
        return candidate
    return None


def _ensure_orchestrator_runtime(clone_name: str) -> Dict[str, Any]:
    """Ensure host runtime exists for orchestrator bare-metal gateway."""
    runtime_venv = Path("/local/.venv")
    runtime_python = runtime_venv / "bin" / "python3"
    requirements = HERMES_SOURCE_ROOT / "requirements.txt"
    source_venv = HERMES_SOURCE_ROOT / ".venv"
    source_python_candidates = [
        source_venv / "bin" / "python3",
        source_venv / "bin" / "python",
    ]
    source_python = next((p for p in source_python_candidates if p.exists()), None)

    # Fast path: if hermes-agent source venv already has gateway deps, use it.
    if source_python is not None and _python_has_module(source_python, "discord"):
        return {
            "runtime_venv": str(source_venv),
            "runtime_python": str(source_python),
            "created": False,
            "installed_dependencies": False,
            "source": "hermes_agent_venv",
        }

    if runtime_python.exists() and _python_has_module(runtime_python, "discord"):
        return {
            "runtime_venv": str(runtime_venv),
            "runtime_python": str(runtime_python),
            "created": False,
            "installed_dependencies": False,
            "source": "local_venv",
        }

    bootstrap_python = _select_host_python(required_module="venv")
    if bootstrap_python is None:
        # Fallback for minimal hosts where python3-venv is unavailable.
        if source_python is not None and _python_has_module(source_python, "discord"):
            _log(
                clone_name,
                "python3-venv unavailable; reusing /local/hermes-agent/.venv runtime for orchestrator",
            )
            return {
                "runtime_venv": str(source_venv),
                "runtime_python": str(source_python),
                "created": False,
                "installed_dependencies": False,
                "source": "hermes_agent_venv_fallback",
            }
        raise CloneManagerError(
            "python runtime with venv module not found on host. Install python3-venv and retry."
        )

    created = False
    if not runtime_python.exists():
        runtime_venv.parent.mkdir(parents=True, exist_ok=True)
        try:
            _run([str(bootstrap_python), "-m", "venv", str(runtime_venv)], check=True)
        except Exception:
            if source_python is not None and _python_has_module(source_python, "discord"):
                _log(
                    clone_name,
                    "failed to create /local/.venv; reusing /local/hermes-agent/.venv runtime",
                )
                return {
                    "runtime_venv": str(source_venv),
                    "runtime_python": str(source_python),
                    "created": False,
                    "installed_dependencies": False,
                    "source": "hermes_agent_venv_fallback",
                }
            raise
        created = True

    if not runtime_python.exists():
        raise CloneManagerError(f"failed to create runtime python at {runtime_python}")

    if not requirements.exists():
        raise CloneManagerError(f"requirements file not found: {requirements}")

    pip_probe = _run([str(runtime_python), "-m", "pip", "--version"], check=False)
    if pip_probe.returncode != 0:
        if source_python is not None and _python_has_module(source_python, "discord"):
            _log(
                clone_name,
                "runtime pip unavailable in /local/.venv; reusing /local/hermes-agent/.venv runtime",
            )
            return {
                "runtime_venv": str(source_venv),
                "runtime_python": str(source_python),
                "created": created,
                "installed_dependencies": False,
                "source": "hermes_agent_venv_fallback",
            }
        raise CloneManagerError("runtime pip unavailable in /local/.venv; install python3-venv and retry.")

    _run(
        [str(runtime_python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
        check=True,
    )
    _run([str(runtime_python), "-m", "pip", "install", "-r", str(requirements)], check=True)
    _log(clone_name, f"orchestrator runtime ready at {runtime_venv}")

    return {
        "runtime_venv": str(runtime_venv),
        "runtime_python": str(runtime_python),
        "created": created,
        "installed_dependencies": True,
        "source": "local_venv",
    }


def _seed_venv_candidates() -> list[Path]:
    preferred = [
        Path("/local/.venv"),
        HERMES_SOURCE_ROOT / ".venv",
        PARENT_HERMES_HOME / "hermes-agent" / ".venv",
    ]
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in preferred:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _select_seed_venv_source(required_module: str | None = None) -> Path:
    candidates = _seed_venv_candidates()

    if required_module:
        for venv_dir in candidates:
            py = venv_dir / "bin" / "python"
            if _python_has_module(py, required_module):
                return venv_dir

    for venv_dir in candidates:
        if (venv_dir / "bin" / "python").exists():
            return venv_dir

    raise CloneManagerError(
        "could not locate parent seed venv (expected one of "
        "/local/.venv, /local/hermes-agent/.venv, or /local/agents/nodes/orchestrator/.hermes/hermes-agent/.venv)."
    )


def _clone_runtime_uv_path(clone_root: Path) -> Path:
    return clone_root / RUNTIME_UV_REL


def _clone_runtime_log_path(clone_name: str, clone_root: Path | None = None) -> Path:
    root = clone_root if clone_root is not None else _clone_root_path(clone_name)
    canonical = root / "logs" / "agents" / f"{clone_name}.log"
    legacy = root / "logs" / "clones" / f"{clone_name}.log"
    if canonical.exists() or not legacy.exists():
        return canonical
    return legacy


def _sync_dir(src: Path, dst: Path, delete: bool = False) -> None:
    if not src.exists():
        raise CloneManagerError(f"source path not found: {src}")
    dst.mkdir(parents=True, exist_ok=True)

    rsync = shutil.which("rsync")
    if rsync:
        cmd = [rsync, "-a"]
        if delete:
            cmd.append("--delete")
        cmd.extend([f"{src}/", f"{dst}/"])
        _run(cmd, check=True)
        return

    if delete and dst.exists():
        shutil.rmtree(dst)
        dst.mkdir(parents=True, exist_ok=True)

    for item in src.iterdir():
        out = dst / item.name

        # Preserve symlinks as symlinks (including dangling links),
        # otherwise copy2/copytree can fail on broken targets.
        if item.is_symlink():
            if out.exists() or out.is_symlink():
                if out.is_dir() and not out.is_symlink():
                    shutil.rmtree(out, ignore_errors=True)
                else:
                    try:
                        out.unlink()
                    except Exception:
                        pass
            target = os.readlink(item)
            os.symlink(target, out)
            continue

        if item.is_dir():
            shutil.copytree(
                item,
                out,
                dirs_exist_ok=True,
                symlinks=True,
                ignore_dangling_symlinks=True,
            )
        else:
            shutil.copy2(item, out)


def _seed_code_tree(src: Path, dst: Path, *, include_git: bool = False) -> None:
    """Copy Hermes source tree excluding bulky / machine-specific caches."""
    if not src.exists():
        raise CloneManagerError(f"hermes source not found: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    excludes = [".venv", "__pycache__", ".pytest_cache", "*.pyc"]
    if not include_git:
        excludes.append(".git")

    rsync = shutil.which("rsync")
    if rsync:
        cmd = [
            rsync,
            "-a",
            "--delete",
        ]
        for pattern in excludes:
            cmd.extend(["--exclude", pattern])
        cmd.extend([f"{src}/", f"{dst}/"])
        _run(cmd, check=True)
        return

    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns(*excludes),
    )


def _ensure_clone_ownership(clone_root: Path) -> None:
    """Normalize clone tree ownership to host UID/GID (heals prior root-owned artifacts)."""
    if not clone_root.exists():
        return
    try:
        has_entries = any(clone_root.iterdir())
    except Exception:
        has_entries = True
    if not has_entries:
        return

    probe = _run(
        [
            "find",
            str(clone_root),
            "-xdev",
            "!",
            "-uid",
            str(HOST_UID),
            "-print",
            "-quit",
        ],
        check=False,
    )
    if probe.returncode == 0 and not (probe.stdout or "").strip():
        return

    if shutil.which("docker") is None:
        return

    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{clone_root}:/clone",
        DEFAULT_DOCKER_IMAGE,
        "sh",
        "-lc",
        f"chown -R {HOST_UID}:{HOST_GID} /clone",
    ]
    _run(cmd, check=True)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def _set_symlink(path: Path, target: Path) -> None:
    if path.is_symlink():
        try:
            if str(path.resolve()) == str(target.resolve()):
                return
        except Exception:
            pass
        _remove_path(path)
    elif path.exists():
        _remove_path(path)
    os.symlink(target, path)


def _orchestrator_runtime_agent_root(clone_root: Path) -> Path:
    return clone_root / ".runtime" / "hermes-agent"


def _prepare_orchestrator_runtime_agent_tree(
    clone_name: str,
    clone_root: Path,
    source_tree: Path,
) -> Path:
    """Create a node-local runtime code tree for orchestrator patching.

    This avoids mutating tracked /local/hermes-agent files when prestart patch
    scripts reapply Discord customizations.
    """
    runtime_root = _orchestrator_runtime_agent_root(clone_root)
    runtime_root.parent.mkdir(parents=True, exist_ok=True)
    _seed_code_tree(source_tree, runtime_root, include_git=False)

    source_venv = source_tree / ".venv"
    runtime_venv = runtime_root / ".venv"
    if source_venv.exists():
        if runtime_venv.exists() or runtime_venv.is_symlink():
            _remove_path(runtime_venv)
        os.symlink(str(source_venv), str(runtime_venv))

    _log(
        clone_name,
        f"orchestrator runtime agent tree synced: source={source_tree} runtime={runtime_root}",
    )
    return runtime_root


def _worker_cron_host_dir(clone_name: str) -> Path:
    return SHARED_CRONS_ROOT / clone_name


def _ensure_worker_shared_mount_links(clone_root: Path, clone_name: str) -> None:
    """Ensure worker node host tree is mount-ready (no self-referential links)."""
    SHARED_SCRIPTS_ROOT.mkdir(parents=True, exist_ok=True)
    SHARED_PLUGINS_ROOT.mkdir(parents=True, exist_ok=True)
    worker_crons = _worker_cron_host_dir(clone_name)
    worker_crons.mkdir(parents=True, exist_ok=True)

    for rel in ("scripts", "plugins", "crons"):
        path = clone_root / rel
        if path.is_symlink():
            _remove_path(path)
        path.mkdir(parents=True, exist_ok=True)


def _discord_plugin_roots() -> list[Path]:
    configured = str(os.getenv("HERMES_DISCORD_PLUGIN_DIR", "") or "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend([DEFAULT_DISCORD_PLUGIN_ROOT, LEGACY_DISCORD_PLUGIN_ROOT])

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _discord_plugin_dir(require_exists: bool = False) -> Path:
    roots = _discord_plugin_roots()
    for root in roots:
        if root.exists():
            return root
    if require_exists:
        raise CloneManagerError(
            "discord shared plugin dir not found. Checked: "
            + ", ".join(str(p) for p in roots)
        )
    return roots[0]


def _discord_plugin_script(relpath: str) -> Path:
    rel = Path(relpath)
    for root in _discord_plugin_roots():
        candidate = root / rel
        if candidate.exists():
            return candidate
    return _discord_plugin_roots()[0] / rel


def _ensure_discord_shared_plugin_seeded(clone_name: str) -> Path:
    target = _discord_plugin_roots()[0]
    target.parent.mkdir(parents=True, exist_ok=True)

    prestart_target = target / "scripts" / "prestart_reapply.sh"
    if prestart_target.exists():
        return target

    source = next((root for root in _discord_plugin_roots()[1:] if (root / "scripts" / "prestart_reapply.sh").exists()), None)
    if source is not None:
        _sync_dir(source, target, delete=True)
        _log(clone_name, f"discord shared plugin seeded: {source} -> {target}")
        return target

    target.mkdir(parents=True, exist_ok=True)
    _log(clone_name, f"discord shared plugin dir created (empty): {target}")
    return target


def _link_clone_workspace_discord(clone_root: Path, clone_name: str = "") -> None:
    """Expose shared Discord plugin under clone-local /local/workspace/discord."""
    workspace_discord = clone_root / "workspace" / "discord"
    if workspace_discord.exists() or workspace_discord.is_symlink():
        _remove_path(workspace_discord)
    workspace_discord.parent.mkdir(parents=True, exist_ok=True)
    os.symlink("/local/plugins/discord", workspace_discord)
    if clone_name:
        _log(clone_name, f"symlinked workspace/discord -> /local/plugins/discord")


def _link_shared_plugins_for_clone(clone_root: Path, clone_name: str) -> None:
    """Symlink /local/plugins/discord into clone's plugins directory (shared, not copied).

    Fixes the empty plugins/discord directory issue by ensuring the shared
    Discord plugin is accessible at clone_root/plugins/discord via symlink.

    If plugins/discord exists as an empty directory (not a symlink), it is replaced
    with a symlink to the shared /local/plugins/discord.
    """
    plugins_dir = clone_root / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)

    shared_plugins = Path("/local/plugins")
    discord_target = plugins_dir / "discord"

    # If it's already a symlink to the right target, nothing to do
    if discord_target.is_symlink() and discord_target.resolve() == shared_plugins / "discord":
        _log(clone_name, f"plugins/discord already symlinked to {shared_plugins}/discord")
        return

    # If it's an empty directory or wrong symlink, remove it
    if discord_target.exists() or discord_target.is_symlink():
        _remove_path(discord_target)

    # Create the symlink
    os.symlink(shared_plugins / "discord", discord_target)
    _log(clone_name, f"symlinked plugins/discord -> {shared_plugins}/discord")


def _setup_orchestrator_baremetal(clone_name: str, clone_root: Path, env: Dict[str, str], env_path: Path) -> Dict[str, Any]:
    """Set up orchestrator (CLONE_STATE=1) as a bare-metal bootstrap node.

    The orchestrator:
    - Lives directly on the VM (not containerized)
    - Lives under /local/agents/nodes/orchestrator/
    - Stores state in /local/agents/nodes/orchestrator/.hermes
    - Uses shared host assets via symlinks:
      /local/hermes-agent, /local/plugins, /local/scripts, /local/crons/orchestrator
    - Can bootstrap other nodes
    """
    _log_spawn_event(clone_name, "orchestrator", "setup_start", f"clone_root={clone_root}")

    clone_root_created = False
    if not clone_root.exists():
        clone_root.mkdir(parents=True, exist_ok=True)
        clone_root_created = True

    state_source: Path | None = None
    try:
        state_source = _parent_hermes_home_source()
    except CloneManagerError:
        state_source = None

    # Ensure canonical orchestrator directory shape.
    for sub in ("data", "workspace", ".hermes", ".runtime", "logs/agents", "logs/clones", ".clone-meta"):
        sub_path = clone_root / sub
        if sub_path.is_symlink():
            _remove_path(sub_path)
        sub_path.mkdir(parents=True, exist_ok=True)

    # Drop legacy clone-era paths that don't belong to orchestrator topology.
    for legacy_sub in ("memory", "backups", "agents", "clones"):
        legacy_path = clone_root / legacy_sub
        if legacy_path.exists() or legacy_path.is_symlink():
            _remove_path(legacy_path)

    # Make sure shared host roots exist.
    _orchestrator_cron_host_dir(clone_name).mkdir(parents=True, exist_ok=True)
    _orchestrator_memory_home(clone_name).mkdir(parents=True, exist_ok=True)
    SHARED_SCRIPTS_ROOT.mkdir(parents=True, exist_ok=True)
    SHARED_PLUGINS_ROOT.mkdir(parents=True, exist_ok=True)

    source_tree = _parent_hermes_agent_source(clone_name=clone_name)
    _set_symlink(clone_root / "hermes-agent", source_tree)
    runtime_agent_root = _prepare_orchestrator_runtime_agent_tree(
        clone_name=clone_name,
        clone_root=clone_root,
        source_tree=source_tree,
    )
    _set_symlink(clone_root / "scripts", SHARED_SCRIPTS_ROOT)
    _set_symlink(clone_root / "plugins", SHARED_PLUGINS_ROOT)
    _set_symlink(clone_root / "crons", _orchestrator_cron_host_dir(clone_name))
    runtime_bootstrap = _ensure_orchestrator_runtime(clone_name)

    orchestrator_home = clone_root / ".hermes"
    if orchestrator_home.is_symlink():
        _remove_path(orchestrator_home)
        orchestrator_home.mkdir(parents=True, exist_ok=True)

    # First bootstrap migrates legacy state (~/.hermes or /local/.hermes) into
    # /local/agents/nodes/orchestrator/.hermes.
    has_local_state = False
    try:
        has_local_state = any(orchestrator_home.iterdir())
    except Exception:
        has_local_state = False
    if not has_local_state and state_source is not None and state_source != orchestrator_home:
        _sync_dir(state_source, orchestrator_home, delete=True)
        _log_spawn_event(
            clone_name,
            "orchestrator",
            "migrate_state",
            f"source={state_source} dest={orchestrator_home}",
        )

    _link_clone_workspace_discord(clone_root, clone_name)
    try:
        _normalize_clone_skills_layout(clone_root)
    except CloneManagerError:
        home_skills = clone_root / ".hermes" / "skills"
        workspace_skills = clone_root / "workspace" / "skills"
        home_skills.mkdir(parents=True, exist_ok=True)
        if workspace_skills.exists() or workspace_skills.is_symlink():
            _remove_path(workspace_skills)
        workspace_skills.parent.mkdir(parents=True, exist_ok=True)
        os.symlink("../.hermes/skills", workspace_skills)

    # Write bootstrap metadata
    bootstrap_meta_path = _clone_bootstrap_meta_path(clone_root)
    _atomic_write_json(
        bootstrap_meta_path,
        {
            "clone_name": clone_name,
            "bootstrapped_at": _utc_now(),
            "state_mode": STATE_LABELS[1],
            "state_code": 1,
            "seed_code_source": str(source_tree),
            "runtime_agent_root": str(runtime_agent_root),
            "seed_venv_source": "",
            "state_source": str(state_source) if state_source is not None else "",
            "orchestrator_baremetal": True,
            "runtime_bootstrap": runtime_bootstrap,
            "seeded_workspace_integrations": {},
            "topology_root": str(clone_root),
            "topology_version": "agents-v2",
        },
    )
    _log_spawn_event(clone_name, "orchestrator", "bootstrap_complete", f"meta_path={bootstrap_meta_path}")

    # Keep clone-local .hermes/.env aligned with the clone profile
    clone_home_env = clone_root / ".hermes" / ".env"
    clone_home_env.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(env_path, clone_home_env)
    try:
        clone_home_env.chmod(0o600)
    except Exception:
        pass

    _log(clone_name, f"orchestrator bootstrap complete at {clone_root}")

    return {
        "clone_root_created": clone_root_created,
        "state_mode": STATE_LABELS[1],
        "state_code": 1,
        "bootstrapped": True,
        "orchestrator_baremetal": True,
    }


def _bootstrap_camofox_for_clone(clone_name: str, env_path: Path) -> Dict[str, Any]:
    env = _read_env_file(env_path)
    enabled = _is_truthy(env.get("BROWSER_CAMOFOX", ""))
    ensure_service = _is_truthy(
        env.get("CAMOFOX_ENSURE_SERVICE", env.get("BROWSER_CAMOFOX_ENSURE_SERVICE", "0"))
    )
    if not enabled:
        return {
            "enabled": False,
            "changed": False,
            "effective_url": str(env.get("CAMOFOX_URL", "") or ""),
            "service": {"attempted": False, "message": "disabled"},
        }

    camofox_bootstrap_script = _discord_plugin_script("scripts/camofox_env_bootstrap.py")
    if camofox_bootstrap_script.exists():
        python_bin = _select_host_python(required_module="json")
        if python_bin is None:
            _log(clone_name, "camofox bootstrap: python runtime not found; using fallback env update")
        else:
            proc = _run(
                [
                    str(python_bin),
                    str(camofox_bootstrap_script),
                    "--env-file",
                    str(env_path),
                    "--default-url",
                    CAMOFOX_DEFAULT_URL_CLONE,
                ]
                + (["--ensure-service"] if ensure_service else []),
                check=False,
            )
            out = (proc.stdout or "").strip()
            err = (proc.stderr or "").strip()
            payload: Dict[str, Any] = {}
            if out:
                try:
                    loaded = json.loads(out)
                    if isinstance(loaded, dict):
                        payload = loaded
                except Exception:
                    payload = {}
            if proc.returncode == 0 and payload:
                _log(
                    clone_name,
                    f"camofox bootstrap: enabled={payload.get('enabled')} changed={payload.get('changed')} "
                    f"url={payload.get('effective_url')}",
                )
                return payload
            _log(
                clone_name,
                "camofox bootstrap script failed; using fallback env update"
                + (f" stderr={err}" if err else ""),
            )

    # Fallback behavior: only env normalization, no service orchestration.
    current_url = str(env.get("CAMOFOX_URL", "") or "").strip()
    changed = False
    if not current_url:
        changed = _upsert_env_value(env_path, "CAMOFOX_URL", CAMOFOX_DEFAULT_URL_CLONE)
        env = _read_env_file(env_path)
        current_url = str(env.get("CAMOFOX_URL", "") or "").strip()
        _log(clone_name, f"camofox fallback: CAMOFOX_URL set to {current_url}")

    return {
        "enabled": True,
        "changed": changed,
        "effective_url": current_url,
        "service": {
            "attempted": False,
            "message": "fallback mode (no service bootstrap)"
            if not ensure_service
            else "fallback mode (service bootstrap failed)",
        },
    }


def _clone_supports_openviking(clone_root: Path) -> bool:
    provider_init = clone_root / "hermes-agent" / "plugins" / "memory" / "openviking" / "__init__.py"
    return provider_init.exists()


def _bootstrap_openviking_for_clone(clone_name: str, env_path: Path, clone_root: Path) -> Dict[str, Any]:
    env = _read_env_file(env_path)
    enabled = _is_truthy(env.get("MEMORY_OPENVIKING", ""))
    default_user = clone_name
    supported = _clone_supports_openviking(clone_root)

    if not enabled:
        return {
            "enabled": False,
            "changed": False,
            "effective": {
                "endpoint": str(env.get("OPENVIKING_ENDPOINT", "") or ""),
                "account": str(env.get("OPENVIKING_ACCOUNT", "") or ""),
                "user": str(env.get("OPENVIKING_USER", "") or ""),
            },
            "compatibility": {"supported": supported, "message": "disabled"},
            "degraded": False,
        }

    openviking_bootstrap_script = _discord_plugin_script("scripts/openviking_env_bootstrap.py")
    if openviking_bootstrap_script.exists():
        python_bin = _select_host_python(required_module="yaml")
        if python_bin is None:
            _log(clone_name, "openviking bootstrap: python runtime not found; using fallback env update")
        else:
            proc = _run(
                [
                    str(python_bin),
                    str(openviking_bootstrap_script),
                    "--env-file",
                    str(env_path),
                    "--config-file",
                    str(clone_root / ".hermes" / "config.yaml"),
                    "--agent-root",
                    str(clone_root / "hermes-agent"),
                    "--default-endpoint",
                    OPENVIKING_DEFAULT_ENDPOINT_CLONE,
                    "--default-account",
                    OPENVIKING_DEFAULT_ACCOUNT,
                    "--default-user",
                    default_user,
                    "--skip-health-probe",
                ],
                check=False,
            )
            out = (proc.stdout or "").strip()
            err = (proc.stderr or "").strip()
            payload: Dict[str, Any] = {}
            if out:
                try:
                    loaded = json.loads(out)
                    if isinstance(loaded, dict):
                        payload = loaded
                except Exception:
                    payload = {}
            if proc.returncode == 0 and payload:
                _log(
                    clone_name,
                    "openviking bootstrap: "
                    f"enabled={payload.get('enabled')} changed={payload.get('changed')} "
                    f"degraded={payload.get('degraded')}",
                )
                compatibility = payload.get("compatibility")
                if isinstance(compatibility, dict) and compatibility.get("supported") is False:
                    _log(clone_name, f"openviking compatibility warning: {compatibility.get('message')}")
                return payload
            _log(
                clone_name,
                "openviking bootstrap script failed; using fallback env update"
                + (f" stderr={err}" if err else ""),
            )

    # Fallback behavior: env normalization only (fail-open).
    changed = False
    if not str(env.get("OPENVIKING_ENDPOINT", "") or "").strip():
        changed = _upsert_env_value(env_path, "OPENVIKING_ENDPOINT", OPENVIKING_DEFAULT_ENDPOINT_CLONE) or changed
    if not str(env.get("OPENVIKING_ACCOUNT", "") or "").strip():
        changed = _upsert_env_value(env_path, "OPENVIKING_ACCOUNT", OPENVIKING_DEFAULT_ACCOUNT) or changed
    if not str(env.get("OPENVIKING_USER", "") or "").strip():
        changed = _upsert_env_value(env_path, "OPENVIKING_USER", default_user) or changed

    env = _read_env_file(env_path)
    if not supported:
        _log(
            clone_name,
            "openviking compatibility warning: provider plugin missing in clone code; "
            "set CLONE_FORCE_RESEED=1 and start again to upgrade.",
        )
    return {
        "enabled": True,
        "changed": changed,
        "effective": {
            "endpoint": str(env.get("OPENVIKING_ENDPOINT", "") or ""),
            "account": str(env.get("OPENVIKING_ACCOUNT", "") or ""),
            "user": str(env.get("OPENVIKING_USER", "") or ""),
        },
        "compatibility": {
            "supported": supported,
            "message": "fallback mode (env only)" if supported else (
                "provider plugin missing; explicit reseed required "
                "(set CLONE_FORCE_RESEED=1 and start again)."
            ),
        },
        "degraded": not supported,
    }


def _bootstrap_models_for_clone(clone_name: str, env_path: Path, clone_root: Path) -> Dict[str, Any]:
    env = _read_env_file(env_path)
    fallback_payload: Dict[str, Any] = {
        "ok": True,
        "changed": False,
        "model_changed": False,
        "fallback_changed": False,
        "effective": {
            "default": {
                "model": str(env.get("DEFAULT_MODEL", "") or ""),
                "provider": str(
                    env.get("DEFAULT_MODEL_PROVIDER", env.get("HERMES_INFERENCE_PROVIDER", "")) or ""
                ),
                "base_url": str(env.get("DEFAULT_MODEL_BASE_URL", "") or ""),
                "api_mode": str(env.get("DEFAULT_MODEL_API_MODE", "") or ""),
            },
            "fallback": {
                "model": str(env.get("FALLBACK_MODEL", "") or ""),
                "provider": str(env.get("FALLBACK_MODEL_PROVIDER", "") or ""),
                "base_url": str(env.get("FALLBACK_MODEL_BASE_URL", "") or ""),
                "api_mode": str(env.get("FALLBACK_MODEL_API_MODE", "") or ""),
            },
        },
        "warnings": ["model bootstrap script unavailable; using env snapshot only"],
    }

    model_bootstrap_script = _discord_plugin_script("scripts/model_env_bootstrap.py")
    if not model_bootstrap_script.exists():
        _log(clone_name, "model bootstrap: script not found; skipped")
        return fallback_payload

    python_bin = _select_host_python(required_module="yaml") or _select_host_python(required_module="json")
    if python_bin is None:
        _log(clone_name, "model bootstrap: python runtime not found; skipped")
        fallback_payload["warnings"] = ["python runtime unavailable for model bootstrap"]
        return fallback_payload

    proc = _run(
        [
            str(python_bin),
            str(model_bootstrap_script),
            "--env-file",
            str(env_path),
            "--config-file",
            str(clone_root / ".hermes" / "config.yaml"),
        ],
        check=False,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    payload: Dict[str, Any] = {}
    if out:
        try:
            loaded = json.loads(out)
            if isinstance(loaded, dict):
                payload = loaded
        except Exception:
            payload = {}
    if proc.returncode == 0 and payload:
        effective = payload.get("effective", {})
        default_cfg = effective.get("default", {}) if isinstance(effective, dict) else {}
        fallback_cfg = effective.get("fallback", {}) if isinstance(effective, dict) else {}
        _log(
            clone_name,
            "model bootstrap: "
            f"changed={payload.get('changed')} "
            f"default={default_cfg.get('provider', '')}:{default_cfg.get('model', '')} "
            f"fallback={fallback_cfg.get('provider', '')}:{fallback_cfg.get('model', '')}",
        )
        return payload

    _log(
        clone_name,
        "model bootstrap script failed; using env snapshot"
        + (f" stderr={err}" if err else ""),
    )
    fallback_payload["ok"] = False
    fallback_payload["warnings"] = [f"model bootstrap script failed: {err}" if err else "model bootstrap script failed"]
    return fallback_payload


def _parent_skills_source() -> Path:
    # Canonical source of truth is HERMES_HOME/skills; fallback to workspace/skills
    # for migration safety if the old symlink is still misconfigured.
    state_source: Path | None
    try:
        state_source = _parent_hermes_home_source()
    except CloneManagerError:
        state_source = None

    candidates = [
        (state_source / "skills") if state_source is not None else Path("/nonexistent"),
        PARENT_HERMES_HOME / "skills",
        Path("/local/workspace/skills"),
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
        if candidate.is_symlink():
            try:
                resolved = candidate.resolve(strict=True)
            except Exception:
                continue
            if resolved.is_dir():
                return resolved
    raise CloneManagerError(
        "no valid skills source found (expected orchestrator .hermes/skills or /local/workspace/skills)."
    )


def _normalize_clone_skills_layout(clone_root: Path) -> None:
    """Ensure deterministic clone skills layout.

    - Canonical skills dir: /local/.hermes/skills (clone_root/.hermes/skills)
    - Workspace legacy links are removed to avoid path drift.
    """
    home_skills = clone_root / ".hermes" / "skills"
    workspace_skills = clone_root / "workspace" / "skills"
    source = _parent_skills_source()

    needs_seed = False
    if home_skills.is_symlink():
        # Old layouts used absolute links that can become dangling; normalize to
        # a real directory under clone-local HERMES_HOME.
        _remove_path(home_skills)
        needs_seed = True
    elif not home_skills.exists():
        needs_seed = True
    elif not home_skills.is_dir():
        raise CloneManagerError(f"invalid clone skills path (not a directory): {home_skills}")

    if needs_seed:
        home_skills.mkdir(parents=True, exist_ok=True)
        _sync_dir(source, home_skills, delete=True)

    # Drop workspace compatibility link if it exists.
    if workspace_skills.exists() or workspace_skills.is_symlink():
        _remove_path(workspace_skills)


def _seed_clone_runtime(clone_root: Path, *, allow_parent_seed: bool) -> None:
    """Ensure clone-local Python runtime artifacts.

    When `allow_parent_seed` is true, missing runtime artifacts are copied from
    parent seed sources. When false, the clone must already be self-contained.
    """
    dst_venv = clone_root / "hermes-agent" / ".venv"
    dst_uv = _clone_runtime_uv_path(clone_root)

    # Heal legacy absolute links first so host-side validation works.
    _rewrite_uv_store_symlinks(clone_root)
    _rewrite_venv_uv_symlinks(clone_root)

    python_bin = dst_venv / "bin" / "python"
    if not python_bin.exists():
        if not allow_parent_seed:
            raise CloneManagerError(
                "clone runtime venv missing at /local/hermes-agent/.venv. "
                "Set CLONE_FORCE_RESEED=1 in clone env to re-bootstrap."
            )
        src_venv = _select_seed_venv_source(required_module="discord")
        _sync_dir(src_venv, dst_venv, delete=True)
        python_bin = dst_venv / "bin" / "python"

    # Validate required gateway dependency to avoid boot loops.
    if not _python_has_module(python_bin, "discord"):
        if not allow_parent_seed:
            raise CloneManagerError(
                "clone runtime venv does not include discord.py. "
                "Set CLONE_FORCE_RESEED=1 in clone env to refresh runtime."
            )
        src_venv = _select_seed_venv_source(required_module="discord")
        _sync_dir(src_venv, dst_venv, delete=True)

    uv_ready = False
    if dst_uv.exists():
        try:
            uv_ready = any(dst_uv.iterdir())
        except Exception:
            uv_ready = False
    if not uv_ready:
        if not allow_parent_seed:
            dst_uv.mkdir(parents=True, exist_ok=True)
        else:
            if not PARENT_UV_STORE.exists():
                raise CloneManagerError(f"parent uv runtime store not found: {PARENT_UV_STORE}")
            dst_uv.parent.mkdir(parents=True, exist_ok=True)
            _sync_dir(PARENT_UV_STORE, dst_uv, delete=True)

    _rewrite_uv_store_symlinks(clone_root)
    # Ensure cloned venv does not depend on /home/ubuntu path permissions
    # inside container. We pin uv runtime links to /local/.runtime/uv.
    _rewrite_venv_uv_symlinks(clone_root)


def _rewrite_venv_uv_symlinks(clone_root: Path) -> int:
    """Rewrite venv symlink targets from /home/ubuntu/.local/share/uv -> /local/.runtime/uv.

    This avoids execute failures when container UID differs from the image's
    default ubuntu user ownership/permissions under /home/ubuntu.
    """
    venv_root = clone_root / "hermes-agent" / ".venv"
    if not venv_root.exists():
        return 0

    src_prefixes = (
        "/home/ubuntu/.local/share/uv/",
        "/local/.runtime/uv/",
    )
    changed = 0

    for path in venv_root.rglob("*"):
        try:
            if not path.is_symlink():
                continue
            target = os.readlink(path)
            prefix = next((p for p in src_prefixes if target.startswith(p)), "")
            if not prefix:
                continue
            suffix = target[len(prefix) :]
            absolute_target = clone_root / ".runtime" / "uv" / suffix
            new_target = os.path.relpath(str(absolute_target), start=str(path.parent))
            path.unlink()
            os.symlink(new_target, path)
            changed += 1
        except Exception:
            continue

    return changed


def _rewrite_uv_store_symlinks(clone_root: Path) -> int:
    """Rewrite absolute symlinks inside clone-local uv runtime store."""
    uv_root = _clone_runtime_uv_path(clone_root)
    if not uv_root.exists():
        return 0

    src_prefixes = (
        "/home/ubuntu/.local/share/uv/",
        "/local/.runtime/uv/",
    )
    changed = 0

    for path in uv_root.rglob("*"):
        try:
            if not path.is_symlink():
                continue
            target = os.readlink(path)
            prefix = next((p for p in src_prefixes if target.startswith(p)), "")
            if not prefix:
                continue
            suffix = target[len(prefix) :]
            absolute_target = uv_root / suffix
            new_target = os.path.relpath(str(absolute_target), start=str(path.parent))
            path.unlink()
            os.symlink(new_target, path)
            changed += 1
        except Exception:
            continue

    return changed


def _seed_clone_workspace_integrations(clone_root: Path) -> Dict[str, bool]:
    """Legacy workspace seeding disabled in agents-v2 topology."""
    return {}


def _extract_state_mode(env: Dict[str, str]) -> int:
    raw = str(env.get("CLONE_STATE", "1") or "1").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise CloneManagerError(f"invalid CLONE_STATE value: {raw}") from exc
    if value not in STATE_LABELS:
        raise CloneManagerError(
            f"invalid CLONE_STATE value: {value}. Expected: 1=orchestrator, 2=seed_from_parent_snapshot, 3=seed_from_backup, 4=fresh."
        )
    return value


def _seed_from_backup(clone_root: Path, backup_path: Path) -> None:
    if not backup_path.exists():
        raise CloneManagerError(f"backup path not found: {backup_path}")

    with tempfile.TemporaryDirectory(prefix="hermes-clone-seed-") as tmp:
        tmp_root = Path(tmp)
        source_root = backup_path

        if backup_path.is_file():
            if not tarfile.is_tarfile(backup_path):
                raise CloneManagerError(
                    f"backup file is not a valid tar archive: {backup_path}"
                )
            with tarfile.open(backup_path, "r:*") as tf:
                tf.extractall(tmp_root)
            source_root = tmp_root

        hermes_home_candidates = [
            source_root / "home" / "ubuntu" / ".hermes",
            source_root / ".hermes",
            source_root / "hermes-home",
        ]
        workspace_candidates = [
            source_root / "local" / "workspace",
            source_root / "workspace",
        ]
        code_candidates = [
            source_root / "local" / "hermes-agent",
            source_root / "hermes-agent",
        ]

        hermes_home_src = next((p for p in hermes_home_candidates if p.exists()), None)
        if hermes_home_src is None:
            raise CloneManagerError(
                "could not find Hermes home state in backup. Expected one of: "
                "home/ubuntu/.hermes, .hermes, hermes-home"
            )

        _sync_dir(hermes_home_src, clone_root / ".hermes", delete=True)

        workspace_src = next((p for p in workspace_candidates if p.exists()), None)
        if workspace_src is not None:
            _sync_dir(workspace_src, clone_root / "workspace", delete=False)
            # Keep user payload files but drop legacy runtime trees that
            # conflict with the canonical node topology.
            for legacy_rel in (
                "data",
                "crons",
                "skills",
                "discord",
                "plugins",
                "colmeio",
            ):
                legacy_path = clone_root / "workspace" / legacy_rel
                if legacy_path.exists() or legacy_path.is_symlink():
                    _remove_path(legacy_path)

        code_src = next((p for p in code_candidates if p.exists()), None)
        if code_src is not None:
            _seed_code_tree(code_src, clone_root / "hermes-agent")


def _prepare_clone_filesystem(clone_name: str, clone_root: Path, env: Dict[str, str], env_path: Path) -> Dict[str, Any]:
    clone_root_created = False
    if not clone_root.exists():
        clone_root.mkdir(parents=True, exist_ok=True)
        clone_root_created = True

    mode = _extract_state_mode(env)

    for sub in (
        "data",
        "workspace",
        "hermes-agent",
        ".hermes",
        "logs/agents",
        ".clone-meta",
        str(RUNTIME_UV_REL),
    ):
        sub_path = clone_root / sub
        if sub_path.is_symlink():
            _remove_path(sub_path)
        sub_path.mkdir(parents=True, exist_ok=True)

    # Drop legacy clone-era paths that are outside the agents-v2 topology.
    for legacy_rel in ("memory", "backups", "agents", "clones"):
        legacy_path = clone_root / legacy_rel
        if legacy_path.exists() or legacy_path.is_symlink():
            _remove_path(legacy_path)

    # Drop workspace compatibility trees; callers should use /local/data,
    # /local/crons and /local/.hermes/skills canonical paths.
    for legacy_rel in ("data", "crons", "skills", "discord", "plugins", "colmeio"):
        legacy_path = clone_root / "workspace" / legacy_rel
        if legacy_path.exists() or legacy_path.is_symlink():
            _remove_path(legacy_path)

    _ensure_worker_shared_mount_links(clone_root, clone_name)

    _ensure_clone_ownership(clone_root)
    force_reseed = _is_truthy(env.get("CLONE_FORCE_RESEED", "0"))
    bootstrap_meta_path = _clone_bootstrap_meta_path(clone_root)
    has_local_code = (clone_root / "hermes-agent" / "cli.py").exists()
    has_local_home = (clone_root / ".hermes").exists()

    # Backward compatibility: clones created before bootstrap metadata should
    # be treated as already bootstrapped if they have local code+state.
    if not force_reseed and not bootstrap_meta_path.exists() and has_local_code and has_local_home:
        _atomic_write_json(
            bootstrap_meta_path,
            {
                "clone_name": clone_name,
                "bootstrapped_at": _utc_now(),
                "state_mode": STATE_LABELS[mode],
                "state_code": mode,
                "seed_code_source": "existing_clone_local",
                "seed_venv_source": "existing_clone_local",
                "legacy_marker_migrated": True,
                "seeded_workspace_integrations": {},
            },
        )

    needs_bootstrap = force_reseed or not bootstrap_meta_path.exists()

    # Handle orchestrator (CLONE_STATE=1) as bare-metal bootstrap node.
    if mode == 1:
        return _setup_orchestrator_baremetal(clone_name, clone_root, env, env_path)

    if needs_bootstrap:
        parent_source = _parent_hermes_agent_source()
        _seed_code_tree(parent_source, clone_root / "hermes-agent")
        _log_spawn_event(clone_name, "bootstrap", "seed_code", f"source={parent_source}")

        if mode == 2:
            parent_home = _parent_hermes_home_source()
            _sync_dir(parent_home, clone_root / ".hermes", delete=True)
            _log_spawn_event(clone_name, "bootstrap", "sync_hermes_home", f"source={parent_home}")
        elif mode == 3:
            raw_backup = str(env.get("CLONE_STATE_FROM_BACKUP_PATH", "") or "").strip()
            if not raw_backup:
                raise CloneManagerError(
                    "CLONE_STATE=3 requires CLONE_STATE_FROM_BACKUP_PATH to be set."
                )
            _seed_from_backup(clone_root, Path(raw_backup))
            _log_spawn_event(clone_name, "bootstrap", "seed_from_backup", f"path={raw_backup}")
        elif mode == 4:
            # Fresh clone - no parent state sync, no backup restore
            _log_spawn_event(clone_name, "bootstrap", "fresh_mode", "no_parent_sync")

        workspace_seeded = _seed_clone_workspace_integrations(clone_root)
        _normalize_clone_skills_layout(clone_root)
        _seed_clone_runtime(clone_root, allow_parent_seed=True)

        _atomic_write_json(
            bootstrap_meta_path,
            {
                "clone_name": clone_name,
                "bootstrapped_at": _utc_now(),
                "state_mode": STATE_LABELS[mode],
                "state_code": mode,
                "seed_code_source": str(parent_source),
                "seed_venv_source": str(_select_seed_venv_source(required_module="discord")),
                "seeded_workspace_integrations": workspace_seeded,
            },
        )
    else:
        # Standard starts must be self-contained and not re-copy parent state.
        required_paths = [
            clone_root / "hermes-agent" / "cli.py",
            clone_root / ".hermes",
        ]
        for path in required_paths:
            if not path.exists():
                raise CloneManagerError(
                    f"clone local path missing: {path}. "
                    "Set CLONE_FORCE_RESEED=1 in clone env to re-bootstrap."
                )
        _normalize_clone_skills_layout(clone_root)
        _seed_clone_runtime(clone_root, allow_parent_seed=False)

    # Keep clone-local .hermes/.env aligned with the clone profile.
    clone_home_env = clone_root / ".hermes" / ".env"
    clone_home_env.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(env_path, clone_home_env)
    try:
        clone_home_env.chmod(0o600)
    except Exception:
        pass

    return {
        "clone_root_created": clone_root_created,
        "state_mode": STATE_LABELS[mode],
        "state_code": mode,
        "bootstrapped": needs_bootstrap,
        "force_reseed": force_reseed,
    }


def _build_docker_run_cmd(
    clone_name: str,
    clone_root: Path,
    env_path: Path,
    image: str,
    shared_discord_plugin_root: Path,
    *,
    camofox_enabled: bool,
    openviking_enabled: bool,
) -> list[str]:
    container = _container_name(clone_name)
    runtime_log = f"/local/logs/agents/{clone_name}.log"
    node_crons_host = SHARED_CRONS_ROOT / clone_name
    node_crons_host.mkdir(parents=True, exist_ok=True)

    gateway_cmd = (
        "set -euo pipefail; "
        "mkdir -p /local/logs/agents; "
        "CA_BUNDLE=\"$("
        "/local/hermes-agent/.venv/bin/python -c "
        "\"import os, importlib.util; "
        "candidates=["
        "os.environ.get('SSL_CERT_FILE',''),"
        "'/etc/ssl/certs/ca-certificates.crt',"
        "'/etc/ssl/cert.pem',"
        "'/etc/pki/tls/certs/ca-bundle.crt',"
        "'/etc/ssl/ca-bundle.pem'"
        "]; "
        "spec=importlib.util.find_spec('certifi'); "
        "candidates=(([__import__('certifi').where()] if spec else []) + candidates); "
        "print(next((p for p in candidates if p and os.path.isfile(p)), ''))\""
        ")\"; "
        f"echo \"[clone-bootstrap] ca_bundle=${{CA_BUNDLE:-unset}}\" >> {runtime_log}; "
        "if [ -n \"${CA_BUNDLE:-}\" ]; then "
        "export SSL_CERT_FILE=\"$CA_BUNDLE\"; "
        "export REQUESTS_CA_BUNDLE=\"$CA_BUNDLE\"; "
        "export CURL_CA_BUNDLE=\"$CA_BUNDLE\"; "
        "fi; "
        "PRESTART_SCRIPT=\"\"; "
        "for _p in /local/plugins/discord/scripts/prestart_reapply.sh /local/workspace/discord/scripts/prestart_reapply.sh; do "
        "if [ -x \"${_p}\" ]; then PRESTART_SCRIPT=\"${_p}\"; break; fi; "
        "done; "
        "if [ -n \"${PRESTART_SCRIPT}\" ]; then "
        f"bash \"${{PRESTART_SCRIPT}}\" >> {runtime_log} 2>&1 || true; "
        "fi; "
        "rm -f /tmp/hermes-supervisor-stop /tmp/hermes-reboot-requested; "
        "SUPERVISOR_STOP=0; "
        "CHILD_PID=''; "
        "_stop_supervisor(){ "
        "SUPERVISOR_STOP=1; "
        "touch /tmp/hermes-supervisor-stop || true; "
        "if [ -n \"${CHILD_PID}\" ] && kill -0 \"${CHILD_PID}\" 2>/dev/null; then "
        "kill -TERM \"${CHILD_PID}\" 2>/dev/null || true; "
        "wait \"${CHILD_PID}\" 2>/dev/null || true; "
        "fi; "
        "exit 0; "
        "}; "
        "trap _stop_supervisor TERM INT; "
        "while true; do "
        f"/local/hermes-agent/.venv/bin/python /local/hermes-agent/cli.py --gateway >> {runtime_log} 2>&1 & "
        "CHILD_PID=$!; "
        "echo \"${CHILD_PID}\" > /tmp/hermes-gateway.pid; "
        "set +e; "
        "wait \"${CHILD_PID}\"; "
        "RC=$?; "
        "set -e; "
        f"echo \"[clone-bootstrap] gateway_exit_rc=${{RC}}\" >> {runtime_log}; "
        "if [ -f /tmp/hermes-reboot-requested ]; then "
        "rm -f /tmp/hermes-reboot-requested; "
        "exit 42; "
        "fi; "
        "if [ \"${SUPERVISOR_STOP}\" = \"1\" ] || [ -f /tmp/hermes-supervisor-stop ]; then "
        "exit 0; "
        "fi; "
        "sleep 1; "
        "done"
    )

    cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        container,
        "--restart",
        "unless-stopped",
        "--user",
        f"{HOST_UID}:{HOST_GID}",
        "--env-file",
        str(env_path),
        "-e",
        "HERMES_HOME=/local/.hermes",
        "-e",
        "HOME=/local",
        "-e",
        "COLMEIO_PROJECT_DIR=/local",
        "-e",
        "COLMEIO_DB_PATH=/local/data/colmeio_db.sqlite3",
        "-e",
        "DISCORD_USERS_DB=/local/plugins/discord/discord_users.json",
        "-e",
        "USER=ubuntu",
        "-e",
        "LOGNAME=ubuntu",
        "-e",
        "VIRTUAL_ENV=/local/hermes-agent/.venv",
        "-e",
        "PATH=/local/hermes-agent/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "-e",
        f"COLMEIO_CLONE_NAME={clone_name}",
        "-e",
        "HERMES_DISCORD_PLUGIN_DIR=/local/plugins/discord",
        "-e",
        "PYTHONUNBUFFERED=1",
        "-v",
        f"{clone_root}:/local",
        "-v",
        f"{SHARED_SCRIPTS_ROOT}:/local/scripts:ro",
        "-v",
        f"{SHARED_PLUGINS_ROOT}:/local/plugins:ro",
        "-v",
        f"{node_crons_host}:/local/crons",
        "--workdir",
        "/local/hermes-agent",
    ]

    # Needed so clone containers can reach host-level services via
    # host.docker.internal on Linux (Camofox/OpenViking defaults).
    if camofox_enabled or openviking_enabled:
        cmd.extend(["--add-host", "host.docker.internal:host-gateway"])

    cmd.extend([image, "bash", "-lc", gateway_cmd])
    return cmd


def _orchestrator_pid_path(clone_root: Path) -> Path:
    return clone_root / "data" / "gateway.pid"


def _read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    raw = str(path.read_text(encoding="utf-8", errors="ignore") or "").strip()
    if not raw:
        return None
    try:
        pid = int(raw)
    except ValueError:
        return None
    return pid if pid > 0 else None


def _pid_running(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _orchestrator_process_state(clone_root: Path) -> Dict[str, Any]:
    pid_path = _orchestrator_pid_path(clone_root)
    pid = _read_pid(pid_path)
    running = _pid_running(pid)
    return {
        "exists": True,
        "running": running,
        "status": "running" if running else "stopped",
        "pid": pid,
        "pid_file": str(pid_path),
    }


def _orchestrator_start_gateway(clone_name: str, clone_root: Path, env_path: Path) -> Dict[str, Any]:
    state = _orchestrator_process_state(clone_root)
    if state.get("running"):
        return {
            "result": "already_running",
            "pid": state.get("pid"),
            "process_state": state,
        }

    runtime_agent_root = _orchestrator_runtime_agent_root(clone_root)
    gateway_run_path = runtime_agent_root / "gateway" / "run.py"
    if not gateway_run_path.exists():
        raise CloneManagerError(f"orchestrator gateway entrypoint not found: {gateway_run_path}")

    python_candidates = [
        runtime_agent_root / ".venv" / "bin" / "python3",
        runtime_agent_root / ".venv" / "bin" / "python",
        clone_root / "hermes-agent" / ".venv" / "bin" / "python3",
        clone_root / "hermes-agent" / ".venv" / "bin" / "python",
        Path("/local/.venv/bin/python3"),
        Path("/usr/bin/python3"),
        Path("/usr/bin/python"),
    ]
    python_bin = next((p for p in python_candidates if p.exists()), None)
    if python_bin is None:
        raise CloneManagerError("python runtime not found for orchestrator gateway start")

    runtime_log = _clone_runtime_log_path(clone_name, clone_root=clone_root)
    runtime_log.parent.mkdir(parents=True, exist_ok=True)
    log_handle = runtime_log.open("a", encoding="utf-8")

    proc_env = os.environ.copy()
    proc_env.update(_read_env_file(env_path))
    proc_env["HERMES_HOME"] = str(clone_root / ".hermes")
    proc_env["HOME"] = str(clone_root)
    proc_env["USER"] = str(proc_env.get("USER") or "ubuntu")
    proc_env["LOGNAME"] = str(proc_env.get("LOGNAME") or proc_env["USER"])
    proc_env["COLMEIO_CLONE_NAME"] = clone_name
    proc_env["HERMES_DISCORD_PLUGIN_DIR"] = str(DEFAULT_DISCORD_PLUGIN_ROOT)
    proc_env["HERMES_AGENT_ROOT"] = str(runtime_agent_root)
    proc_env["PYTHONUNBUFFERED"] = "1"

    # Keep host-layer orchestrator behavior aligned with container nodes:
    # reapply Discord/runtime patches before gateway launch.
    prestart_script = _discord_plugin_script("scripts/prestart_reapply.sh")
    if prestart_script.exists():
        try:
            prestart_proc = subprocess.run(
                ["bash", str(prestart_script)],
                cwd=str(runtime_agent_root),
                env=proc_env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            if prestart_proc.returncode != 0:
                _log(
                    clone_name,
                    f"orchestrator prestart reapply failed rc={prestart_proc.returncode} script={prestart_script}",
                )
        except Exception as exc:
            _log(clone_name, f"orchestrator prestart reapply crashed: {exc}")

    proc = subprocess.Popen(
        [
            str(python_bin),
            "-c",
            (
                "import asyncio; "
                "from gateway.run import start_gateway; "
                "asyncio.run(start_gateway(replace=True))"
            ),
        ],
        cwd=str(runtime_agent_root),
        env=proc_env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        text=True,
    )
    log_handle.close()

    pid_path = _orchestrator_pid_path(clone_root)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(f"{proc.pid}\n", encoding="utf-8")

    # Fail fast if the gateway crashes immediately after spawn.
    time.sleep(2.0)
    if proc.poll() is not None:
        rc = proc.returncode
        if pid_path.exists():
            try:
                pid_path.unlink()
            except Exception:
                pass
        raise CloneManagerError(
            f"orchestrator gateway exited immediately (rc={rc}). "
            f"See runtime log: {_clone_runtime_log_path(clone_name, clone_root=clone_root)}"
        )

    _log(clone_name, f"orchestrator gateway started on host pid={proc.pid}")

    return {
        "result": "started",
        "pid": proc.pid,
        "process_state": _orchestrator_process_state(clone_root),
    }


def _orchestrator_stop_gateway(clone_name: str, clone_root: Path) -> Dict[str, Any]:
    pid_path = _orchestrator_pid_path(clone_root)
    pid = _read_pid(pid_path)
    if not _pid_running(pid):
        if pid_path.exists():
            try:
                pid_path.unlink()
            except Exception:
                pass
        return {
            "result": "not_found",
            "pid": pid,
            "process_state": _orchestrator_process_state(clone_root),
        }

    assert pid is not None
    try:
        os.kill(pid, 15)
    except OSError:
        pass

    for _ in range(25):
        if not _pid_running(pid):
            break
        time.sleep(0.2)

    if _pid_running(pid):
        try:
            os.kill(pid, 9)
        except OSError:
            pass

    for _ in range(10):
        if not _pid_running(pid):
            break
        time.sleep(0.1)

    if pid_path.exists():
        try:
            pid_path.unlink()
        except Exception:
            pass

    _log(clone_name, f"orchestrator gateway stopped pid={pid}")
    return {
        "result": "stopped",
        "pid": pid,
        "process_state": _orchestrator_process_state(clone_root),
    }


def _action_start(clone_name: str, image: str) -> Dict[str, Any]:
    env_path = _clone_env_path(clone_name)
    env = _read_env_file(env_path)
    clone_root = _clone_root_path(clone_name)
    container = _container_name(clone_name)
    state_code = _extract_state_mode(env)
    is_orchestrator = state_code == 1

    if clone_root.exists():
        # Heal legacy root-owned artifacts before any bootstrap writes.
        _ensure_clone_ownership(clone_root)
    discord_home_sync = _sync_discord_home_channel_env(clone_name, env_path)
    restart_reboot_sync = _sync_restart_reboot_env(clone_name, env_path)
    env = _read_env_file(env_path)
    state_code = _extract_state_mode(env)
    is_orchestrator = state_code == 1

    if not str(env.get("DISCORD_BOT_TOKEN", "") or "").strip():
        raise CloneManagerError(
            "DISCORD_BOT_TOKEN missing in clone env. "
            "Add it to /local/agents/envs/<clone_name>.env."
        )

    if not is_orchestrator and shutil.which("docker") is None:
        raise CloneManagerError("docker CLI not found on host.")

    shared_discord_plugin_root = _ensure_discord_shared_plugin_seeded(clone_name)
    camofox_bootstrap = _bootstrap_camofox_for_clone(clone_name, env_path)
    openviking_bootstrap = _bootstrap_openviking_for_clone(clone_name, env_path, clone_root)
    model_bootstrap = (
        _bootstrap_models_for_clone(clone_name, env_path, clone_root)
        if clone_root.exists()
        else {
            "ok": True,
            "changed": False,
            "model_changed": False,
            "fallback_changed": False,
            "effective": {
                "default": {
                    "model": str(env.get("DEFAULT_MODEL", "") or ""),
                    "provider": str(
                        env.get("DEFAULT_MODEL_PROVIDER", env.get("HERMES_INFERENCE_PROVIDER", "")) or ""
                    ),
                    "base_url": str(env.get("DEFAULT_MODEL_BASE_URL", "") or ""),
                    "api_mode": str(env.get("DEFAULT_MODEL_API_MODE", "") or ""),
                },
                "fallback": {
                    "model": str(env.get("FALLBACK_MODEL", "") or ""),
                    "provider": str(env.get("FALLBACK_MODEL_PROVIDER", "") or ""),
                    "base_url": str(env.get("FALLBACK_MODEL_BASE_URL", "") or ""),
                    "api_mode": str(env.get("FALLBACK_MODEL_API_MODE", "") or ""),
                },
            },
            "warnings": ["model bootstrap deferred until filesystem seed completes"],
        }
    )
    env = _read_env_file(env_path)
    camofox_enabled = _is_truthy(env.get("BROWSER_CAMOFOX", ""))
    openviking_enabled = _is_truthy(env.get("MEMORY_OPENVIKING", ""))

    _log(clone_name, f"start requested: container={container} env={env_path}")

    if is_orchestrator and _docker_exists(container):
        # Heals legacy deployments where orchestrator used to run in Docker.
        _run(["docker", "rm", "-f", container], check=False)

    if not is_orchestrator and _docker_running(container):
        state = _docker_state(container)
        status = str(state.get("status") or "").strip().lower()
        if status != "restarting":
            return {
                "ok": True,
                "action": "start",
                "result": "already_running",
                "clone_name": clone_name,
                "container_name": container,
                "state_mode": STATE_LABELS.get(_extract_state_mode(env), "unknown"),
                "container_state": state,
                "log_file": str(_management_log_path(clone_name)),
                "runtime_log_file": str(_clone_runtime_log_path(clone_name, clone_root=clone_root)),
                "camofox": camofox_bootstrap,
                "openviking": openviking_bootstrap,
                "models": model_bootstrap,
                "discord_home_channel": str(env.get("DISCORD_HOME_CHANNEL", "") or ""),
                "discord_home_channel_sync": discord_home_sync,
                "restart_reboot_sync": restart_reboot_sync,
            }

        _log(
            clone_name,
            "start requested while container was restarting; forcing recreate",
        )
        _run(["docker", "rm", "-f", container], check=False)

    registry_before = _load_registry()
    registry_after = json.loads(json.dumps(registry_before))

    fs_meta: Dict[str, Any] = {}
    created_container = False

    try:
        fs_meta = _prepare_clone_filesystem(clone_name, clone_root, env, env_path)
        # Re-run after filesystem prep so provider compatibility check sees
        # newly seeded clone code and can enforce memory.provider deterministically.
        openviking_bootstrap = _bootstrap_openviking_for_clone(clone_name, env_path, clone_root)
        model_bootstrap = _bootstrap_models_for_clone(clone_name, env_path, clone_root)
        env = _read_env_file(env_path)
        openviking_enabled = _is_truthy(env.get("MEMORY_OPENVIKING", ""))

        if fs_meta.get("orchestrator_baremetal"):
            host_start = _orchestrator_start_gateway(clone_name, clone_root, env_path)
            registry_after.setdefault("clones", {})
            registry_after["clones"][clone_name] = {
                "clone_name": clone_name,
                "container_name": "",
                "container_id": "",
                "runtime_type": "baremetal",
                "host_pid": host_start.get("pid"),
                "clone_root": str(clone_root),
                "env_path": str(env_path),
                "state_mode": fs_meta["state_mode"],
                "state_code": fs_meta["state_code"],
                "docker_image": "",
                "updated_at": _utc_now(),
            }
            _save_registry(registry_after)

            process_state = _orchestrator_process_state(clone_root)
            return {
                "ok": True,
                "action": "start",
                "result": host_start.get("result", "started"),
                "clone_name": clone_name,
                "container_name": "",
                "container_id": "",
                "runtime_type": "baremetal",
                "host_pid": host_start.get("pid"),
                "clone_root": str(clone_root),
                "env_path": str(env_path),
                "state_mode": fs_meta["state_mode"],
                "state_code": fs_meta["state_code"],
                "container_state": process_state,
                "log_file": str(_management_log_path(clone_name)),
                "runtime_log_file": str(_clone_runtime_log_path(clone_name, clone_root=clone_root)),
                "camofox": camofox_bootstrap,
                "openviking": openviking_bootstrap,
                "models": model_bootstrap,
                "discord_home_channel": str(env.get("DISCORD_HOME_CHANNEL", "") or ""),
                "discord_home_channel_sync": discord_home_sync,
                "restart_reboot_sync": restart_reboot_sync,
            }

        if _docker_exists(container):
            _run(["docker", "rm", "-f", container], check=False)

        cmd = _build_docker_run_cmd(
            clone_name,
            clone_root,
            env_path,
            image,
            shared_discord_plugin_root,
            camofox_enabled=camofox_enabled,
            openviking_enabled=openviking_enabled,
        )
        proc = _run(cmd, check=True)
        created_container = True
        container_id = (proc.stdout or "").strip()

        registry_after.setdefault("clones", {})
        registry_after["clones"][clone_name] = {
            "clone_name": clone_name,
            "container_name": container,
            "container_id": container_id,
            "clone_root": str(clone_root),
            "env_path": str(env_path),
            "state_mode": fs_meta["state_mode"],
            "state_code": fs_meta["state_code"],
            "docker_image": image,
            "updated_at": _utc_now(),
        }
        _save_registry(registry_after)

        state = _docker_state(container)
        _log(clone_name, f"start ok: container={container} id={container_id[:12]}")
        return {
            "ok": True,
            "action": "start",
            "result": "started",
            "clone_name": clone_name,
            "container_name": container,
            "container_id": container_id,
            "clone_root": str(clone_root),
            "env_path": str(env_path),
            "state_mode": fs_meta["state_mode"],
            "state_code": fs_meta["state_code"],
            "container_state": state,
            "log_file": str(_management_log_path(clone_name)),
            "runtime_log_file": str(_clone_runtime_log_path(clone_name, clone_root=clone_root)),
            "camofox": camofox_bootstrap,
            "openviking": openviking_bootstrap,
            "models": model_bootstrap,
            "discord_home_channel": str(env.get("DISCORD_HOME_CHANNEL", "") or ""),
            "discord_home_channel_sync": discord_home_sync,
            "restart_reboot_sync": restart_reboot_sync,
        }
    except Exception as exc:
        if created_container:
            _run(["docker", "rm", "-f", container], check=False)

        # Roll back registry to preserve transactional behavior.
        _save_registry(registry_before)

        if fs_meta.get("clone_root_created"):
            # Best-effort rollback only for brand-new roots created in this call.
            shutil.rmtree(clone_root, ignore_errors=True)

        _log(clone_name, f"start failed: {exc}")
        if isinstance(exc, CloneManagerError):
            raise
        raise CloneManagerError(f"start failed: {exc}") from exc


def _action_status(clone_name: str) -> Dict[str, Any]:
    container = _container_name(clone_name)
    env_path = _clone_env_path(clone_name)
    clone_root = _clone_root_path(clone_name)
    env = _read_env_file(env_path) if env_path.exists() else {}

    state_mode = "unknown"
    state_code: Any = None
    if env:
        try:
            state_code = _extract_state_mode(env)
            state_mode = STATE_LABELS[state_code]
        except Exception:
            state_mode = "invalid"

    is_orchestrator = state_code == 1
    state = _orchestrator_process_state(clone_root) if is_orchestrator else _docker_state(container)
    mgmt_log_file = _management_log_path(clone_name)
    return {
        "ok": True,
        "action": "status",
        "clone_name": clone_name,
        "container_name": "" if is_orchestrator else container,
        "runtime_type": "baremetal" if is_orchestrator else "container",
        "env_exists": env_path.exists(),
        "env_path": str(env_path),
        "clone_root_exists": clone_root.exists(),
        "clone_root": str(clone_root),
        "state_mode": state_mode,
        "state_code": state_code,
        "camofox_enabled": _is_truthy(env.get("BROWSER_CAMOFOX", "")) if env else False,
        "camofox_url": str(env.get("CAMOFOX_URL", "") or "") if env else "",
        "openviking_enabled": _is_truthy(env.get("MEMORY_OPENVIKING", "")) if env else False,
        "openviking_endpoint": str(env.get("OPENVIKING_ENDPOINT", "") or "") if env else "",
        "openviking_account": str(env.get("OPENVIKING_ACCOUNT", "") or "") if env else "",
        "openviking_user": str(env.get("OPENVIKING_USER", "") or "") if env else "",
        "openviking_supported": _clone_supports_openviking(clone_root) if clone_root.exists() else False,
        "default_model_env": str(env.get("DEFAULT_MODEL", "") or "") if env else "",
        "default_model_provider_env": str(
            env.get("DEFAULT_MODEL_PROVIDER", env.get("HERMES_INFERENCE_PROVIDER", "")) or ""
        )
        if env
        else "",
        "fallback_model_env": str(env.get("FALLBACK_MODEL", "") or "") if env else "",
        "fallback_model_provider_env": str(env.get("FALLBACK_MODEL_PROVIDER", "") or "") if env else "",
        "discord_home_channel": str(env.get("DISCORD_HOME_CHANNEL", "") or "") if env else "",
        "discord_home_channel_id": str(env.get("DISCORD_HOME_CHANNEL_ID", "") or "") if env else "",
        "discord_restart_cmd": str(env.get("COLMEIO_DISCORD_RESTART_CMD", "") or "") if env else "",
        "discord_reboot_cmd": str(env.get("COLMEIO_DISCORD_REBOOT_CMD", "") or "") if env else "",
        "discord_restart_delay_sec": str(env.get("COLMEIO_DISCORD_RESTART_DELAY_SEC", "") or "") if env else "",
        "discord_reboot_delay_sec": str(env.get("COLMEIO_DISCORD_REBOOT_DELAY_SEC", "") or "") if env else "",
        "container_state": state,
        "log_file": str(mgmt_log_file),
        "runtime_log_file": str(_clone_runtime_log_path(clone_name, clone_root=clone_root)),
    }


def _action_stop(clone_name: str) -> Dict[str, Any]:
    container = _container_name(clone_name)
    env_path = _clone_env_path(clone_name)
    env = _read_env_file(env_path) if env_path.exists() else {}
    state_code: Any = None
    if env:
        try:
            state_code = _extract_state_mode(env)
        except Exception:
            state_code = None
    is_orchestrator = state_code == 1
    clone_root = _clone_root_path(clone_name)

    _log(clone_name, "stop requested")
    if is_orchestrator:
        stop_state = _orchestrator_stop_gateway(clone_name, clone_root)
        return {
            "ok": True,
            "action": "stop",
            "result": str(stop_state.get("result") or "stopped"),
            "clone_name": clone_name,
            "container_name": "",
            "runtime_type": "baremetal",
            "container_state": stop_state.get("process_state", {}),
            "host_pid": stop_state.get("pid"),
        }

    if not _docker_exists(container):
        return {
            "ok": True,
            "action": "stop",
            "result": "not_found",
            "clone_name": clone_name,
            "container_name": container,
            "runtime_type": "container",
        }

    _run(["docker", "stop", container], check=False)
    state = _docker_state(container)
    _log(clone_name, f"stop result: status={state.get('status')}")
    return {
        "ok": True,
        "action": "stop",
        "result": "stopped",
        "clone_name": clone_name,
        "container_name": container,
        "runtime_type": "container",
        "container_state": state,
    }


def _action_delete(clone_name: str) -> Dict[str, Any]:
    container = _container_name(clone_name)
    env_path = _clone_env_path(clone_name)
    env = _read_env_file(env_path) if env_path.exists() else {}
    state_code: Any = None
    if env:
        try:
            state_code = _extract_state_mode(env)
        except Exception:
            state_code = None
    is_orchestrator = state_code == 1
    clone_root = _clone_root_path(clone_name)

    _log(clone_name, "delete requested")

    if is_orchestrator:
        _orchestrator_stop_gateway(clone_name, clone_root)

    if _docker_exists(container):
        _run(["docker", "rm", "-f", container], check=False)

    reg = _load_registry()
    clones = reg.get("clones") if isinstance(reg.get("clones"), dict) else {}
    if clone_name in clones:
        clones.pop(clone_name, None)
        reg["clones"] = clones
        _save_registry(reg)

    _log(clone_name, "delete completed (container removed; data preserved)")
    return {
        "ok": True,
        "action": "delete",
        "result": "deleted",
        "clone_name": clone_name,
        "container_name": "" if is_orchestrator else container,
        "runtime_type": "baremetal" if is_orchestrator else "container",
        "data_preserved": True,
        "clone_root": str(clone_root),
    }


def _tail_file(path: Path, lines: int) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="ignore")
    parts = text.splitlines()
    return "\n".join(parts[-lines:])


def _action_logs(clone_name: str, lines: int) -> Dict[str, Any]:
    mgmt_log_file = _management_log_path(clone_name)
    runtime_log_file = _clone_runtime_log_path(clone_name)
    mgmt_text = _tail_file(mgmt_log_file, lines)
    runtime_text = _tail_file(runtime_log_file, lines)

    chunks: list[str] = []
    if mgmt_text:
        chunks.append(f"== management ({mgmt_log_file}) ==\n{mgmt_text}")
    if runtime_text:
        chunks.append(f"== runtime ({runtime_log_file}) ==\n{runtime_text}")
    text = "\n\n".join(chunks).strip()

    if not text:
        container = _container_name(clone_name)
        if _docker_exists(container):
            proc = _run(["docker", "logs", "--tail", str(lines), container], check=False)
            text = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()

    return {
        "ok": True,
        "action": "logs",
        "clone_name": clone_name,
        "log_file": str(mgmt_log_file),
        "runtime_log_file": str(runtime_log_file),
        "lines": lines,
        "log_text": text,
    }


def _git_commit(path: Path) -> str:
    proc = _run(["git", "-C", str(path), "rev-parse", "HEAD"], check=False)
    if proc.returncode != 0:
        return ""
    return str(proc.stdout or "").strip()


def _git_branch(path: Path) -> str:
    proc = _run(["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"], check=False)
    if proc.returncode != 0:
        return ""
    return str(proc.stdout or "").strip()


def _action_update_template(source_branch: str) -> Dict[str, Any]:
    _ensure_hermes_source_checkout("orchestrator")
    if not HERMES_SOURCE_ROOT.exists():
        raise CloneManagerError(f"hermes-agent source tree not found: {HERMES_SOURCE_ROOT}")

    branch = str(source_branch or "").strip() or HERMES_AGENT_UPSTREAM_BRANCH
    before_commit = _git_commit(HERMES_SOURCE_ROOT)
    before_branch = _git_branch(HERMES_SOURCE_ROOT)
    source_mode = "snapshot_sync"
    upstream_commit = ""

    if (HERMES_SOURCE_ROOT / ".git").exists():
        _run(["git", "-C", str(HERMES_SOURCE_ROOT), "fetch", "--prune", "origin"], check=True)
        _run(["git", "-C", str(HERMES_SOURCE_ROOT), "checkout", branch], check=True)
        _run(
            ["git", "-C", str(HERMES_SOURCE_ROOT), "pull", "--ff-only", "origin", branch],
            check=True,
        )
        source_mode = "git_checkout"
        upstream_commit = _git_commit(HERMES_SOURCE_ROOT)
    else:
        with tempfile.TemporaryDirectory(prefix="horc-agent-update-") as tmp:
            tmp_root = Path(tmp)
            _run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    branch,
                    HERMES_AGENT_UPSTREAM_REPO,
                    str(tmp_root),
                ],
                check=True,
            )
            upstream_commit = _git_commit(tmp_root)
            _seed_code_tree(tmp_root, HERMES_SOURCE_ROOT, include_git=False)

    after_commit = _git_commit(HERMES_SOURCE_ROOT) or upstream_commit
    after_branch = _git_branch(HERMES_SOURCE_ROOT) or branch
    changed = bool(before_commit and after_commit and before_commit != after_commit)
    if not before_commit and after_commit:
        changed = True

    _log(
        "orchestrator",
        f"template update: branch={branch} before={before_commit or 'unknown'} after={after_commit or 'unknown'} changed={str(changed).lower()}",
    )

    return {
        "ok": True,
        "action": "update",
        "target": "template",
        "source_root": str(HERMES_SOURCE_ROOT),
        "branch_requested": branch,
        "branch_before": before_branch,
        "branch_after": after_branch,
        "commit_before": before_commit,
        "commit_after": after_commit,
        "upstream_commit": upstream_commit,
        "source_mode": source_mode,
        "changed": changed,
        "applies_to_new_nodes": True,
    }


def _action_update_node(clone_name: str, source_branch: str) -> Dict[str, Any]:
    env_path = _clone_env_path(clone_name)
    clone_root = _clone_root_path(clone_name)
    if not env_path.exists():
        raise CloneManagerError(f"clone env not found: {env_path}")
    if not clone_root.exists():
        raise CloneManagerError(f"clone root not found: {clone_root}")

    env = _read_env_file(env_path)
    state_code = _extract_state_mode(env)
    if state_code == 1:
        template_payload = _action_update_template(source_branch)
        source_root = _parent_hermes_agent_source(clone_name=clone_name)
        runtime_root = _prepare_orchestrator_runtime_agent_tree(
            clone_name=clone_name,
            clone_root=clone_root,
            source_tree=source_root,
        )
        source_commit = _git_commit(source_root)

        process_state_before = _orchestrator_process_state(clone_root)
        was_running = bool(process_state_before.get("running"))
        if was_running:
            _orchestrator_stop_gateway(clone_name, clone_root)
            _orchestrator_start_gateway(clone_name, clone_root, env_path)

        process_state_after = _orchestrator_process_state(clone_root)
        return {
            "ok": True,
            "action": "update",
            "target": "orchestrator",
            "clone_name": clone_name,
            "clone_root": str(clone_root),
            "env_path": str(env_path),
            "source_root": str(source_root),
            "source_commit": source_commit,
            "runtime_root": str(runtime_root),
            "was_running": was_running,
            "process_state_before": process_state_before,
            "process_state_after": process_state_after,
            "template_update": template_payload,
            "note": (
                "orchestrator now patches and runs from "
                "agents/nodes/orchestrator/.runtime/hermes-agent; /local/hermes-agent stays template-only."
            ),
        }

    template_payload = _action_update_template(source_branch)
    source_root = _parent_hermes_agent_source(clone_name=clone_name)
    source_commit = _git_commit(source_root)
    clone_commit_before = _git_commit(clone_root / "hermes-agent")

    container = _container_name(clone_name)
    container_exists = _docker_exists(container)
    was_running = _docker_running(container) if container_exists else False

    if was_running:
        _run(["docker", "stop", container], check=True)
        _log(clone_name, "node update: container stopped for hermes-agent sync")

    _seed_code_tree(source_root, clone_root / "hermes-agent")
    _seed_clone_runtime(clone_root, allow_parent_seed=True)
    clone_commit_after = _git_commit(clone_root / "hermes-agent")

    if was_running:
        _run(["docker", "start", container], check=True)
        _log(clone_name, "node update: container restarted after hermes-agent sync")

    container_state = _docker_state(container) if container_exists else {
        "exists": False,
        "running": False,
        "status": "not_found",
    }

    changed = True
    if clone_commit_before and clone_commit_after:
        changed = clone_commit_before != clone_commit_after

    return {
        "ok": True,
        "action": "update",
        "target": "node",
        "clone_name": clone_name,
        "clone_root": str(clone_root),
        "env_path": str(env_path),
        "source_root": str(source_root),
        "source_commit": source_commit,
        "clone_commit_before": clone_commit_before,
        "clone_commit_after": clone_commit_after,
        "changed": changed,
        "container_name": container,
        "container_exists": container_exists,
        "was_running": was_running,
        "container_state": container_state,
        "template_update": template_payload,
    }


def _action_update(clone_name: str | None, source_branch: str) -> Dict[str, Any]:
    if clone_name:
        return _action_update_node(clone_name, source_branch=source_branch)
    return _action_update_template(source_branch=source_branch)


def _dispatch(
    action: str,
    clone_name: str | None,
    image: str,
    lines: int,
    source_branch: str,
) -> Dict[str, Any]:
    if action == "start":
        if not clone_name:
            raise CloneManagerError("start requires clone name")
        return _action_start(clone_name, image=image)
    if action == "status":
        if not clone_name:
            raise CloneManagerError("status requires clone name")
        return _action_status(clone_name)
    if action == "stop":
        if not clone_name:
            raise CloneManagerError("stop requires clone name")
        return _action_stop(clone_name)
    if action == "delete":
        if not clone_name:
            raise CloneManagerError("delete requires clone name")
        return _action_delete(clone_name)
    if action == "logs":
        if not clone_name:
            raise CloneManagerError("logs requires clone name")
        return _action_logs(clone_name, lines=lines)
    if action == "update":
        return _action_update(clone_name, source_branch=source_branch)
    raise CloneManagerError(f"unsupported action: {action}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes clone lifecycle manager")
    parser.add_argument("action", choices=["start", "status", "stop", "delete", "logs", "update"])
    parser.add_argument(
        "name_positional",
        nargs="?",
        default=None,
        help="Clone name (default: orchestrator)",
    )
    parser.add_argument(
        "--name",
        dest="name_flag",
        default=None,
        help="Clone name (maps to /local/agents/envs/<name>.env)",
    )
    parser.add_argument("--image", default=DEFAULT_DOCKER_IMAGE, help="Docker image for clone runtime")
    parser.add_argument("--lines", type=int, default=80, help="Log tail lines for logs action")
    parser.add_argument(
        "--source-branch",
        default=str(os.getenv("HERMES_AGENT_UPDATE_BRANCH", HERMES_AGENT_UPSTREAM_BRANCH) or HERMES_AGENT_UPSTREAM_BRANCH),
        help="Source git branch used by 'update' when syncing /local/hermes-agent",
    )
    return parser


def main() -> int:
    _load_optional_env_file(HOST_BOOTSTRAP_ENV_FILE)
    _ensure_dirs()
    parser = _build_parser()
    args = parser.parse_args()

    try:
        clone_name: str | None
        if args.action == "update":
            raw_name = args.name_flag or args.name_positional
            clone_name = _normalize_clone_name(raw_name) if raw_name else None
        else:
            raw_name = (
                args.name_flag
                or args.name_positional
                or str(os.getenv("HERMES_DEFAULT_NODE", "orchestrator") or "orchestrator")
            )
            clone_name = _normalize_clone_name(raw_name)
        lines = max(10, min(int(args.lines), 500))
        payload = _dispatch(
            args.action,
            clone_name,
            image=str(args.image),
            lines=lines,
            source_branch=str(args.source_branch or HERMES_AGENT_UPSTREAM_BRANCH),
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except CloneManagerError as exc:
        err = {
            "ok": False,
            "error": str(exc),
        }
        print(json.dumps(err, ensure_ascii=False))
        return 1
    except Exception as exc:
        err = {
            "ok": False,
            "error": f"unexpected error: {exc}",
        }
        print(json.dumps(err, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
