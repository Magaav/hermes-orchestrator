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
  - Per-node centralized logs at /local/logs/nodes/<clone_name>/

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

Per-node configuration (in /local/agents/envs/<node_name>.env):
  OPENVIKING_ENABLED=1          # Enable OpenViking (0 to disable)
  OPENVIKING_ENDPOINT=...       # Server URL (auto-set to host.docker.internal for clones)
  # OPENVIKING_ACCOUNT / OPENVIKING_USER are optional and default to <node_name>

The clone manager auto-configures OpenViking during `start` by calling
openviking_env_bootstrap.py which:
  1. Validates the provider plugin exists in hermes-agent/plugins/memory/openviking/
  2. Probes the endpoint health
  3. Updates config.yaml to set memory.provider=openviking
  4. Sets fail-open mode if endpoint is unreachable

Legacy keys remain supported for compatibility:
  MEMORY_OPENVIKING -> OPENVIKING_ENABLED
  BROWSER_CAMOFOX   -> CAMOFOX_ENABLED
  CLONE_STATE*      -> NODE_STATE*
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict


AGENTS_ROOT = Path(os.getenv("HERMES_AGENTS_ROOT", "/local/agents"))
ENVS_ROOT = Path(os.getenv("HERMES_AGENTS_ENVS_ROOT", str(AGENTS_ROOT / "envs")))
CLONES_ROOT = Path(os.getenv("HERMES_AGENTS_NODES_ROOT", str(AGENTS_ROOT / "nodes")))
NODE_ENV_TEMPLATE_PATH = ENVS_ROOT / "node.env.example"
ORCHESTRATOR_ENV_TEMPLATE_PATH = ENVS_ROOT / "orchestrator.env.example"
LOGS_ROOT = Path(os.getenv("HERMES_LOGS_ROOT", "/local/logs"))
NODE_LOG_ROOT = Path(os.getenv("HERMES_AGENTS_NODE_LOG_ROOT", str(LOGS_ROOT / "nodes")))
ATTENTION_LOG_ROOT = Path(
    os.getenv("HERMES_AGENTS_ATTENTION_LOG_ROOT", str(LOGS_ROOT / "attention" / "nodes"))
)
REGISTRY_PATH = Path(os.getenv("HERMES_AGENTS_REGISTRY_PATH", str(AGENTS_ROOT / "registry.json")))

CANONICAL_ORCHESTRATOR_HOME = Path(
    os.getenv("HERMES_ORCHESTRATOR_HOME", str(CLONES_ROOT / "orchestrator" / ".hermes"))
)
PARENT_HERMES_HOME = CANONICAL_ORCHESTRATOR_HOME
PARENT_UV_STORE = Path(os.getenv("HERMES_PARENT_UV_STORE", str(Path.home() / ".local" / "share" / "uv")))
SCRIPTS_ROOT = Path(
    str(
        os.getenv("HERMES_SCRIPTS_ROOT", "")
        or "/local/scripts"
    )
)
PRIVATE_SCRIPTS_ROOT = Path(
    str(
        os.getenv("HERMES_PRIVATE_SCRIPTS_ROOT", "")
        or (SCRIPTS_ROOT / "private")
    )
)
PLUGINS_ROOT = Path(
    str(
        os.getenv("HERMES_PLUGINS_ROOT", "")
        or "/local/plugins"
    )
)
SHARED_PLUGINS_ROOT = Path(
    str(
        os.getenv("HERMES_PUBLIC_PLUGINS_ROOT", "")
        or (PLUGINS_ROOT / "public")
    )
)
SHARED_SCRIPTS_ROOT = Path(
    str(
        os.getenv("HERMES_PUBLIC_SCRIPTS_ROOT", "")
        or (SCRIPTS_ROOT / "public")
    )
)
PRIVATE_PLUGINS_ROOT = Path(
    str(
        os.getenv("HERMES_PRIVATE_PLUGINS_ROOT", "")
        or (PLUGINS_ROOT / "private")
    )
)
SHARED_CRONS_ROOT = Path(
    str(
        os.getenv("HERMES_PRIVATE_CRONS_ROOT", "")
        or os.getenv("HERMES_CRONS_ROOT", "")
        or "/local/crons"
    )
)
LEGACY_SHARED_CRONS_ROOT = PRIVATE_SCRIPTS_ROOT / "crons"
SHARED_WIKI_ROOT = Path(
    str(
        os.getenv("HERMES_SHARED_WIKI_ROOT", "")
        or os.getenv("HERMES_PRIVATE_WIKI_ROOT", "")
        or (PRIVATE_PLUGINS_ROOT / "wiki")
    )
)
PRIVATE_SKILLS_ROOT = Path(
    str(
        os.getenv("HERMES_PRIVATE_SKILLS_ROOT", "")
        or "/local/skills"
    )
)
SHARED_MEMORY_ROOT = Path(
    str(
        os.getenv("HERMES_PRIVATE_MEMORY_ROOT", "")
        or os.getenv("HERMES_MEMORY_ROOT", "")
        or (PRIVATE_PLUGINS_ROOT / "memory")
    )
)
SHARED_NODE_DATA_ROOT = Path(
    str(
        os.getenv("HERMES_SHARED_NODE_DATA_ROOT", "")
        or os.getenv("HERMES_DATAS_ROOT", "")
        or os.getenv("HERMES_DATA_ROOT", "")
        or "/local/datas"
    )
)
BACKUPS_ROOT = Path(os.getenv("HERMES_BACKUPS_ROOT", "/local/backups"))
HERMES_SOURCE_ROOT = Path(os.getenv("HERMES_SOURCE_ROOT", "/local/hermes-agent"))
HERMES_AGENT_UPSTREAM_REPO = str(
    os.getenv("HERMES_AGENT_UPSTREAM_REPO", "https://github.com/NousResearch/hermes-agent.git")
    or "https://github.com/NousResearch/hermes-agent.git"
).strip()
HERMES_AGENT_UPSTREAM_BRANCH = str(
    os.getenv("HERMES_AGENT_UPSTREAM_BRANCH", "main") or "main"
).strip() or "main"
DEFAULT_DISCORD_PLUGIN_ROOT = SHARED_PLUGINS_ROOT / "discord"
DEFAULT_HERMES_CORE_PLUGIN_ROOT = SHARED_PLUGINS_ROOT / "hermes-core"
DEFAULT_DISCORD_PRIVATE_ROOT = PRIVATE_PLUGINS_ROOT / "discord"
HOST_BOOTSTRAP_ENV_FILE = Path(os.getenv("HERMES_BOOTSTRAP_ENV_FILE", "/local/.env"))
UPDATE_TEST_NODE_DEFAULT = str(os.getenv("HERMES_UPDATE_TEST_NODE", "node-dummy") or "node-dummy").strip() or "node-dummy"
UPDATE_TEST_ENV_SOURCE = Path(
    str(os.getenv("HERMES_UPDATE_TEST_ENV_FILE", "/local/dummy/dummy.env") or "/local/dummy/dummy.env")
)
UPDATE_TEST_LOG_ROOT = Path(
    str(os.getenv("HERMES_UPDATE_TEST_LOG_ROOT", "/log/update") or "/log/update")
)
UPDATE_TEST_LOG_FALLBACK_ROOT = Path(
    str(os.getenv("HERMES_UPDATE_TEST_LOG_FALLBACK", "/local/log/update") or "/local/log/update")
)
UPDATE_DUMMY_ROOT = Path(
    str(os.getenv("HERMES_UPDATE_DUMMY_ROOT", "/local/dummy") or "/local/dummy")
)
UPDATE_DUMMY_HERMES_ROOT = UPDATE_DUMMY_ROOT / "hermes-agent"
UPDATE_DUMMY_PLUGINS_ROOT = UPDATE_DUMMY_ROOT / "plugins"
UPDATE_DUMMY_SCRIPTS_ROOT = UPDATE_DUMMY_ROOT / "scripts"
UPDATE_DUMMY_PUBLIC_PLUGINS_ROOT = UPDATE_DUMMY_PLUGINS_ROOT / "public"
UPDATE_DUMMY_PRIVATE_PLUGINS_ROOT = UPDATE_DUMMY_PLUGINS_ROOT / "private"
UPDATE_DUMMY_PUBLIC_SCRIPTS_ROOT = UPDATE_DUMMY_SCRIPTS_ROOT / "public"
UPDATE_DUMMY_PRIVATE_SCRIPTS_ROOT = UPDATE_DUMMY_SCRIPTS_ROOT / "private"

DEFAULT_DOCKER_IMAGE = os.getenv("HERMES_CLONE_DOCKER_IMAGE", "ubuntu:24.04")
CONTAINER_PREFIX = "hermes-node-"
HOST_UID = os.getuid()
HOST_GID = os.getgid()
RUNTIME_UV_REL = Path(".runtime/uv")
BOOTSTRAP_META_REL = Path(".clone-meta/bootstrap.json")
NODE_RUNTIME_CONTRACT_REL = Path(".hermes/NODE_RUNTIME_CONTRACT.md")
NODE_RUNTIME_CONTRACT_WORKSPACE_REL = Path("workspace/NODE_RUNTIME_CONTRACT.md")
CAMOFOX_DEFAULT_URL_CLONE = "http://host.docker.internal:9377"
OPENVIKING_DEFAULT_ENDPOINT_CLONE = "http://host.docker.internal:1933"
GATEWAY_REQUIRED_MODULES: tuple[str, ...] = ("discord", "yaml")
DISCORD_DEFAULT_RESTART_CMD = (
    "if [ -s /tmp/hermes-gateway.pid ]; then "
    "kill -KILL $(cat /tmp/hermes-gateway.pid); "
    "else "
    "pkill -KILL -f '/local/hermes-agent/cli.py --gateway'; "
    "fi"
)
DISCORD_DEFAULT_REBOOT_CMD = (
    "touch /tmp/hermes-reboot-requested; "
    "if [ -s /tmp/hermes-gateway.pid ]; then "
    "kill -KILL $(cat /tmp/hermes-gateway.pid); "
    "else "
    "pkill -KILL -f '/local/hermes-agent/cli.py --gateway'; "
    "fi"
)
DISCORD_DEFAULT_RESTART_DELAY_SEC = "0.1"
DISCORD_DEFAULT_REBOOT_DELAY_SEC = "0.1"
NODE_WORKSPACE_ROOT_IN_CONTAINER = "/local/workspace"
NODE_WORKSPACE_DB_PATH_IN_CONTAINER = "/local/data/colmeio_db.sqlite3"
NODE_WORKSPACE_DISCORD_SETTINGS_IN_CONTAINER = "/local/workspace/discord/discord_settings.json"
# Canonical shared Discord ACL/users table now lives in the private plugin root.
# Keep variable name stable to avoid touching unrelated call sites.
NODE_WORKSPACE_DISCORD_USERS_DB_IN_CONTAINER = "/local/plugins/private/discord/discord_users.json"
NODE_SKILLS_PATH_IN_CONTAINER = "/local/skills"
ORCHESTRATOR_BACKUP_CRON_SCRIPT = "backup_daily_brt.sh"

VALID_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
VALID_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ATTENTION_LINE_RE = re.compile(
    r"\b(warn(?:ing)?|error|critical|fatal|panic|emerg(?:ency)?|alert)\b",
    re.IGNORECASE,
)
PLUGIN_PATH_RE = re.compile(r"/plugins/(?:public|private)/([^/\s]+)/")

STATE_LABELS = {
    1: "orchestrator",           # bare-metal bootstrap node, syncs local hermes-agent copy + shared asset symlinks
    2: "seed_from_parent_snapshot",
    3: "seed_from_backup",
    4: "fresh",                  # fresh containerized clone for testing/benchmarking/lab
}

NODE_BACKUP_EXCLUDE_PREFIXES: tuple[str, ...] = (
    # Shared host mirrors and mount anchors (canonical roots are backed up once).
    "plugins",
    "scripts",
    "skills",
    "wiki",
    "cron",
    "crons",
    "data",
    # Node-local transient/runtime noise.
    ".runtime",
    "hermes-agent",
    "logs",
    ".cache",
    ".local",
    "workspace/skills",
    ".hermes/skills",
    ".hermes/logs",
    ".hermes/audio_cache",
    ".hermes/browser_screenshots",
    ".hermes/sandboxes",
    ".hermes/sessions/request_dump_",
    ".hermes/hermes-agent",
    ".hermes/node",
    ".hermes/skills.backup-",
    # Source checkout metadata/docs that bloat archives without affecting restore state.
    "hermes-agent/.git",
    "hermes-agent/tests",
    "hermes-agent/docs",
    "hermes-agent/website",
    "hermes-agent/optional-skills",
    "hermes-agent/skills",
    "hermes-agent/plugins",
    "hermes-agent/__pycache__",
)


class CloneManagerError(RuntimeError):
    """Custom error for user-friendly operation failures."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dir_has_entries(path: Path, *, ignored_names: set[str] | None = None) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    ignored = ignored_names or set()
    for entry in path.iterdir():
        if entry.name in ignored:
            continue
        return True
    return False


def _ensure_root_dir(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        _remove_path(target)
    elif target.exists() and not target.is_dir():
        _remove_path(target)
    target.mkdir(parents=True, exist_ok=True)


def _migrate_legacy_crons_root() -> None:
    legacy = LEGACY_SHARED_CRONS_ROOT
    target = SHARED_CRONS_ROOT
    if legacy == target:
        return
    if not (legacy.exists() or legacy.is_symlink()):
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.move(str(legacy), str(target))
        return

    if legacy.is_symlink():
        _remove_path(legacy)
        return
    if not legacy.is_dir():
        _remove_path(legacy)
        return

    for item in sorted(legacy.iterdir(), key=lambda p: p.name):
        dst = target / item.name
        if dst.exists() or dst.is_symlink():
            continue
        if item.is_symlink():
            os.symlink(os.readlink(item), dst)
            continue
        if item.is_dir():
            shutil.copytree(item, dst, symlinks=True)
            continue
        shutil.copy2(item, dst)
    _remove_path(legacy)


def _ensure_dirs() -> None:
    AGENTS_ROOT.mkdir(parents=True, exist_ok=True)
    ENVS_ROOT.mkdir(parents=True, exist_ok=True)
    CLONES_ROOT.mkdir(parents=True, exist_ok=True)
    if SCRIPTS_ROOT.is_symlink() or (SCRIPTS_ROOT.exists() and not SCRIPTS_ROOT.is_dir()):
        _remove_path(SCRIPTS_ROOT)
    SCRIPTS_ROOT.mkdir(parents=True, exist_ok=True)

    LOGS_ROOT.mkdir(parents=True, exist_ok=True)
    NODE_LOG_ROOT.mkdir(parents=True, exist_ok=True)
    ATTENTION_LOG_ROOT.mkdir(parents=True, exist_ok=True)
    BACKUPS_ROOT.mkdir(parents=True, exist_ok=True)
    PLUGINS_ROOT.mkdir(parents=True, exist_ok=True)
    _ensure_root_dir(SHARED_SCRIPTS_ROOT)
    _ensure_root_dir(PRIVATE_SCRIPTS_ROOT)
    _migrate_legacy_crons_root()
    _ensure_root_dir(SHARED_CRONS_ROOT)
    _ensure_orchestrator_backup_cron_script()
    _ensure_root_dir(SHARED_PLUGINS_ROOT)
    _ensure_root_dir(PRIVATE_PLUGINS_ROOT)
    _ensure_root_dir(SHARED_WIKI_ROOT)
    _ensure_root_dir(PRIVATE_SKILLS_ROOT)
    _ensure_root_dir(SHARED_MEMORY_ROOT)
    _ensure_root_dir(SHARED_NODE_DATA_ROOT)


def _parent_hermes_home_source() -> Path:
    canonical = PARENT_HERMES_HOME
    if canonical.exists():
        try:
            if any(canonical.iterdir()):
                return canonical
        except Exception:
            pass
    raise CloneManagerError(f"could not locate orchestrator state source: {PARENT_HERMES_HOME}")


def _orchestrator_cron_host_dir(clone_name: str = "orchestrator") -> Path:
    return SHARED_CRONS_ROOT / clone_name


def _orchestrator_backup_cron_script_path() -> Path:
    return _orchestrator_cron_host_dir("orchestrator") / ORCHESTRATOR_BACKUP_CRON_SCRIPT


def _orchestrator_backup_cron_script_content() -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "\n"
        "# Daily backup policy (00:00 America/Sao_Paulo):\n"
        "# - Keep only the latest 3 archives under /local/backups\n"
        "# - Prune old request_dump_* files before archiving\n"
        "export NODE_TIME_ZONE=\"${NODE_TIME_ZONE:-America/Sao_Paulo}\"\n"
        "export HERMES_TIMEZONE=\"${HERMES_TIMEZONE:-${NODE_TIME_ZONE}}\"\n"
        "export TZ=\"${TZ:-${HERMES_TIMEZONE}}\"\n"
        "export HERMES_BACKUP_KEEP_LAST=\"${HERMES_BACKUP_KEEP_LAST:-3}\"\n"
        "export HERMES_REQUEST_DUMP_KEEP_DAYS=\"${HERMES_REQUEST_DUMP_KEEP_DAYS:-14}\"\n"
        "export HERMES_REQUEST_DUMP_KEEP_LAST=\"${HERMES_REQUEST_DUMP_KEEP_LAST:-200}\"\n"
        "\n"
        "/local/scripts/public/clone/horc.sh backup all\n"
    )


def _ensure_orchestrator_backup_cron_script() -> Path:
    cron_dir = _orchestrator_cron_host_dir("orchestrator")
    cron_dir.mkdir(parents=True, exist_ok=True)
    script_path = _orchestrator_backup_cron_script_path()
    content = _orchestrator_backup_cron_script_content()
    current = script_path.read_text(encoding="utf-8") if script_path.exists() else ""
    if current != content:
        script_path.write_text(content, encoding="utf-8")
    try:
        script_path.chmod(0o755)
    except Exception:
        pass

    schedule_path = cron_dir / "backup_daily_brt.cron"
    schedule_content = (
        "# Cron schedule (BRT): daily at 00:00\n"
        "CRON_TZ=America/Sao_Paulo\n"
        "0 0 * * * /local/crons/orchestrator/backup_daily_brt.sh\n"
    )
    if not schedule_path.exists() or schedule_path.read_text(encoding="utf-8") != schedule_content:
        schedule_path.write_text(schedule_content, encoding="utf-8")
    try:
        schedule_path.chmod(0o644)
    except Exception:
        pass

    return script_path


def _orchestrator_memory_home(clone_name: str = "orchestrator") -> Path:
    return SHARED_MEMORY_ROOT / "openviking" / clone_name


def _node_log_dir(clone_name: str) -> Path:
    return NODE_LOG_ROOT / clone_name


def _node_attention_dir(clone_name: str) -> Path:
    return ATTENTION_LOG_ROOT / clone_name


def _node_hermes_log_dir(clone_name: str) -> Path:
    return _node_log_dir(clone_name) / "hermes"


def _canonical_management_log_path(clone_name: str) -> Path:
    return _node_log_dir(clone_name) / "management.log"


def _canonical_runtime_log_path(clone_name: str) -> Path:
    return _node_log_dir(clone_name) / "runtime.log"


def _canonical_attention_log_path(clone_name: str) -> Path:
    return _node_attention_dir(clone_name) / "warning-plus.log"


def _append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.open("a", encoding="utf-8").write(line)


def _link_attention_errors_file(clone_name: str) -> None:
    """Expose attention/hermes-errors.log as a stable regular file path.

    Prefer hardlink (same inode) so editors open it as a normal file while it
    still reflects the canonical hermes/errors.log content.
    """
    source = _node_hermes_log_dir(clone_name) / "errors.log"
    target = _node_attention_dir(clone_name) / "hermes-errors.log"

    source.parent.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    source.touch(exist_ok=True)

    if target.exists() or target.is_symlink():
        try:
            if target.is_file() and not target.is_symlink():
                if source.exists() and target.stat().st_ino == source.stat().st_ino:
                    return
        except Exception:
            pass
        _remove_path(target)

    try:
        os.link(source, target)
        return
    except Exception:
        pass

    # Fallback to symlink when hardlink is unavailable.
    try:
        _set_symlink(target, source)
    except Exception:
        pass


def _ensure_node_log_topology(
    clone_name: str,
    clone_root: Path | None = None,
    *,
    migrate_clone_paths: bool = False,
    link_clone_hermes_logs: bool = True,
) -> None:
    node_dir = _node_log_dir(clone_name)
    attention_dir = _node_attention_dir(clone_name)
    hermes_dir = _node_hermes_log_dir(clone_name)
    node_dir.mkdir(parents=True, exist_ok=True)
    attention_dir.mkdir(parents=True, exist_ok=True)
    hermes_dir.mkdir(parents=True, exist_ok=True)
    for seed_file in (
        _canonical_management_log_path(clone_name),
        _canonical_runtime_log_path(clone_name),
        _canonical_attention_log_path(clone_name),
        _node_hermes_log_dir(clone_name) / "agent.log",
        _node_hermes_log_dir(clone_name) / "errors.log",
        _node_hermes_log_dir(clone_name) / "gateway.log",
    ):
        try:
            seed_file.parent.mkdir(parents=True, exist_ok=True)
            seed_file.touch(exist_ok=True)
        except Exception:
            pass

    _link_attention_errors_file(clone_name)

    if not migrate_clone_paths:
        return

    if clone_root is None or not clone_root.exists():
        return

    hermes_home = clone_root / ".hermes"
    if hermes_home.exists() and hermes_home.is_dir():
        hermes_logs = hermes_home / "logs"
        if link_clone_hermes_logs:
            if hermes_logs.exists() and not hermes_logs.is_symlink():
                if hermes_logs.is_dir():
                    _sync_dir(hermes_logs, hermes_dir, delete=False)
                _remove_path(hermes_logs)
            try:
                _set_symlink(hermes_logs, hermes_dir)
            except Exception:
                pass
        else:
            if hermes_logs.is_symlink():
                _remove_path(hermes_logs)
            hermes_logs.mkdir(parents=True, exist_ok=True)
    _link_attention_errors_file(clone_name)


def _append_attention_if_needed(clone_name: str, line: str) -> None:
    if ATTENTION_LINE_RE.search(line) is None:
        return
    attention_log = _canonical_attention_log_path(clone_name)
    _append_line(attention_log, line)


def _log(clone_name: str, message: str) -> None:
    _ensure_node_log_topology(clone_name)
    line = f"[{_utc_now()}] {message}\n"
    log_path = _canonical_management_log_path(clone_name)
    try:
        _append_line(log_path, line)
    except PermissionError as exc:
        raise CloneManagerError(f"unable to write log file for {clone_name}: {log_path}") from exc
    _append_attention_if_needed(clone_name, line)


def _log_spawn_event(clone_name: str, phase: str, action: str, detail: str = "") -> None:
    """Deterministic spawn event logging for observability and replay."""
    _ensure_node_log_topology(clone_name)
    msg = f"[{_utc_now()}] [SPAWN] phase={phase} action={action}"
    if detail:
        msg += f" detail={detail}"
    msg += "\n"
    log_path = _canonical_management_log_path(clone_name)
    try:
        _append_line(log_path, msg)
    except PermissionError as exc:
        raise CloneManagerError(f"unable to write spawn log file for {clone_name}: {log_path}") from exc
    _append_attention_if_needed(clone_name, msg)


def _management_log_path(clone_name: str) -> Path:
    return _canonical_management_log_path(clone_name)


def _attention_log_path(clone_name: str) -> Path:
    canonical = _canonical_attention_log_path(clone_name)
    if canonical.exists():
        return canonical
    return canonical


def _clone_hermes_log_dir(clone_name: str, clone_root: Path | None = None) -> Path:
    canonical = _node_hermes_log_dir(clone_name)
    if canonical.exists():
        return canonical
    root = clone_root
    if root is None:
        try:
            root = _clone_root_path(clone_name)
        except Exception:
            root = None
    if root is not None:
        legacy = root / ".hermes" / "logs"
        if legacy.exists():
            return legacy
    return canonical


def _clone_hermes_log_path(clone_name: str, filename: str, clone_root: Path | None = None) -> Path:
    return _clone_hermes_log_dir(clone_name, clone_root=clone_root) / filename


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


def _replace_or_append_env_line(text: str, key: str, value: str) -> str:
    line = f"{key}={value}"
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(line, text, count=1)
    if text and not text.endswith("\n"):
        text += "\n"
    return f"{text}{line}\n"


def _orchestrator_env_template() -> tuple[Path, str]:
    if ORCHESTRATOR_ENV_TEMPLATE_PATH.exists():
        return ORCHESTRATOR_ENV_TEMPLATE_PATH, ORCHESTRATOR_ENV_TEMPLATE_PATH.read_text(encoding="utf-8")

    if NODE_ENV_TEMPLATE_PATH.exists():
        text = NODE_ENV_TEMPLATE_PATH.read_text(encoding="utf-8")
        text = _replace_or_append_env_line(text, "NODE_STATE", "1")
        text = _replace_or_append_env_line(text, "NODE_STATE_FROM_BACKUP_PATH", "''")
        text = _replace_or_append_env_line(text, "OPENVIKING_ENDPOINT", "http://127.0.0.1:1933")
        text = _replace_or_append_env_line(text, "CAMOFOX_URL", "http://127.0.0.1:9377")
        return NODE_ENV_TEMPLATE_PATH, text

    raise CloneManagerError(
        "orchestrator env missing and no template found. "
        f"Tried: {ORCHESTRATOR_ENV_TEMPLATE_PATH}, {NODE_ENV_TEMPLATE_PATH}"
    )


def _ensure_clone_env_file(clone_name: str) -> Dict[str, Any]:
    env_path = _clone_env_path(clone_name)
    if env_path.exists():
        return {
            "created": False,
            "clone_name": clone_name,
            "env_path": str(env_path),
            "template_path": "",
            "reason": "already_exists",
        }

    if clone_name != "orchestrator":
        return {
            "created": False,
            "clone_name": clone_name,
            "env_path": str(env_path),
            "template_path": "",
            "reason": "missing_non_orchestrator_env",
        }

    template_path, template_text = _orchestrator_env_template()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    final_text = template_text if template_text.endswith("\n") else f"{template_text}\n"
    env_path.write_text(final_text, encoding="utf-8")
    _log(clone_name, f"auto-created missing env from template: {template_path}")
    return {
        "created": True,
        "clone_name": clone_name,
        "env_path": str(env_path),
        "template_path": str(template_path),
        "reason": "auto_created_orchestrator_env",
    }


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
    """Resolve canonical Discord home channel without mutating profile env."""
    env = _read_env_file(env_path)
    source = str(env.get("DISCORD_HOME_CHANNEL_ID", "") or "").strip()
    current = str(env.get("DISCORD_HOME_CHANNEL", "") or "").strip()
    effective = _effective_discord_home_channel(env)

    if source and not current:
        _log(
            clone_name,
            f"discord home channel sync: using legacy DISCORD_HOME_CHANNEL_ID as runtime DISCORD_HOME_CHANNEL ({source})",
        )

    return {
        "mapped": bool(source and not current),
        "changed": False,
        "source": source,
        "effective": effective,
    }


def _sync_restart_reboot_env(clone_name: str, env_path: Path) -> Dict[str, Any]:
    """Resolve restart/reboot runtime defaults without mutating profile env."""
    env = _read_env_file(env_path)
    effective = _effective_restart_reboot_env(env)
    restart_cmd = effective["restart_cmd"]
    reboot_cmd = effective["reboot_cmd"]
    restart_delay = effective["restart_delay_sec"]
    reboot_delay = effective["reboot_delay_sec"]

    _log(
        clone_name,
        "restart/reboot env sync: "
        f"runtime restart_delay={restart_delay} reboot_delay={reboot_delay}",
    )

    return {
        "changed": False,
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


def _to_archive_relative(path: Path) -> str:
    local_root = Path("/local")
    try:
        return str(path.resolve().relative_to(local_root))
    except Exception:
        return path.name


def _archive_add_path(
    tf: tarfile.TarFile,
    source: Path,
    *,
    archive_name: str | None = None,
    exclude_relative_prefixes: tuple[str, ...] = (),
) -> str | None:
    if not source.exists():
        return None
    if archive_name:
        arcname = str(PurePosixPath(str(archive_name).strip("/")))
    else:
        arcname = _to_archive_relative(source)
    archive_source = source
    if source.is_symlink():
        try:
            resolved = source.resolve()
            if resolved.exists():
                archive_source = resolved
        except Exception:
            archive_source = source

    cleaned_prefixes = tuple(
        str(PurePosixPath(prefix.strip("/"))) for prefix in exclude_relative_prefixes if str(prefix or "").strip()
    )
    if not cleaned_prefixes:
        tf.add(str(archive_source), arcname=arcname, recursive=True)
        return arcname

    def _filter(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
        raw_name = str(member.name or "").strip()
        if not raw_name:
            return member
        if raw_name == arcname:
            return member
        if raw_name.startswith(f"{arcname}/"):
            rel_name = raw_name[len(arcname) + 1 :]
        else:
            rel_name = raw_name
        rel_posix = str(PurePosixPath(rel_name))
        rel_parts = PurePosixPath(rel_posix).parts
        if "__pycache__" in rel_parts or rel_posix.endswith((".pyc", ".pyo")):
            return None
        for prefix in cleaned_prefixes:
            if (
                rel_posix == prefix
                or rel_posix.startswith(f"{prefix}/")
                or (prefix and prefix[-1] in {"-", "_"} and rel_posix.startswith(prefix))
            ):
                return None
        return member

    tf.add(str(archive_source), arcname=arcname, recursive=True, filter=_filter)
    return arcname


def _resolve_backup_path(raw_path: str) -> Path:
    value = str(raw_path or "").strip()
    if not value:
        raise CloneManagerError("backup/restore path is required")

    probe = Path(value).expanduser()
    candidates = [probe]
    if not probe.is_absolute():
        candidates.append(BACKUPS_ROOT / probe)

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    tried = ", ".join(str(c) for c in candidates)
    raise CloneManagerError(f"backup path not found: {value} (tried: {tried})")


def _int_env(name: str, default: int) -> int:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _prune_request_dump_files(
    node: str,
    node_root: Path,
    *,
    keep_last: int,
    keep_days: int,
) -> Dict[str, Any]:
    sessions_dir = node_root / ".hermes" / "sessions"
    if not sessions_dir.exists() or not sessions_dir.is_dir():
        return {
            "node": node,
            "sessions_dir": str(sessions_dir),
            "scanned": 0,
            "removed": 0,
            "removed_bytes": 0,
            "kept": 0,
            "keep_last": max(0, keep_last),
            "keep_days": max(0, keep_days),
            "policy_enabled": False,
        }

    keep_last = max(0, int(keep_last))
    keep_days = max(0, int(keep_days))
    policy_enabled = keep_last > 0 or keep_days > 0
    if not policy_enabled:
        files = [
            path
            for path in sessions_dir.glob("request_dump_*")
            if path.is_file()
        ]
        return {
            "node": node,
            "sessions_dir": str(sessions_dir),
            "scanned": len(files),
            "removed": 0,
            "removed_bytes": 0,
            "kept": len(files),
            "keep_last": keep_last,
            "keep_days": keep_days,
            "policy_enabled": False,
        }

    snapshots: list[tuple[Path, float, int]] = []
    for path in sessions_dir.glob("request_dump_*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except Exception:
            continue
        snapshots.append((path, float(stat.st_mtime), int(stat.st_size)))

    snapshots.sort(key=lambda item: item[1], reverse=True)
    cutoff_ts = (
        time.time() - (keep_days * 86400)
        if keep_days > 0
        else None
    )
    removed = 0
    removed_bytes = 0

    for idx, (path, mtime, size) in enumerate(snapshots):
        should_remove = False
        if keep_last > 0 and idx >= keep_last:
            should_remove = True
        if cutoff_ts is not None and mtime < cutoff_ts:
            should_remove = True
        if not should_remove:
            continue
        try:
            path.unlink()
            removed += 1
            removed_bytes += size
        except Exception:
            continue

    scanned = len(snapshots)
    kept = max(0, scanned - removed)
    return {
        "node": node,
        "sessions_dir": str(sessions_dir),
        "scanned": scanned,
        "removed": removed,
        "removed_bytes": removed_bytes,
        "kept": kept,
        "keep_last": keep_last,
        "keep_days": keep_days,
        "policy_enabled": policy_enabled,
    }


def _prune_backup_archives(*, keep_last: int) -> Dict[str, Any]:
    keep_last = max(0, int(keep_last))
    candidates: list[Path] = []
    seen: set[str] = set()
    for pattern in ("horc-backup-*.tar.gz", "horc-backup-*.tgz", "horc-backup-*.tar"):
        for path in BACKUPS_ROOT.glob(pattern):
            if not path.is_file():
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            candidates.append(path)

    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if keep_last <= 0:
        return {
            "enabled": False,
            "keep_last": 0,
            "scanned": len(candidates),
            "deleted": 0,
            "errors": {},
        }

    stale = candidates[keep_last:]
    deleted = 0
    errors: Dict[str, str] = {}
    for path in stale:
        try:
            path.unlink()
            deleted += 1
        except Exception as exc:
            errors[str(path)] = str(exc)

    return {
        "enabled": True,
        "keep_last": keep_last,
        "scanned": len(candidates),
        "deleted": deleted,
        "errors": errors,
    }


def _is_safe_archive_member(name: str) -> bool:
    clean = str(name or "").strip()
    if not clean:
        return False
    while clean.startswith("./"):
        clean = clean[2:]
    if not clean:
        return False
    posix = PurePosixPath(clean)
    if posix.is_absolute():
        return False
    return ".." not in posix.parts


def _extract_backup_archive(archive_path: Path, destination: Path) -> Dict[str, Any]:
    if not tarfile.is_tarfile(archive_path):
        raise CloneManagerError(f"backup file is not a valid tar archive: {archive_path}")

    nodes: set[str] = set()
    env_nodes: set[str] = set()
    registry_present = False
    plugins_private_present = False
    scripts_private_present = False
    crons_present = False
    skills_present = False
    legacy_private_present = False
    datas_present = False
    legacy_data_present = False
    runtime_seed_hermes_present = False
    runtime_seed_venv_present = False
    runtime_seed_uv_present = False
    member_count = 0

    with tarfile.open(archive_path, "r:*") as tf:
        members = tf.getmembers()
        for member in members:
            member_count += 1
            member_name = str(member.name or "").strip()
            if not member_name:
                continue
            if not _is_safe_archive_member(member_name):
                raise CloneManagerError(
                    f"unsafe path inside backup archive: {member_name}"
                )

            clean = member_name
            while clean.startswith("./"):
                clean = clean[2:]
            parts = PurePosixPath(clean).parts
            if not parts:
                continue
            if parts[0] == "agents":
                if len(parts) == 2 and parts[1] == "registry.json":
                    registry_present = True
                    continue
                if len(parts) >= 3 and parts[1] == "envs" and parts[2].endswith(".env"):
                    env_nodes.add(_normalize_clone_name(parts[2][:-4]))
                    continue
                if len(parts) >= 3 and parts[1] == "nodes":
                    nodes.add(_normalize_clone_name(parts[2]))
                    continue
                if len(parts) == 1:
                    continue
                if len(parts) >= 2 and parts[1] == "private":
                    legacy_private_present = True
                    continue
                if len(parts) >= 2 and parts[1] in {"envs", "nodes"}:
                    continue
                raise CloneManagerError(
                    f"unsupported path in backup archive: {member_name}"
                )

            if parts[0] == "plugins":
                if len(parts) == 1:
                    continue
                if parts[1] == "private":
                    plugins_private_present = True
                    continue
                raise CloneManagerError(
                    f"unsupported path in backup archive: {member_name}"
                )

            if parts[0] == "skills":
                skills_present = True
                continue

            if parts[0] == "crons":
                crons_present = True
                continue

            if parts[0] == "scripts":
                if len(parts) == 1:
                    continue
                if parts[1] == "private":
                    scripts_private_present = True
                    continue
                raise CloneManagerError(
                    f"unsupported path in backup archive: {member_name}"
                )

            if parts[0] == "datas":
                datas_present = True
                continue

            if parts[0] == "data":
                legacy_data_present = True
                continue

            if parts[0] == "runtime_seed":
                if len(parts) == 1:
                    continue
                if parts[1] == "hermes-agent":
                    runtime_seed_hermes_present = True
                    continue
                if parts[1] == "venv":
                    runtime_seed_venv_present = True
                    continue
                if parts[1] == "uv":
                    runtime_seed_uv_present = True
                    continue
                raise CloneManagerError(
                    f"unsupported path in backup archive: {member_name}"
                )

            raise CloneManagerError(
                f"unsupported path in backup archive: {member_name}"
            )

        tf.extractall(destination)

    return {
        "nodes": sorted(nodes),
        "env_nodes": sorted(env_nodes),
        "registry_present": registry_present,
        "plugins_private_present": plugins_private_present,
        "scripts_private_present": scripts_private_present,
        "crons_present": crons_present,
        "skills_present": skills_present,
        "legacy_private_present": legacy_private_present,
        "datas_present": datas_present,
        "legacy_data_present": legacy_data_present,
        "runtime_seed_hermes_present": runtime_seed_hermes_present,
        "runtime_seed_venv_present": runtime_seed_venv_present,
        "runtime_seed_uv_present": runtime_seed_uv_present,
        "member_count": member_count,
    }


def _load_registry() -> Dict[str, Any]:
    source = REGISTRY_PATH
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


def _docker_mounts(container_name: str) -> list[Dict[str, Any]]:
    if not _docker_exists(container_name):
        return []
    proc = _run(
        ["docker", "inspect", container_name, "--format", "{{json .Mounts}}"],
        check=False,
    )
    raw = (proc.stdout or "").strip()
    if proc.returncode != 0 or not raw:
        return []
    try:
        mounts = json.loads(raw)
    except Exception:
        return []
    if not isinstance(mounts, list):
        return []

    normalized: list[Dict[str, Any]] = []
    for item in mounts:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "source": str(item.get("Source") or ""),
                "destination": str(item.get("Destination") or ""),
                "rw": bool(item.get("RW")),
                "mode": str(item.get("Mode") or ""),
            }
        )
    return normalized


def _normalized_path_str(path: Path | str) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    try:
        return str(Path(raw).resolve())
    except Exception:
        return os.path.normpath(raw)


def _required_worker_mount_specs(clone_name: str, clone_root: Path) -> list[Dict[str, Any]]:
    return [
        {
            "destination": "/local",
            "source": str(clone_root),
            "read_only": False,
        },
        {
            "destination": "/local/data",
            "source": str(_shared_node_data_dir(clone_name)),
            "read_only": False,
        },
        {
            "destination": f"/local/logs/nodes/{clone_name}",
            "source": str(_node_log_dir(clone_name)),
            "read_only": False,
        },
        {
            "destination": f"/local/logs/attention/nodes/{clone_name}",
            "source": str(_node_attention_dir(clone_name)),
            "read_only": False,
        },
        {
            "destination": "/local/.hermes/logs",
            "source": str(_node_hermes_log_dir(clone_name)),
            "read_only": False,
        },
        {
            "destination": "/local/scripts/public",
            "source": str(SHARED_SCRIPTS_ROOT),
            "read_only": True,
        },
        {
            "destination": "/local/scripts/private",
            "source": str(PRIVATE_SCRIPTS_ROOT),
            "read_only": False,
        },
        {
            "destination": "/local/plugins/public",
            "source": str(SHARED_PLUGINS_ROOT),
            "read_only": True,
        },
        {
            "destination": "/local/plugins/private",
            "source": str(PRIVATE_PLUGINS_ROOT),
            "read_only": False,
        },
        {
            "destination": "/local/cron",
            "source": str(SHARED_CRONS_ROOT / clone_name),
            "read_only": False,
        },
        {
            "destination": NODE_SKILLS_PATH_IN_CONTAINER,
            "source": str(PRIVATE_SKILLS_ROOT),
            "read_only": False,
        },
    ]


def _missing_required_worker_mounts(container_name: str, clone_name: str, clone_root: Path) -> list[str]:
    mounts = _docker_mounts(container_name)
    if not mounts:
        return ["docker inspect mount data unavailable"]

    by_dest = {
        str(mount.get("destination") or "").strip(): mount
        for mount in mounts
        if str(mount.get("destination") or "").strip()
    }
    missing: list[str] = []

    for spec in _required_worker_mount_specs(clone_name, clone_root):
        destination = str(spec["destination"])
        expected_source = _normalized_path_str(str(spec["source"]))
        expected_ro = bool(spec["read_only"])
        actual = by_dest.get(destination)
        if actual is None:
            missing.append(f"{destination} (missing)")
            continue

        actual_source = _normalized_path_str(str(actual.get("source") or ""))
        if expected_source and actual_source != expected_source:
            missing.append(
                f"{destination} (source mismatch: expected={expected_source} actual={actual_source})"
            )
            continue

        actual_ro = not bool(actual.get("rw"))
        if actual_ro != expected_ro:
            missing.append(
                f"{destination} (mode mismatch: expected={'ro' if expected_ro else 'rw'} actual={'ro' if actual_ro else 'rw'})"
            )

    return missing


def _normalize_clone_name(raw: str) -> str:
    name = str(raw or "").strip().lower()
    if not VALID_NAME_RE.fullmatch(name):
        raise CloneManagerError(
            "invalid clone name. Use lowercase letters, numbers, and dashes "
            "(2-63 chars), e.g. hermes-catatau"
        )
    return name


def _clone_env_path(clone_name: str) -> Path:
    return ENVS_ROOT / f"{clone_name}.env"


def _clone_root_path(clone_name: str) -> Path:
    return CLONES_ROOT / clone_name


def _shared_node_data_dir(clone_name: str) -> Path:
    return SHARED_NODE_DATA_ROOT / clone_name


def _legacy_node_data_dir(clone_root: Path) -> Path:
    return clone_root / "data"


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


def _clone_runtime_contract_path(clone_root: Path) -> Path:
    return clone_root / NODE_RUNTIME_CONTRACT_REL


def _clone_workspace_runtime_contract_path(clone_root: Path) -> Path:
    return clone_root / NODE_RUNTIME_CONTRACT_WORKSPACE_REL


def _resolve_state_mode_info(env: Dict[str, str]) -> tuple[int | None, str]:
    try:
        mode = _extract_state_mode(env)
        return mode, STATE_LABELS.get(mode, "unknown")
    except Exception:
        raw = _env_first_nonempty(env, "NODE_STATE", "CLONE_STATE")
        if not raw:
            return None, "unknown"
        try:
            mode = int(raw)
        except Exception:
            return None, "invalid"
        return mode, STATE_LABELS.get(mode, "invalid")


def _build_node_runtime_contract_text(clone_name: str, env: Dict[str, str]) -> str:
    state_code, state_label = _resolve_state_mode_info(env)
    role = "orchestrator-control-plane" if state_code == 1 else "worker-node"
    node_timezone = _env_first_nonempty(env, "NODE_TIME_ZONE", "HERMES_TIMEZONE") or "system-default"
    lines = [
        "# Node Runtime Contract",
        "",
        "This file defines the operational contract for this node in the Hermes",
        "Orchestrator topology.",
        "",
        f"- Node: {clone_name}",
        f"- Role: {role}",
        f"- Bootstrap mode: NODE_STATE={state_code if state_code is not None else '?'} ({state_label})",
        f"- Shared plugins root (host): {SHARED_PLUGINS_ROOT}",
        f"- Private plugins root (host): {PRIVATE_PLUGINS_ROOT}",
        f"- Shared scripts root (host): {SHARED_SCRIPTS_ROOT}",
        f"- Private scripts root (host): {PRIVATE_SCRIPTS_ROOT}",
        f"- Shared crons root (host): {SHARED_CRONS_ROOT}",
        f"- Node timezone: {node_timezone} (exported as HERMES_TIMEZONE)",
        "- Shared container plugin mounts: /local/plugins/public (ro), /local/plugins/private (rw)",
        "- Shared container script mounts: /local/scripts/public (ro), /local/scripts/private (rw)",
        f"- Bootstrap metadata: /local/.clone-meta/bootstrap.json",
        f"- Prestart patch pipeline: {SHARED_PLUGINS_ROOT}/hermes-core/scripts/prestart_reapply.sh",
        "",
        "## Framework Roles",
        "- Orchestrator node owns shared framework assets and node lifecycle controls.",
        "- Worker nodes execute domain tasks and provide technical proposals/improvements.",
        "- Plugins and framework patches are shared infrastructure, not per-node app code.",
        "",
        "## Plugin Governance",
        "- Workers must treat /local/plugins/{public,private} and /local/scripts/{public,private} as orchestrator-managed assets.",
        "- Workers should not claim plugin/framework changes are applied unless orchestrator executes them.",
        "- Workers should propose exact file diffs, rollout plan, rollback plan, and verification steps.",
        "- Orchestrator should apply approved shared changes, restart affected nodes, and verify outcomes.",
        "",
        "## Collaboration Protocol",
        "1. Detect issue or improvement opportunity.",
        "2. Draft a scoped change proposal (what/why/risk/tests).",
        "3. Ask orchestrator to execute shared plugin/framework mutations.",
        "4. Validate behavior after restart and document residual risk.",
        "",
    ]
    return "\n".join(lines)


def _build_node_governance_prompt(clone_name: str, env: Dict[str, str]) -> str:
    state_code, state_label = _resolve_state_mode_info(env)
    role = "orchestrator" if state_code == 1 else "worker"
    role_line = (
        "You own shared plugin/framework execution and rollout for the fleet."
        if state_code == 1
        else "Do not execute or claim direct shared plugin/framework mutations; escalate to orchestrator."
    )
    return (
        f"[Node governance contract]\n"
        f"Node={clone_name}; role={role}; NODE_STATE={state_code if state_code is not None else '?'} ({state_label}).\n"
        f"Shared framework assets live at {SHARED_PLUGINS_ROOT} and {SHARED_SCRIPTS_ROOT}; "
        "they are orchestrator-managed infrastructure.\n"
        f"{role_line}\n"
        "When proposing shared changes, provide exact file edits, rollout+rollback, and verification.\n"
        f"Bootstrap note: gateway startup runs {SHARED_PLUGINS_ROOT}/hermes-core/scripts/prestart_reapply.sh "
        "so plugin hooks are re-applied on restart.\n"
        "Reference contract file: /local/.hermes/NODE_RUNTIME_CONTRACT.md"
    ).strip()


def _write_node_runtime_contract(clone_root: Path, clone_name: str, env: Dict[str, str]) -> None:
    content = _build_node_runtime_contract_text(clone_name, env)
    hermes_path = _clone_runtime_contract_path(clone_root)
    workspace_path = _clone_workspace_runtime_contract_path(clone_root)

    for target in (hermes_path, workspace_path):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        try:
            target.chmod(0o644)
        except Exception:
            pass


def _is_truthy(value: Any) -> bool:
    raw = str(value or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _env_first_nonempty(env: Dict[str, str], *keys: str) -> str:
    for key in keys:
        value = str(env.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _env_truthy_prefer(env: Dict[str, str], primary: str, legacy: str) -> bool:
    primary_raw = str(env.get(primary, "") or "").strip()
    if primary_raw:
        return _is_truthy(primary_raw)
    legacy_raw = str(env.get(legacy, "") or "").strip()
    if legacy_raw:
        return _is_truthy(legacy_raw)
    return False


def _is_camofox_enabled_env(env: Dict[str, str]) -> bool:
    return _env_truthy_prefer(env, "CAMOFOX_ENABLED", "BROWSER_CAMOFOX")


def _is_openviking_enabled_env(env: Dict[str, str]) -> bool:
    return _env_truthy_prefer(env, "OPENVIKING_ENABLED", "MEMORY_OPENVIKING")


def _effective_discord_home_channel(env: Dict[str, str]) -> str:
    return _env_first_nonempty(env, "DISCORD_HOME_CHANNEL", "DISCORD_HOME_CHANNEL_ID")


def _resolve_openviking_identity(env: Dict[str, str], clone_name: str) -> tuple[str, str]:
    account = _env_first_nonempty(env, "OPENVIKING_ACCOUNT", "OPENVIKING_ACCOUNT_DEFAULT")
    user = _env_first_nonempty(env, "OPENVIKING_USER", "OPENVIKING_USER_DEFAULT")

    if not account and not user:
        account = clone_name
        user = clone_name
    elif account and not user:
        user = account
    elif user and not account:
        account = user

    return account, user


def _effective_restart_reboot_env(env: Dict[str, str]) -> Dict[str, str]:
    restart_cmd = str(env.get("COLMEIO_DISCORD_RESTART_CMD", "") or "").strip()
    reboot_cmd = str(env.get("COLMEIO_DISCORD_REBOOT_CMD", "") or "").strip()
    restart_delay = str(env.get("COLMEIO_DISCORD_RESTART_DELAY_SEC", "") or "").strip()
    reboot_delay = str(env.get("COLMEIO_DISCORD_REBOOT_DELAY_SEC", "") or "").strip()

    if not restart_cmd or restart_cmd in {"kill -TERM 1", "kill -KILL 1"}:
        restart_cmd = DISCORD_DEFAULT_RESTART_CMD
    if not reboot_cmd or reboot_cmd in {"kill -TERM 1", "kill -KILL 1"}:
        reboot_cmd = DISCORD_DEFAULT_REBOOT_CMD
    if not restart_delay:
        restart_delay = DISCORD_DEFAULT_RESTART_DELAY_SEC
    if not reboot_delay:
        reboot_delay = DISCORD_DEFAULT_REBOOT_DELAY_SEC

    return {
        "restart_cmd": restart_cmd,
        "reboot_cmd": reboot_cmd,
        "restart_delay_sec": restart_delay,
        "reboot_delay_sec": reboot_delay,
    }


def _default_model_provider_from_env(env: Dict[str, str]) -> str:
    return _env_first_nonempty(
        env,
        "NODE_AGENT_DEFAULT_MODEL_PROVIDER",
        "DEFAULT_MODEL_PROVIDER",
        "HERMES_INFERENCE_PROVIDER",
    )


def _default_model_name_from_env(env: Dict[str, str]) -> str:
    return _env_first_nonempty(env, "NODE_AGENT_DEFAULT_MODEL", "DEFAULT_MODEL")


def _fallback_model_provider_from_env(env: Dict[str, str]) -> str:
    return _env_first_nonempty(env, "NODE_AGENT_FALLBACK_MODEL_PROVIDER", "FALLBACK_MODEL_PROVIDER")


def _fallback_model_name_from_env(env: Dict[str, str]) -> str:
    return _env_first_nonempty(env, "NODE_AGENT_FALLBACK_MODEL", "FALLBACK_MODEL")


def _effective_hermes_yolo_mode(env: Dict[str, str]) -> str:
    """Return the canonical YOLO toggle from profile env (supports legacy alias)."""
    return _env_first_nonempty(
        env,
        "NODE_HERMES_YOLO_MODE",
        "HERMES_YOLO_MODE",
    )


def _runtime_env_overrides(clone_name: str, env: Dict[str, str]) -> Dict[str, str]:
    overrides: Dict[str, str] = {}
    node_logs_dir = _node_log_dir(clone_name)
    overrides["NODE_NAME"] = _env_first_nonempty(env, "NODE_NAME") or clone_name
    node_timezone = _env_first_nonempty(env, "NODE_TIME_ZONE", "HERMES_TIMEZONE")
    if node_timezone:
        overrides["HERMES_TIMEZONE"] = node_timezone
        overrides["TZ"] = node_timezone

    overrides["COLMEIO_PROJECT_DIR"] = (
        _env_first_nonempty(env, "COLMEIO_PROJECT_DIR") or NODE_WORKSPACE_ROOT_IN_CONTAINER
    )
    overrides["COLMEIO_DB_PATH"] = (
        _env_first_nonempty(env, "COLMEIO_DB_PATH") or NODE_WORKSPACE_DB_PATH_IN_CONTAINER
    )
    overrides["COLMEIO_LOGS_DIR"] = (
        _env_first_nonempty(env, "COLMEIO_LOGS_DIR") or str(node_logs_dir)
    )
    overrides["HERMES_DATA_DIR"] = (
        _env_first_nonempty(env, "HERMES_DATA_DIR") or "/local/data"
    )
    overrides["DISCORD_USERS_DB"] = (
        _env_first_nonempty(env, "DISCORD_USERS_DB") or NODE_WORKSPACE_DISCORD_USERS_DB_IN_CONTAINER
    )
    overrides["DISCORD_SETTINGS_FILE"] = (
        _env_first_nonempty(env, "DISCORD_SETTINGS_FILE") or NODE_WORKSPACE_DISCORD_SETTINGS_IN_CONTAINER
    )

    discord_home = _effective_discord_home_channel(env)
    if discord_home:
        overrides["DISCORD_HOME_CHANNEL"] = discord_home

    restart_reboot = _effective_restart_reboot_env(env)
    overrides["COLMEIO_DISCORD_RESTART_CMD"] = restart_reboot["restart_cmd"]
    overrides["COLMEIO_DISCORD_REBOOT_CMD"] = restart_reboot["reboot_cmd"]
    overrides["COLMEIO_DISCORD_RESTART_DELAY_SEC"] = restart_reboot["restart_delay_sec"]
    overrides["COLMEIO_DISCORD_REBOOT_DELAY_SEC"] = restart_reboot["reboot_delay_sec"]

    overrides["CAMOFOX_ENABLED"] = "1" if _is_camofox_enabled_env(env) else "0"
    overrides["OPENVIKING_ENABLED"] = "1" if _is_openviking_enabled_env(env) else "0"
    if _is_camofox_enabled_env(env):
        overrides["CAMOFOX_URL"] = _env_first_nonempty(env, "CAMOFOX_URL") or CAMOFOX_DEFAULT_URL_CLONE
    if _is_openviking_enabled_env(env):
        overrides["OPENVIKING_ENDPOINT"] = (
            _env_first_nonempty(env, "OPENVIKING_ENDPOINT") or OPENVIKING_DEFAULT_ENDPOINT_CLONE
        )

    openviking_account, openviking_user = _resolve_openviking_identity(env, clone_name)
    overrides["OPENVIKING_ACCOUNT"] = openviking_account
    overrides["OPENVIKING_USER"] = openviking_user

    yolo_mode = _effective_hermes_yolo_mode(env)
    if yolo_mode:
        overrides["HERMES_YOLO_MODE"] = yolo_mode

    governance_prompt = _build_node_governance_prompt(clone_name, env)
    existing_prompt = _env_first_nonempty(env, "HERMES_EPHEMERAL_SYSTEM_PROMPT")
    if existing_prompt:
        overrides["HERMES_EPHEMERAL_SYSTEM_PROMPT"] = (
            f"{existing_prompt}\n\n{governance_prompt}"
        ).strip()
    else:
        overrides["HERMES_EPHEMERAL_SYSTEM_PROMPT"] = governance_prompt
    overrides["HERMES_NODE_RUNTIME_CONTRACT_PATH"] = "/local/.hermes/NODE_RUNTIME_CONTRACT.md"
    overrides["HERMES_NODE_BOOTSTRAP_META_PATH"] = "/local/.clone-meta/bootstrap.json"

    return overrides


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


def _python_has_modules(python_bin: Path, modules: tuple[str, ...]) -> bool:
    for module in modules:
        if not _python_has_module(python_bin, module):
            return False
    return True


def _host_python_candidates() -> list[Path]:
    """Bootstrap Python candidates (host-level, not tied to hermes-agent)."""
    configured = str(os.getenv("HERMES_CLONE_BOOTSTRAP_PYTHON", "") or "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())

    candidates.extend(
        [
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
    """Ensure orchestrator runtime is clone-local under node root."""
    clone_root = _clone_root_path(clone_name)
    runtime_agent_root = _orchestrator_runtime_agent_root(clone_root)
    runtime_venv = runtime_agent_root / ".venv"
    python_candidates = [
        runtime_venv / "bin" / "python3",
        runtime_venv / "bin" / "python",
    ]
    runtime_python = next((p for p in python_candidates if p.exists()), None)
    if runtime_python is not None and _python_has_modules(runtime_python, GATEWAY_REQUIRED_MODULES):
        return {
            "runtime_venv": str(runtime_venv),
            "runtime_python": str(runtime_python),
            "created": False,
            "installed_dependencies": False,
            "source": "clone_local_venv",
        }

    _seed_clone_runtime(clone_root, allow_parent_seed=True)
    runtime_python = next(
        (
            p
            for p in python_candidates
            if p.exists() and _python_has_modules(p, GATEWAY_REQUIRED_MODULES)
        ),
        None,
    )
    if runtime_python is None:
        required = ", ".join(GATEWAY_REQUIRED_MODULES)
        raise CloneManagerError(
            "orchestrator clone-local runtime missing required modules "
            f"({required}) at {runtime_venv}"
        )

    _log(clone_name, f"orchestrator runtime ready at {runtime_venv}")
    return {
        "runtime_venv": str(runtime_venv),
        "runtime_python": str(runtime_python),
        "created": True,
        "installed_dependencies": False,
        "source": "clone_local_seed",
    }


def _seed_venv_candidates() -> list[Path]:
    preferred = [
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


def _select_seed_venv_source(
    *,
    required_module: str | None = None,
    required_modules: tuple[str, ...] | None = None,
) -> Path:
    candidates = _seed_venv_candidates()

    if required_modules:
        for venv_dir in candidates:
            py = venv_dir / "bin" / "python"
            if _python_has_modules(py, required_modules):
                return venv_dir
    elif required_module:
        for venv_dir in candidates:
            py = venv_dir / "bin" / "python"
            if _python_has_module(py, required_module):
                return venv_dir

    for venv_dir in candidates:
        if (venv_dir / "bin" / "python").exists():
            return venv_dir

    raise CloneManagerError(
        "could not locate parent seed venv (expected one of "
        "/local/hermes-agent/.venv or /local/agents/nodes/orchestrator/hermes-agent/.venv)."
    )


def _clone_runtime_uv_path(clone_root: Path) -> Path:
    return clone_root / RUNTIME_UV_REL


def _clone_runtime_log_path(clone_name: str, clone_root: Path | None = None) -> Path:
    return _canonical_runtime_log_path(clone_name)


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
        f"chown -R -h {HOST_UID}:{HOST_GID} /clone",
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
    """Canonical orchestrator runtime code root.

    New topology uses clone-local `/hermes-agent` as the mutable runtime tree.
    Legacy `.runtime/hermes-agent` is still recognized for migration fallback.
    """
    local_copy = clone_root / "hermes-agent"
    if (local_copy / "gateway" / "run.py").exists():
        return local_copy

    legacy_runtime = clone_root / ".runtime" / "hermes-agent"
    if (legacy_runtime / "gateway" / "run.py").exists():
        return legacy_runtime

    return local_copy


def _prepare_orchestrator_runtime_agent_tree(
    clone_name: str,
    clone_root: Path,
    source_tree: Path,
) -> Path:
    """Sync orchestrator node-local runtime code tree for patching.

    NODE_STATE=1 must patch and run from the clone-local hermes-agent copy so
    `/local/hermes-agent` remains template-only.
    """
    runtime_root = clone_root / "hermes-agent"
    if runtime_root.is_symlink():
        _remove_path(runtime_root)
    runtime_root.parent.mkdir(parents=True, exist_ok=True)
    _seed_code_tree(source_tree, runtime_root, include_git=False)

    # Clean obsolete legacy runtime tree created by older layouts.
    legacy_runtime_root = clone_root / ".runtime" / "hermes-agent"
    if legacy_runtime_root.exists() or legacy_runtime_root.is_symlink():
        _remove_path(legacy_runtime_root)

    _log(
        clone_name,
        f"orchestrator runtime agent tree synced: source={source_tree} runtime={runtime_root}",
    )
    return runtime_root


def _worker_cron_host_dir(clone_name: str) -> Path:
    return SHARED_CRONS_ROOT / clone_name


def _is_wiki_enabled_env(env: Dict[str, str]) -> bool:
    return _is_truthy(env.get("NODE_WIKI_ENABLED", "0"))


def _ensure_shared_wiki_root() -> None:
    SHARED_WIKI_ROOT.parent.mkdir(parents=True, exist_ok=True)
    SHARED_WIKI_ROOT.mkdir(parents=True, exist_ok=True)


def _sync_node_wiki_link(clone_root: Path, env: Dict[str, str], *, containerized: bool) -> None:
    node_wiki = clone_root / "wiki"
    legacy_node_wiki_public = clone_root / "wiki-public"
    workspace_wiki = clone_root / "workspace" / "wiki"
    if _is_wiki_enabled_env(env):
        _ensure_shared_wiki_root()
        if containerized:
            if node_wiki.is_symlink():
                _remove_path(node_wiki)
            if node_wiki.exists() and not node_wiki.is_dir():
                _remove_path(node_wiki)
            node_wiki.mkdir(parents=True, exist_ok=True)
        else:
            _set_symlink(node_wiki, SHARED_WIKI_ROOT)
    elif node_wiki.exists() or node_wiki.is_symlink():
        _remove_path(node_wiki)

    # Legacy topology cleanup: nodes now expose a single wiki root.
    if legacy_node_wiki_public.exists() or legacy_node_wiki_public.is_symlink():
        _remove_path(legacy_node_wiki_public)

    # Always clean up the old workspace/wiki link from legacy layouts.
    if workspace_wiki.exists() or workspace_wiki.is_symlink():
        _remove_path(workspace_wiki)


def _ensure_worker_shared_mount_links(clone_root: Path, clone_name: str, *, refresh_mirrors: bool = True) -> None:
    """Ensure worker node host tree has deterministic plugin/script mount anchors.

    Worker nodes (colmeio, catatau, etc.) access shared plugins and scripts
    via bind mounts inside their containers
    (/local/plugins/public, /local/plugins/private, /local/scripts/public, /local/scripts/private).
    On the HOST side, clone_root/scripts/{public,private} is a visible mirror
    of canonical /local/scripts/{public,private} for easier inspection.
    Paths stay as real directories (not symlinks) because Docker cannot bind
    mount over symlink mountpoints.
    """
    anchor_notes: dict[str, str] = {
        "plugins": (
            "# Node Mount Anchor: plugins\n\n"
            "This directory is intentionally a host-side mount anchor.\n"
            "Containers read plugin content from bind mounts at:\n"
            "- /local/plugins/public (host: /local/plugins/public)\n"
            "- /local/plugins/private (host: /local/plugins/private)\n\n"
            "Why this can look empty on host:\n"
            "- Bind mounts overlay files inside the container namespace only.\n"
            "- Host-side node anchors stay mostly empty by design.\n"
        ),
        "scripts": (
            "# Node Mount Anchor: scripts\n\n"
            "This directory is a host-visible mirror of shared scripts.\n"
            "Canonical roots:\n"
            "- /local/scripts/public\n"
            "- /local/scripts/private\n\n"
            "Containers read those canonical roots via bind mounts.\n"
        ),
    }

    worker_crons = _worker_cron_host_dir(clone_name)
    worker_crons.mkdir(parents=True, exist_ok=True)

    script_mirrors = {
        "public": SHARED_SCRIPTS_ROOT,
        "private": PRIVATE_SCRIPTS_ROOT,
    }
    host_mirrors: dict[str, tuple[Path, str]] = {
        "skills": (
            PRIVATE_SKILLS_ROOT,
            "# Node Mount Mirror: skills\n\n"
            "Host-visible mirror of shared skills mounted into worker containers.\n"
            "Canonical source: /local/skills\n",
        ),
        "wiki": (
            SHARED_WIKI_ROOT,
            "# Node Mount Mirror: wiki\n\n"
            "Host-visible mirror of shared private wiki data mounted at /local/wiki.\n"
            "Canonical source: /local/plugins/private/wiki\n",
        ),
    }

    for subdir in ("plugins", "scripts"):
        subdir_path = clone_root / subdir
        if subdir_path.is_symlink() or (subdir_path.exists() and not subdir_path.is_dir()):
            _remove_path(subdir_path)
        subdir_path.mkdir(parents=True, exist_ok=True)
        note = anchor_notes.get(subdir, "").strip()
        if note:
            (subdir_path / "README.md").write_text(note + "\n", encoding="utf-8")
        for namespace in ("public", "private"):
            ns = subdir_path / namespace
            if ns.is_symlink() or (ns.exists() and not ns.is_dir()):
                _remove_path(ns)
            ns.mkdir(parents=True, exist_ok=True)
            if subdir == "scripts" and refresh_mirrors:
                src = script_mirrors[namespace]
                if src.exists():
                    _sync_dir(src, ns, delete=True)

    for dirname, (src, note) in host_mirrors.items():
        dst = clone_root / dirname
        if dst.is_symlink() or (dst.exists() and not dst.is_dir()):
            _remove_path(dst)
        dst.mkdir(parents=True, exist_ok=True)
        if refresh_mirrors and src.exists():
            _sync_dir(src, dst, delete=True)
        elif note.strip():
            (dst / "README.md").write_text(note.strip() + "\n", encoding="utf-8")

    _set_symlink(clone_root / "cron", worker_crons)

    legacy_crons = clone_root / "crons"
    if legacy_crons.exists() or legacy_crons.is_symlink():
        _remove_path(legacy_crons)
    legacy_agents = clone_root / "agents"
    if legacy_agents.exists() or legacy_agents.is_symlink():
        _remove_path(legacy_agents)


def _discord_plugin_roots() -> list[Path]:
    configured = str(os.getenv("HERMES_DISCORD_PLUGIN_DIR", "") or "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(DEFAULT_DISCORD_PLUGIN_ROOT)

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


def _discord_private_roots() -> list[Path]:
    configured = str(os.getenv("HERMES_DISCORD_PRIVATE_DIR", "") or "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(DEFAULT_DISCORD_PRIVATE_ROOT)

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _discord_private_dir(require_exists: bool = False) -> Path:
    roots = _discord_private_roots()
    for root in roots:
        if root.exists():
            return root
    if require_exists:
        raise CloneManagerError(
            "discord private runtime dir not found. Checked: "
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


def _prestart_script_path() -> Path:
    configured_core = str(os.getenv("HERMES_CORE_PLUGIN_DIR", "") or "").strip()
    candidates: list[Path] = []
    if configured_core:
        candidates.append(Path(configured_core).expanduser() / "scripts" / "prestart_reapply.sh")
    candidates.extend(
        [
            DEFAULT_HERMES_CORE_PLUGIN_ROOT / "scripts" / "prestart_reapply.sh",
            DEFAULT_DISCORD_PLUGIN_ROOT / "scripts" / "prestart_reapply.sh",
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

    for candidate in deduped:
        if candidate.exists():
            return candidate
    return deduped[0]


def _resolve_update_test_log_root() -> tuple[Path, str]:
    requested = UPDATE_TEST_LOG_ROOT.expanduser()
    try:
        requested.mkdir(parents=True, exist_ok=True)
        return requested, ""
    except Exception as exc:
        fallback = UPDATE_TEST_LOG_FALLBACK_ROOT.expanduser()
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except Exception as fallback_exc:
            raise CloneManagerError(
                "unable to initialize update log roots "
                f"(requested={requested}, fallback={fallback}): {fallback_exc}"
            ) from fallback_exc
        warning = f"requested log root not writable ({requested}): {exc}"
        return fallback, warning


def _new_update_run_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}-{int(time.time() * 1000)}"


def _create_update_run_dir(prefix: str) -> tuple[Path, str, str]:
    log_root, log_root_warning = _resolve_update_test_log_root()
    run_id = _new_update_run_id(prefix)
    run_dir = log_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir, run_id, log_root_warning


def _parse_deprecate_plugins(raw: str) -> list[str]:
    entries: list[str] = []
    seen: set[str] = set()
    for item in str(raw or "").split(","):
        name = str(item or "").strip()
        if not name or name == "deprecated":
            continue
        if name in seen:
            continue
        seen.add(name)
        entries.append(name)
    return entries


def _list_public_plugins(public_plugins_root: Path) -> list[str]:
    if not public_plugins_root.exists() or not public_plugins_root.is_dir():
        return []
    names: list[str] = []
    for child in sorted(public_plugins_root.iterdir(), key=lambda p: p.name):
        if child.name == "deprecated":
            continue
        if child.is_dir():
            names.append(child.name)
    return names


def _list_deprecated_plugins(public_plugins_root: Path) -> list[str]:
    deprecated_root = public_plugins_root / "deprecated"
    if not deprecated_root.exists() or not deprecated_root.is_dir():
        return []
    names: list[str] = []
    for child in sorted(deprecated_root.iterdir(), key=lambda p: p.name):
        if child.is_dir():
            names.append(child.name)
    return names


def _deprecate_plugins(
    *,
    public_plugins_root: Path,
    plugin_names: list[str],
) -> Dict[str, Any]:
    deprecated_root = public_plugins_root / "deprecated"
    deprecated_root.mkdir(parents=True, exist_ok=True)

    applied: list[str] = []
    already_present: list[str] = []
    missing: list[str] = []

    for plugin in plugin_names:
        source = public_plugins_root / plugin
        target = deprecated_root / plugin
        if target.exists():
            if source.exists():
                _sync_dir(source, target, delete=False)
                _remove_path(source)
            already_present.append(plugin)
            continue
        if not source.exists():
            missing.append(plugin)
            continue
        shutil.move(str(source), str(target))
        applied.append(plugin)

    return {
        "deprecated_plugins_root": str(deprecated_root),
        "deprecated_plugins_applied": applied,
        "deprecated_plugins_already_present": already_present,
        "deprecated_plugins_missing": missing,
    }


@contextmanager
def _temporary_runtime_roots(
    *,
    source_root: Path,
    plugins_root: Path,
    scripts_root: Path,
):
    # This context manager is intentionally narrow and only used by update
    # preflight to run the full clone bootstrap path against dummy snapshots.
    global HERMES_SOURCE_ROOT
    global PLUGINS_ROOT
    global SHARED_PLUGINS_ROOT
    global PRIVATE_PLUGINS_ROOT
    global SCRIPTS_ROOT
    global SHARED_SCRIPTS_ROOT
    global PRIVATE_SCRIPTS_ROOT
    global DEFAULT_DISCORD_PLUGIN_ROOT
    global DEFAULT_HERMES_CORE_PLUGIN_ROOT
    global DEFAULT_DISCORD_PRIVATE_ROOT
    global SHARED_WIKI_ROOT
    global SHARED_MEMORY_ROOT
    global LEGACY_SHARED_CRONS_ROOT

    previous = {
        "HERMES_SOURCE_ROOT": HERMES_SOURCE_ROOT,
        "PLUGINS_ROOT": PLUGINS_ROOT,
        "SHARED_PLUGINS_ROOT": SHARED_PLUGINS_ROOT,
        "PRIVATE_PLUGINS_ROOT": PRIVATE_PLUGINS_ROOT,
        "SCRIPTS_ROOT": SCRIPTS_ROOT,
        "SHARED_SCRIPTS_ROOT": SHARED_SCRIPTS_ROOT,
        "PRIVATE_SCRIPTS_ROOT": PRIVATE_SCRIPTS_ROOT,
        "DEFAULT_DISCORD_PLUGIN_ROOT": DEFAULT_DISCORD_PLUGIN_ROOT,
        "DEFAULT_HERMES_CORE_PLUGIN_ROOT": DEFAULT_HERMES_CORE_PLUGIN_ROOT,
        "DEFAULT_DISCORD_PRIVATE_ROOT": DEFAULT_DISCORD_PRIVATE_ROOT,
        "SHARED_WIKI_ROOT": SHARED_WIKI_ROOT,
        "SHARED_MEMORY_ROOT": SHARED_MEMORY_ROOT,
        "LEGACY_SHARED_CRONS_ROOT": LEGACY_SHARED_CRONS_ROOT,
    }

    try:
        HERMES_SOURCE_ROOT = source_root
        PLUGINS_ROOT = plugins_root
        SHARED_PLUGINS_ROOT = plugins_root / "public"
        PRIVATE_PLUGINS_ROOT = plugins_root / "private"
        SCRIPTS_ROOT = scripts_root
        SHARED_SCRIPTS_ROOT = scripts_root / "public"
        PRIVATE_SCRIPTS_ROOT = scripts_root / "private"
        DEFAULT_DISCORD_PLUGIN_ROOT = SHARED_PLUGINS_ROOT / "discord"
        DEFAULT_HERMES_CORE_PLUGIN_ROOT = SHARED_PLUGINS_ROOT / "hermes-core"
        DEFAULT_DISCORD_PRIVATE_ROOT = PRIVATE_PLUGINS_ROOT / "discord"
        SHARED_WIKI_ROOT = PRIVATE_PLUGINS_ROOT / "wiki"
        SHARED_MEMORY_ROOT = PRIVATE_PLUGINS_ROOT / "memory"
        LEGACY_SHARED_CRONS_ROOT = PRIVATE_SCRIPTS_ROOT / "crons"
        yield
    finally:
        HERMES_SOURCE_ROOT = previous["HERMES_SOURCE_ROOT"]
        PLUGINS_ROOT = previous["PLUGINS_ROOT"]
        SHARED_PLUGINS_ROOT = previous["SHARED_PLUGINS_ROOT"]
        PRIVATE_PLUGINS_ROOT = previous["PRIVATE_PLUGINS_ROOT"]
        SCRIPTS_ROOT = previous["SCRIPTS_ROOT"]
        SHARED_SCRIPTS_ROOT = previous["SHARED_SCRIPTS_ROOT"]
        PRIVATE_SCRIPTS_ROOT = previous["PRIVATE_SCRIPTS_ROOT"]
        DEFAULT_DISCORD_PLUGIN_ROOT = previous["DEFAULT_DISCORD_PLUGIN_ROOT"]
        DEFAULT_HERMES_CORE_PLUGIN_ROOT = previous["DEFAULT_HERMES_CORE_PLUGIN_ROOT"]
        DEFAULT_DISCORD_PRIVATE_ROOT = previous["DEFAULT_DISCORD_PRIVATE_ROOT"]
        SHARED_WIKI_ROOT = previous["SHARED_WIKI_ROOT"]
        SHARED_MEMORY_ROOT = previous["SHARED_MEMORY_ROOT"]
        LEGACY_SHARED_CRONS_ROOT = previous["LEGACY_SHARED_CRONS_ROOT"]


def _plugin_name_from_step_command(command: str) -> str:
    match = PLUGIN_PATH_RE.search(str(command or ""))
    if match:
        return str(match.group(1) or "").strip() or "unknown"
    return "unknown"


def _build_plugin_matrix(
    *,
    prestart_log_path: Path,
    deprecated_plugins: list[str],
) -> Dict[str, Any]:
    deprecated_set = set(deprecated_plugins)
    steps: list[Dict[str, Any]] = []
    by_name: Dict[str, Dict[str, Any]] = {}

    if prestart_log_path.exists():
        for raw in prestart_log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = str(raw or "")
            step_match = re.search(r"STEP\s+([A-Za-z0-9._-]+):\s*(.*)$", line)
            if step_match:
                name = str(step_match.group(1) or "").strip()
                command = str(step_match.group(2) or "").strip()
                plugin = _plugin_name_from_step_command(command)
                row = {
                    "step": name,
                    "plugin": plugin,
                    "command": command,
                    "status": "pending",
                }
                steps.append(row)
                by_name[name] = row
                continue

            ok_match = re.search(r"OK\s+([A-Za-z0-9._-]+)\s*$", line)
            if ok_match:
                name = str(ok_match.group(1) or "").strip()
                row = by_name.get(name)
                if row is not None:
                    row["status"] = "passed"
                continue

            fail_match = re.search(r"FAIL\s+([A-Za-z0-9._-]+)\s*$", line)
            if fail_match:
                name = str(fail_match.group(1) or "").strip()
                row = by_name.get(name)
                if row is not None:
                    row["status"] = "failed"
                continue

    for row in steps:
        if str(row.get("plugin") or "") in deprecated_set:
            row["status"] = "skipped_deprecated"

    for plugin in deprecated_plugins:
        has_rows = any(str(row.get("plugin") or "") == plugin for row in steps)
        if has_rows:
            continue
        steps.append(
            {
                "step": f"plugin::{plugin}",
                "plugin": plugin,
                "command": "",
                "status": "skipped_deprecated",
                "reason": "plugin moved under deprecated/",
            }
        )

    summary = {
        "passed": sum(1 for row in steps if row.get("status") == "passed"),
        "failed": sum(1 for row in steps if row.get("status") == "failed"),
        "skipped_deprecated": sum(1 for row in steps if row.get("status") == "skipped_deprecated"),
        "pending": sum(1 for row in steps if row.get("status") == "pending"),
        "total": len(steps),
    }

    return {
        "steps": steps,
        "summary": summary,
        "deprecated_plugins": list(deprecated_plugins),
    }


def _refresh_dummy_snapshot(source_branch: str, deprecated_plugins: list[str]) -> Dict[str, Any]:
    UPDATE_DUMMY_ROOT.mkdir(parents=True, exist_ok=True)

    _sync_dir(PLUGINS_ROOT, UPDATE_DUMMY_PLUGINS_ROOT, delete=True)
    _sync_dir(SCRIPTS_ROOT, UPDATE_DUMMY_SCRIPTS_ROOT, delete=True)

    with _temporary_runtime_roots(
        source_root=UPDATE_DUMMY_HERMES_ROOT,
        plugins_root=UPDATE_DUMMY_PLUGINS_ROOT,
        scripts_root=UPDATE_DUMMY_SCRIPTS_ROOT,
    ):
        template_payload = _action_update_template(source_branch)

    deprecate_payload = _deprecate_plugins(
        public_plugins_root=UPDATE_DUMMY_PUBLIC_PLUGINS_ROOT,
        plugin_names=deprecated_plugins,
    )

    return {
        "dummy_root": str(UPDATE_DUMMY_ROOT),
        "dummy_hermes_root": str(UPDATE_DUMMY_HERMES_ROOT),
        "dummy_plugins_root": str(UPDATE_DUMMY_PLUGINS_ROOT),
        "dummy_scripts_root": str(UPDATE_DUMMY_SCRIPTS_ROOT),
        "template_update": template_payload,
        "snapshot_plugins": {
            "source": str(PLUGINS_ROOT),
            "target": str(UPDATE_DUMMY_PLUGINS_ROOT),
        },
        "snapshot_scripts": {
            "source": str(SCRIPTS_ROOT),
            "target": str(UPDATE_DUMMY_SCRIPTS_ROOT),
        },
        **deprecate_payload,
        "active_plugins_after_snapshot": _list_public_plugins(UPDATE_DUMMY_PUBLIC_PLUGINS_ROOT),
        "deprecated_plugins_present": _list_deprecated_plugins(UPDATE_DUMMY_PUBLIC_PLUGINS_ROOT),
    }


def _seed_update_test_env_profile(clone_name: str, env_path: Path) -> Dict[str, Any]:
    source = UPDATE_TEST_ENV_SOURCE.expanduser()
    if source.exists():
        seed_text = source.read_text(encoding="utf-8")
        seed_source = source
    elif NODE_ENV_TEMPLATE_PATH.exists():
        seed_text = NODE_ENV_TEMPLATE_PATH.read_text(encoding="utf-8")
        seed_source = NODE_ENV_TEMPLATE_PATH
    else:
        raise CloneManagerError(
            "could not build dummy env profile; no seed found at "
            f"{source} or {NODE_ENV_TEMPLATE_PATH}"
        )

    text = seed_text if seed_text.endswith("\n") else f"{seed_text}\n"
    overrides = {
        "NODE_STATE": "4",
        "NODE_STATE_FROM_BACKUP_PATH": "''",
        "NODE_WIKI_ENABLED": "false",
        "OPENVIKING_ENABLED": "0",
        "CAMOFOX_ENABLED": "0",
        "DISCORD_HOME_CHANNEL": "000000000000000000",
        "DISCORD_APP_ID": "000000000000000000",
        "DISCORD_SERVER_ID": "000000000000000000",
        "DISCORD_BOT_TOKEN": "DUMMY_TOKEN",
        "NODE_PLUGINS_STRICT": "1",
    }
    for key, value in overrides.items():
        text = _replace_or_append_env_line(text, key, value)

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(text, encoding="utf-8")
    try:
        env_path.chmod(0o600)
    except Exception:
        pass

    _log(
        clone_name,
        f"update test env prepared: {env_path} (seed={seed_source})",
    )
    return {
        "env_path": str(env_path),
        "seed_source": str(seed_source),
        "seed_source_exists": source.exists(),
    }


def _extract_prestart_failures(prestart_log_path: Path) -> list[str]:
    if not prestart_log_path.exists():
        return []
    failures: list[str] = []
    for raw in prestart_log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        idx = raw.find("FAIL ")
        if idx < 0:
            continue
        name = raw[idx + len("FAIL ") :].strip()
        if not name:
            continue
        if name not in failures:
            failures.append(name)
    return failures


def _run_prestart_reapply(
    clone_name: str,
    *,
    clone_root: Path,
    env_path: Path,
    strict: bool,
    capture_output: bool,
) -> Dict[str, Any]:
    prestart_script = _prestart_script_path()
    if not prestart_script.exists():
        raise CloneManagerError(f"prestart reapply script not found: {prestart_script}")

    env = _read_env_file(env_path)
    runtime_env_overrides = _runtime_env_overrides(clone_name, env)
    proc_env = os.environ.copy()
    proc_env.update(env)
    proc_env.update(runtime_env_overrides)
    proc_env["HERMES_HOME"] = str(clone_root / ".hermes")
    proc_env["HOME"] = str(clone_root)
    proc_env["USER"] = str(proc_env.get("USER") or "ubuntu")
    proc_env["LOGNAME"] = str(proc_env.get("LOGNAME") or proc_env["USER"])
    proc_env["NODE_NAME"] = str(proc_env.get("NODE_NAME") or clone_name)
    proc_env["HERMES_DISCORD_PLUGIN_DIR"] = str(DEFAULT_DISCORD_PLUGIN_ROOT)
    proc_env["HERMES_CORE_PLUGIN_DIR"] = str(DEFAULT_HERMES_CORE_PLUGIN_ROOT)
    proc_env["HERMES_DISCORD_PRIVATE_DIR"] = str(DEFAULT_DISCORD_PRIVATE_ROOT)
    proc_env["HERMES_PUBLIC_PLUGINS_ROOT"] = str(SHARED_PLUGINS_ROOT)
    proc_env["HERMES_PRIVATE_PLUGINS_ROOT"] = str(PRIVATE_PLUGINS_ROOT)
    proc_env["HERMES_PUBLIC_SCRIPTS_ROOT"] = str(SHARED_SCRIPTS_ROOT)
    proc_env["HERMES_PRIVATE_SCRIPTS_ROOT"] = str(PRIVATE_SCRIPTS_ROOT)
    proc_env["HERMES_AGENT_ROOT"] = str(clone_root / "hermes-agent")
    proc_env["HERMES_NODE_ROOT"] = str(clone_root)
    proc_env["NODE_PLUGINS_STRICT"] = "1" if strict else str(proc_env.get("NODE_PLUGINS_STRICT", "0"))
    proc_env["PYTHONUNBUFFERED"] = "1"

    cmd = ["bash", str(prestart_script)]
    if strict:
        cmd.append("--strict")

    proc = subprocess.run(
        cmd,
        cwd=str(clone_root / "hermes-agent"),
        env=proc_env,
        capture_output=capture_output,
        text=True,
        check=False,
    )

    prestart_log_path = clone_root / ".hermes" / "logs" / "colmeio-prestart.log"
    failed_marker_path = clone_root / ".hermes" / "logs" / "colmeio-prestart.failed"
    return {
        "script": str(prestart_script),
        "returncode": int(proc.returncode),
        "stdout": str(proc.stdout or ""),
        "stderr": str(proc.stderr or ""),
        "prestart_log_path": str(prestart_log_path),
        "failed_marker_path": str(failed_marker_path),
        "failed_marker_exists": failed_marker_path.exists(),
        "failures": _extract_prestart_failures(prestart_log_path),
    }


def _ensure_discord_shared_plugin_seeded(clone_name: str) -> Path:
    target = _discord_plugin_roots()[0]
    target.parent.mkdir(parents=True, exist_ok=True)

    prestart_target = target / "scripts" / "prestart_reapply.sh"
    if prestart_target.exists():
        return target

    source = next(
        (root for root in _discord_plugin_roots()[1:] if (root / "scripts" / "prestart_reapply.sh").exists()),
        None,
    )
    if source is not None:
        _sync_dir(source, target, delete=True)
        _log(clone_name, f"discord shared plugin seeded: {source} -> {target}")
        return target

    target.mkdir(parents=True, exist_ok=True)
    _log(clone_name, f"discord shared plugin dir created (empty): {target}")
    return target


def _discord_runtime_seed_candidates(filename: str) -> list[Path]:
    private_root = _discord_private_dir(require_exists=False)
    public_root = _discord_plugin_dir(require_exists=False)
    primary = private_root / filename
    return [
        primary,
        public_root / f"{filename}.example",
    ]


def _seed_discord_state_file(
    *,
    clone_name: str,
    target_file: Path,
    default_content: str,
    seed_candidates: list[Path] | None = None,
) -> None:
    if target_file.exists():
        return

    candidates = list(seed_candidates or [])
    source = next((c for c in candidates if c.exists()), None)
    target_file.parent.mkdir(parents=True, exist_ok=True)
    if source is not None:
        shutil.copy2(source, target_file)
        _log(clone_name, f"seeded discord state: {source} -> {target_file}")
        return

    target_file.write_text(default_content, encoding="utf-8")
    _log(clone_name, f"created discord state file: {target_file}")


def _parse_csv_env_list(value: str) -> list[str]:
    return [entry.strip() for entry in str(value or "").split(",") if entry.strip()]


def _seed_discord_settings_file(
    *,
    clone_root: Path,
    clone_name: str = "",
    env: Dict[str, str] | None = None,
) -> None:
    settings_path = clone_root / "workspace" / "discord" / "discord_settings.json"
    if settings_path.exists():
        return

    env_data = env or {}
    payload = {
        "DISCORD_ALLOWED_USERS": _parse_csv_env_list(
            _env_first_nonempty(env_data, "DISCORD_ALLOWED_USERS") or ""
        ),
        "DISCORD_AUTO_THREAD_IGNORE_CHANNELS": _parse_csv_env_list(
            _env_first_nonempty(env_data, "DISCORD_AUTO_THREAD_IGNORE_CHANNELS") or ""
        ),
    }
    if "DISCORD_REQUIRE_MENTION_CHANNELS" in env_data:
        payload["DISCORD_REQUIRE_MENTION_CHANNELS"] = _parse_csv_env_list(
            str(env_data.get("DISCORD_REQUIRE_MENTION_CHANNELS", "") or "")
        )
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    if clone_name:
        _log(clone_name, f"created discord settings file: {settings_path}")


def _ensure_workspace_data_layout(clone_root: Path, clone_name: str = "") -> None:
    if not clone_name:
        return

    data_dir = _shared_node_data_dir(clone_name)
    data_dir.mkdir(parents=True, exist_ok=True)

    legacy_data_dirs = [
        _legacy_node_data_dir(clone_root),
        clone_root / "workspace" / "data",
    ]
    migrated_items: list[str] = []
    dropped_duplicates: list[str] = []
    migrated_from: list[str] = []
    data_root_norm = _normalized_path_str(data_dir)

    for legacy_dir in legacy_data_dirs:
        if not legacy_dir.exists():
            continue
        if legacy_dir.is_symlink():
            _remove_path(legacy_dir)
            continue
        if not legacy_dir.is_dir():
            continue
        if _normalized_path_str(legacy_dir) == data_root_norm:
            continue

        migrated_from.append(str(legacy_dir))
        for legacy_item in sorted(legacy_dir.iterdir(), key=lambda p: p.name):
            target_item = data_dir / legacy_item.name
            if target_item.exists() or target_item.is_symlink():
                _remove_path(legacy_item)
                dropped_duplicates.append(legacy_item.name)
                continue
            shutil.move(str(legacy_item), str(target_item))
            migrated_items.append(legacy_item.name)

        try:
            has_entries = any(legacy_dir.iterdir())
        except Exception:
            has_entries = True
        if not has_entries:
            try:
                legacy_dir.rmdir()
            except Exception:
                pass

    if clone_name and migrated_items:
        joined = ", ".join(migrated_items)
        sources = ", ".join(migrated_from) if migrated_from else "legacy paths"
        _log(clone_name, f"migrated node data ({joined}) from {sources} -> {data_dir}")
    if clone_name and dropped_duplicates:
        joined = ", ".join(dropped_duplicates)
        _log(clone_name, f"removed legacy data duplicates already present in {data_dir} ({joined})")


def _sync_discord_runtime_layout(
    clone_root: Path,
    clone_name: str = "",
    env: Dict[str, str] | None = None,
) -> None:
    """Use private plugin runtime state and remove stale workspace mirrors."""
    shared_discord_root = _discord_private_dir(require_exists=False)
    shared_discord_root.mkdir(parents=True, exist_ok=True)

    _seed_discord_state_file(
        clone_name=clone_name,
        target_file=shared_discord_root / "discord_users.json",
        default_content='{\n  "version": 2,\n  "users": []\n}\n',
        seed_candidates=_discord_runtime_seed_candidates("discord_users.json"),
    )
    _seed_discord_state_file(
        clone_name=clone_name,
        target_file=shared_discord_root / "discord_webhooks_table.json",
        default_content="{}\n",
        seed_candidates=_discord_runtime_seed_candidates("discord_webhooks_table.json"),
    )

    # Discord pairing/channel settings are now node-local source of truth.
    _seed_discord_settings_file(
        clone_root=clone_root,
        clone_name=clone_name,
        env=env,
    )


def _setup_orchestrator_baremetal(clone_name: str, clone_root: Path, env: Dict[str, str], env_path: Path) -> Dict[str, Any]:
    """Set up orchestrator (NODE_STATE=1) as a bare-metal bootstrap node.

    The orchestrator:
    - Lives directly on the VM (not containerized)
    - Lives under /local/agents/nodes/orchestrator/
    - Stores state in /local/agents/nodes/orchestrator/.hermes
    - Uses a clone-local hermes-agent runtime copy under node root
    - Uses shared host assets via symlinks: /local/plugins, /local/scripts, and /local/crons/orchestrator
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
    for sub in ("workspace", ".hermes", ".runtime", "logs", ".clone-meta"):
        sub_path = clone_root / sub
        if sub_path.is_symlink():
            _remove_path(sub_path)
        sub_path.mkdir(parents=True, exist_ok=True)
    _ensure_node_log_topology(
        clone_name,
        clone_root=clone_root,
        migrate_clone_paths=True,
        link_clone_hermes_logs=True,
    )

    # Drop legacy clone-era paths that don't belong to orchestrator topology.
    for legacy_sub in ("memory", "backups", "agents", "clones", "tmp"):
        legacy_path = clone_root / legacy_sub
        if legacy_path.exists() or legacy_path.is_symlink():
            _remove_path(legacy_path)

    # Make sure shared host roots exist.
    _orchestrator_cron_host_dir(clone_name).mkdir(parents=True, exist_ok=True)
    _orchestrator_memory_home(clone_name).mkdir(parents=True, exist_ok=True)
    SHARED_SCRIPTS_ROOT.mkdir(parents=True, exist_ok=True)
    SHARED_PLUGINS_ROOT.mkdir(parents=True, exist_ok=True)

    source_tree = _parent_hermes_agent_source(clone_name=clone_name)
    runtime_agent_root = _prepare_orchestrator_runtime_agent_tree(
        clone_name=clone_name,
        clone_root=clone_root,
        source_tree=source_tree,
    )
    _set_symlink(clone_root / "scripts", SCRIPTS_ROOT)
    _set_symlink(clone_root / "plugins", PLUGINS_ROOT)
    _set_symlink(clone_root / "cron", _orchestrator_cron_host_dir(clone_name))
    legacy_crons = clone_root / "crons"
    if legacy_crons.exists() or legacy_crons.is_symlink():
        _remove_path(legacy_crons)
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

    _sync_discord_runtime_layout(clone_root, clone_name, env)
    _ensure_workspace_data_layout(clone_root, clone_name)
    _sync_node_wiki_link(clone_root, env, containerized=False)
    try:
        _normalize_clone_skills_layout(clone_root, containerized=False)
    except CloneManagerError:
        home_skills = clone_root / ".hermes" / "skills"
        node_skills = clone_root / "skills"
        _set_symlink(node_skills, PRIVATE_SKILLS_ROOT)
        if home_skills.exists() or home_skills.is_symlink():
            _remove_path(home_skills)
        PRIVATE_SKILLS_ROOT.mkdir(parents=True, exist_ok=True)
        home_skills.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(os.path.relpath(str(node_skills), start=str(home_skills.parent)), str(home_skills))

    _write_node_runtime_contract(clone_root, clone_name, env)

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
    yolo_mode = _effective_hermes_yolo_mode(env)
    if yolo_mode:
        _upsert_env_value(clone_home_env, "HERMES_YOLO_MODE", yolo_mode)
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
    enabled = _is_camofox_enabled_env(env)
    enable_var = "CAMOFOX_ENABLED" if str(env.get("CAMOFOX_ENABLED", "") or "").strip() else "BROWSER_CAMOFOX"
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
                    "--enable-var",
                    enable_var,
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
    current_url = str(env.get("CAMOFOX_URL", "") or "").strip() or CAMOFOX_DEFAULT_URL_CLONE

    return {
        "enabled": True,
        "changed": False,
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
    enabled = _is_openviking_enabled_env(env)
    enable_var = (
        "OPENVIKING_ENABLED"
        if str(env.get("OPENVIKING_ENABLED", "") or "").strip()
        else "MEMORY_OPENVIKING"
    )
    default_account, default_user = _resolve_openviking_identity(env, clone_name)
    supported = _clone_supports_openviking(clone_root)
    effective_endpoint = str(env.get("OPENVIKING_ENDPOINT", "") or "").strip() or OPENVIKING_DEFAULT_ENDPOINT_CLONE
    effective_account, effective_user = _resolve_openviking_identity(env, clone_name)

    if not enabled:
        return {
            "enabled": False,
            "changed": False,
            "effective": {
                "endpoint": effective_endpoint,
                "account": effective_account,
                "user": effective_user,
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
                    "--enable-var",
                    enable_var,
                    "--config-file",
                    str(clone_root / ".hermes" / "config.yaml"),
                    "--agent-root",
                    str(clone_root / "hermes-agent"),
                    "--default-endpoint",
                    OPENVIKING_DEFAULT_ENDPOINT_CLONE,
                    "--default-account",
                    default_account,
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
    env = _read_env_file(env_path)
    effective_endpoint = str(env.get("OPENVIKING_ENDPOINT", "") or "").strip() or OPENVIKING_DEFAULT_ENDPOINT_CLONE
    effective_account, effective_user = _resolve_openviking_identity(env, clone_name)
    if not supported:
        _log(
            clone_name,
            "openviking compatibility warning: provider plugin missing in clone code; "
            "run 'horc update apply node <node>' to refresh node code.",
        )
    return {
        "enabled": True,
        "changed": False,
        "effective": {
            "endpoint": effective_endpoint,
            "account": effective_account,
            "user": effective_user,
        },
        "compatibility": {
            "supported": supported,
            "message": "fallback mode (env only)" if supported else (
                "provider plugin missing; refresh node code "
                "(run 'horc update apply node <node>' and start again)."
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
                "model": _default_model_name_from_env(env),
                "provider": _default_model_provider_from_env(env),
                "base_url": str(env.get("DEFAULT_MODEL_BASE_URL", "") or ""),
                "api_mode": str(env.get("DEFAULT_MODEL_API_MODE", "") or ""),
            },
            "fallback": {
                "model": _fallback_model_name_from_env(env),
                "provider": _fallback_model_provider_from_env(env),
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
    # Canonical source of truth is /local/skills. We keep
    # compatibility fallbacks only for first-run migrations.
    placeholder_names = {".gitignore", ".gitkeep", ".keep", "README.md"}

    def _resolve_dir(candidate: Path) -> Path | None:
        if candidate.is_dir():
            return candidate
        if candidate.is_symlink():
            try:
                resolved = candidate.resolve(strict=True)
            except Exception:
                return None
            if resolved.is_dir():
                return resolved
        return None

    state_source: Path | None
    try:
        state_source = _parent_hermes_home_source()
    except CloneManagerError:
        state_source = None

    candidates = [
        PRIVATE_SKILLS_ROOT,
        (state_source / "skills") if state_source is not None else Path("/nonexistent"),
        PARENT_HERMES_HOME / "skills",
    ]

    private_source = _resolve_dir(candidates[0])
    if private_source is not None and _dir_has_entries(private_source, ignored_names=placeholder_names):
        return private_source

    for candidate in candidates[1:]:
        resolved = _resolve_dir(candidate)
        if resolved is None:
            continue
        if _dir_has_entries(resolved, ignored_names=placeholder_names):
            return resolved

    if private_source is not None:
        return private_source

    raise CloneManagerError(
        "no valid skills source found "
        "(expected /local/skills or orchestrator .hermes/skills)."
    )


def _normalize_clone_skills_layout(clone_root: Path, *, containerized: bool) -> None:
    """Ensure deterministic clone skills layout.

    - Canonical shared skills dir: /local/skills
    - Node-local /local/.hermes/skills becomes a symlink to ../skills
    - Host orchestrator uses node skills symlink -> /local/skills
    - Containerized nodes expose /local/skills as a mountpoint (no node/agents bloat)
    """
    home_skills = clone_root / ".hermes" / "skills"
    node_skills = clone_root / "skills"
    workspace_skills = clone_root / "workspace" / "skills"

    PRIVATE_SKILLS_ROOT.parent.mkdir(parents=True, exist_ok=True)
    PRIVATE_SKILLS_ROOT.mkdir(parents=True, exist_ok=True)
    placeholder_names = {".gitignore", ".gitkeep", ".keep", "README.md"}
    private_has_payload = _dir_has_entries(PRIVATE_SKILLS_ROOT, ignored_names=placeholder_names)

    if not private_has_payload:
        source: Path | None = None
        if home_skills.exists() and home_skills.is_dir() and not home_skills.is_symlink():
            if _dir_has_entries(home_skills):
                source = home_skills
        if source is None:
            try:
                candidate = _parent_skills_source()
            except CloneManagerError:
                candidate = None
            if (
                candidate is not None
                and candidate != PRIVATE_SKILLS_ROOT
                and _dir_has_entries(candidate, ignored_names=placeholder_names)
            ):
                source = candidate
        if source is not None:
            _sync_dir(source, PRIVATE_SKILLS_ROOT, delete=True)
    elif home_skills.exists() and home_skills.is_dir() and not home_skills.is_symlink():
        # Preserve node-local custom skills during migration into the shared
        # private pool without deleting existing shared material.
        if _dir_has_entries(home_skills):
            _sync_dir(home_skills, PRIVATE_SKILLS_ROOT, delete=False)

    if containerized:
        if node_skills.exists() and node_skills.is_symlink():
            _remove_path(node_skills)
        if node_skills.exists() and not node_skills.is_dir():
            _remove_path(node_skills)
        node_skills.mkdir(parents=True, exist_ok=True)
    else:
        _set_symlink(node_skills, PRIVATE_SKILLS_ROOT)

    if home_skills.exists() or home_skills.is_symlink():
        _remove_path(home_skills)
    home_skills.parent.mkdir(parents=True, exist_ok=True)
    # Relative link keeps host/container paths aligned without hardcoding /local/agents.
    os.symlink(os.path.relpath(str(node_skills), start=str(home_skills.parent)), str(home_skills))

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
                "Run 'horc update apply node <node>' or set NODE_FORCE_RESEED=1 to re-bootstrap."
            )
        src_venv = _select_seed_venv_source(required_modules=GATEWAY_REQUIRED_MODULES)
        _sync_dir(src_venv, dst_venv, delete=True)
        python_bin = dst_venv / "bin" / "python"

    # Validate required gateway dependency to avoid boot loops.
    if not _python_has_modules(python_bin, GATEWAY_REQUIRED_MODULES):
        if not allow_parent_seed:
            required = ", ".join(GATEWAY_REQUIRED_MODULES)
            raise CloneManagerError(
                f"clone runtime venv is missing required modules ({required}). "
                "Run 'horc update apply node <node>' or set NODE_FORCE_RESEED=1 to refresh runtime."
            )
        src_venv = _select_seed_venv_source(required_modules=GATEWAY_REQUIRED_MODULES)
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
    raw = _env_first_nonempty(env, "NODE_STATE", "CLONE_STATE") or "1"
    try:
        value = int(raw)
    except ValueError as exc:
        raise CloneManagerError(f"invalid NODE_STATE value: {raw}") from exc
    if value not in STATE_LABELS:
        raise CloneManagerError(
            f"invalid NODE_STATE value: {value}. Expected: 1=orchestrator, 2=seed_from_parent_snapshot, 3=seed_from_backup, 4=fresh."
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
                "cron",
                "crons",
                "skills",
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
        "workspace",
        "hermes-agent",
        ".hermes",
        "logs",
        ".clone-meta",
        str(RUNTIME_UV_REL),
    ):
        sub_path = clone_root / sub
        if sub_path.is_symlink():
            _remove_path(sub_path)
        sub_path.mkdir(parents=True, exist_ok=True)
    _ensure_node_log_topology(
        clone_name,
        clone_root=clone_root,
        migrate_clone_paths=True,
        link_clone_hermes_logs=(mode == 1),
    )

    # Drop clone-local legacy log buckets. Canonical runtime logs live under
    # /local/logs/{nodes,attention}/... managed by the orchestrator.
    for legacy_log_rel in ("agents", "clones", "skills"):
        legacy_log_path = clone_root / "logs" / legacy_log_rel
        if legacy_log_path.exists() or legacy_log_path.is_symlink():
            _remove_path(legacy_log_path)

    # Drop legacy clone-era paths that are outside the agents-v2 topology.
    for legacy_rel in ("memory", "backups", "agents", "clones", "tmp"):
        legacy_path = clone_root / legacy_rel
        if legacy_path.exists() or legacy_path.is_symlink():
            _remove_path(legacy_path)

    # Drop legacy workspace compatibility trees that conflict with agents-v2.
    # Runtime mutable state is mounted at /local/data from /local/datas/<node>.
    for legacy_rel in ("cron", "crons", "skills", "plugins", "colmeio"):
        legacy_path = clone_root / "workspace" / legacy_rel
        if legacy_path.exists() or legacy_path.is_symlink():
            _remove_path(legacy_path)

    _ensure_worker_shared_mount_links(clone_root, clone_name)
    _sync_discord_runtime_layout(clone_root, clone_name, env)
    _ensure_workspace_data_layout(clone_root, clone_name)
    _sync_node_wiki_link(clone_root, env, containerized=True)
    _write_node_runtime_contract(clone_root, clone_name, env)

    _ensure_clone_ownership(clone_root)
    force_reseed = _is_truthy(_env_first_nonempty(env, "NODE_FORCE_RESEED", "CLONE_FORCE_RESEED", "0"))
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

    # Handle orchestrator (NODE_STATE=1) as bare-metal bootstrap node.
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
            raw_backup = _env_first_nonempty(
                env,
                "NODE_STATE_FROM_BACKUP_PATH",
                "CLONE_STATE_FROM_BACKUP_PATH",
            )
            if not raw_backup:
                raise CloneManagerError(
                    "NODE_STATE=3 requires NODE_STATE_FROM_BACKUP_PATH to be set."
                )
            _seed_from_backup(clone_root, Path(raw_backup))
            _log_spawn_event(clone_name, "bootstrap", "seed_from_backup", f"path={raw_backup}")
        elif mode == 4:
            # Fresh clone - no parent state sync, no backup restore
            _log_spawn_event(clone_name, "bootstrap", "fresh_mode", "no_parent_sync")

        workspace_seeded = _seed_clone_workspace_integrations(clone_root)
        _normalize_clone_skills_layout(clone_root, containerized=True)
        _seed_clone_runtime(clone_root, allow_parent_seed=True)

        _atomic_write_json(
            bootstrap_meta_path,
            {
                "clone_name": clone_name,
                "bootstrapped_at": _utc_now(),
                "state_mode": STATE_LABELS[mode],
                "state_code": mode,
                "seed_code_source": str(parent_source),
                "seed_venv_source": str(_select_seed_venv_source(required_modules=GATEWAY_REQUIRED_MODULES)),
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
                    "Run 'horc update apply node <node>' or set NODE_FORCE_RESEED=1 to re-bootstrap."
                )
        _normalize_clone_skills_layout(clone_root, containerized=True)
        _seed_clone_runtime(clone_root, allow_parent_seed=False)

    # Keep clone-local .hermes/.env aligned with the clone profile.
    clone_home_env = clone_root / ".hermes" / ".env"
    clone_home_env.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(env_path, clone_home_env)
    yolo_mode = _effective_hermes_yolo_mode(env)
    if yolo_mode:
        _upsert_env_value(clone_home_env, "HERMES_YOLO_MODE", yolo_mode)
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
    runtime_env_overrides: Dict[str, str],
) -> list[str]:
    env = _read_env_file(env_path)
    container = _container_name(clone_name)
    _ensure_node_log_topology(
        clone_name,
        clone_root=clone_root,
        migrate_clone_paths=True,
        link_clone_hermes_logs=False,
    )
    node_log_host = _node_log_dir(clone_name)
    attention_log_host = _node_attention_dir(clone_name)
    hermes_log_host = _node_hermes_log_dir(clone_name)
    node_log_host.mkdir(parents=True, exist_ok=True)
    attention_log_host.mkdir(parents=True, exist_ok=True)
    hermes_log_host.mkdir(parents=True, exist_ok=True)

    node_crons_host = SHARED_CRONS_ROOT / clone_name
    node_crons_host.mkdir(parents=True, exist_ok=True)
    node_data_host = _shared_node_data_dir(clone_name)
    node_data_host.mkdir(parents=True, exist_ok=True)

    gateway_cmd = (
        "set -euo pipefail; "
        f"NODE_LOG_DIR=/local/logs/nodes/{clone_name}; "
        f"ATTN_LOG_DIR=/local/logs/attention/nodes/{clone_name}; "
        "RUNTIME_LOG=\"${NODE_LOG_DIR}/runtime.log\"; "
        "ATTN_LOG=\"${ATTN_LOG_DIR}/warning-plus.log\"; "
        "ATTN_REGEX='warn(ing)?|error|critical|fatal|panic|emerg(ency)?|alert'; "
        "mkdir -p \"${NODE_LOG_DIR}\" \"${ATTN_LOG_DIR}\" /local/.hermes/logs; "
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
        "echo \"[clone-bootstrap] ca_bundle=${CA_BUNDLE:-unset}\" | tee -a \"${RUNTIME_LOG}\" >(grep -Eai \"${ATTN_REGEX}\" >> \"${ATTN_LOG}\") >/dev/null; "
        "if [ -n \"${CA_BUNDLE:-}\" ]; then "
        "export SSL_CERT_FILE=\"$CA_BUNDLE\"; "
        "export REQUESTS_CA_BUNDLE=\"$CA_BUNDLE\"; "
        "export CURL_CA_BUNDLE=\"$CA_BUNDLE\"; "
        "fi; "
        "PRESTART_SCRIPT=\"\"; "
        "for _p in /local/plugins/public/hermes-core/scripts/prestart_reapply.sh /local/plugins/public/discord/scripts/prestart_reapply.sh; do "
        "if [ -x \"${_p}\" ]; then PRESTART_SCRIPT=\"${_p}\"; break; fi; "
        "done; "
        "if [ -n \"${PRESTART_SCRIPT}\" ]; then "
        "bash \"${PRESTART_SCRIPT}\" 2>&1 | tee -a \"${RUNTIME_LOG}\" >(grep -Eai \"${ATTN_REGEX}\" >> \"${ATTN_LOG}\") >/dev/null || true; "
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
        "( /local/hermes-agent/.venv/bin/python /local/hermes-agent/cli.py --gateway 2>&1 | tee -a \"${RUNTIME_LOG}\" >(grep -Eai \"${ATTN_REGEX}\" >> \"${ATTN_LOG}\") >/dev/null ) & "
        "CHILD_PID=$!; "
        "echo \"${CHILD_PID}\" > /tmp/hermes-gateway.pid; "
        "set +e; "
        "wait \"${CHILD_PID}\"; "
        "RC=$?; "
        "set -e; "
        "echo \"[clone-bootstrap] gateway_exit_rc=${RC}\" | tee -a \"${RUNTIME_LOG}\" >(grep -Eai \"${ATTN_REGEX}\" >> \"${ATTN_LOG}\") >/dev/null; "
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
        "HERMES_NODE_ROOT=/local",
        "-e",
        "HOME=/local",
        "-e",
        "USER=ubuntu",
        "-e",
        "LOGNAME=ubuntu",
        "-e",
        "VIRTUAL_ENV=/local/hermes-agent/.venv",
        "-e",
        "PATH=/local/hermes-agent/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "-e",
        f"NODE_NAME={clone_name}",
        "-e",
        "HERMES_DISCORD_PLUGIN_DIR=/local/plugins/public/discord",
        "-e",
        "HERMES_CORE_PLUGIN_DIR=/local/plugins/public/hermes-core",
        "-e",
        "HERMES_DISCORD_PRIVATE_DIR=/local/plugins/private/discord",
        "-e",
        "HERMES_PUBLIC_PLUGINS_ROOT=/local/plugins/public",
        "-e",
        "HERMES_PRIVATE_PLUGINS_ROOT=/local/plugins/private",
        "-e",
        "HERMES_PUBLIC_SCRIPTS_ROOT=/local/scripts/public",
        "-e",
        "HERMES_PRIVATE_SCRIPTS_ROOT=/local/scripts/private",
        "-e",
        "PYTHONUNBUFFERED=1",
        "-v",
        f"{clone_root}:/local",
        "-v",
        f"{node_data_host}:/local/data",
        "-v",
        f"{node_log_host}:/local/logs/nodes/{clone_name}",
        "-v",
        f"{attention_log_host}:/local/logs/attention/nodes/{clone_name}",
        "-v",
        f"{hermes_log_host}:/local/.hermes/logs",
        "-v",
        f"{SHARED_SCRIPTS_ROOT}:/local/scripts/public:ro",
        "-v",
        f"{PRIVATE_SCRIPTS_ROOT}:/local/scripts/private",
        "-v",
        f"{SHARED_PLUGINS_ROOT}:/local/plugins/public:ro",
        "-v",
        f"{PRIVATE_PLUGINS_ROOT}:/local/plugins/private",
        "-v",
        f"{node_crons_host}:/local/cron",
        "-v",
        f"{PRIVATE_SKILLS_ROOT}:{NODE_SKILLS_PATH_IN_CONTAINER}",
        "--workdir",
        "/local/hermes-agent",
    ]

    if _is_wiki_enabled_env(env):
        _ensure_shared_wiki_root()
        cmd.extend(["-e", "HERMES_WIKI_ROOT=/local/wiki"])
        cmd.extend(["-v", f"{SHARED_WIKI_ROOT}:/local/wiki"])

    for key in sorted(runtime_env_overrides):
        value = str(runtime_env_overrides.get(key, "") or "")
        cmd.extend(["-e", f"{key}={value}"])

    # Needed so clone containers can reach host-level services via
    # host.docker.internal on Linux (Camofox/OpenViking defaults).
    if camofox_enabled or openviking_enabled:
        cmd.extend(["--add-host", "host.docker.internal:host-gateway"])

    cmd.extend([image, "bash", "-lc", gateway_cmd])
    return cmd


def _orchestrator_pid_path(clone_root: Path) -> Path:
    return _shared_node_data_dir("orchestrator") / "gateway.pid"


def _orchestrator_legacy_pid_paths(clone_root: Path) -> list[Path]:
    return [
        clone_root / "data" / "gateway.pid",
        clone_root / "workspace" / "data" / "gateway.pid",
    ]


def _orchestrator_pid_candidates(clone_root: Path) -> list[Path]:
    return [_orchestrator_pid_path(clone_root), *_orchestrator_legacy_pid_paths(clone_root)]


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
    running_pid: int | None = None
    running_path: Path | None = None
    stale_pid: int | None = None
    stale_path: Path | None = None

    for candidate in _orchestrator_pid_candidates(clone_root):
        pid = _read_pid(candidate)
        if pid is None:
            continue
        if stale_path is None:
            stale_path = candidate
            stale_pid = pid
        if _pid_running(pid):
            running_pid = pid
            running_path = candidate
            break

    pid_path = running_path or stale_path or _orchestrator_pid_path(clone_root)
    pid = running_pid if running_pid is not None else stale_pid
    running = running_pid is not None
    return {
        "exists": True,
        "running": running,
        "status": "running" if running else "stopped",
        "pid": pid,
        "pid_file": str(pid_path),
    }


def _orchestrator_start_gateway(
    clone_name: str,
    clone_root: Path,
    env_path: Path,
    *,
    runtime_env_overrides: Dict[str, str] | None = None,
) -> Dict[str, Any]:
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
    ]
    python_bin = next(
        (
            p
            for p in python_candidates
            if p.exists() and _python_has_modules(p, GATEWAY_REQUIRED_MODULES)
        ),
        None,
    )
    if python_bin is None:
        existing = [str(p) for p in python_candidates if p.exists()]
        detail = ", ".join(existing) if existing else "none"
        required = ", ".join(GATEWAY_REQUIRED_MODULES)
        raise CloneManagerError(
            "python runtime missing required gateway modules "
            f"({required}); candidates={detail}"
        )

    _ensure_node_log_topology(
        clone_name,
        clone_root=clone_root,
        migrate_clone_paths=True,
        link_clone_hermes_logs=True,
    )
    runtime_log = _clone_runtime_log_path(clone_name, clone_root=clone_root)
    runtime_log.parent.mkdir(parents=True, exist_ok=True)
    log_handle = runtime_log.open("a", encoding="utf-8")

    proc_env = os.environ.copy()
    proc_env.update(_read_env_file(env_path))
    proc_env.update(runtime_env_overrides or {})
    proc_env["HERMES_HOME"] = str(clone_root / ".hermes")
    proc_env["HOME"] = str(clone_root)
    proc_env["USER"] = str(proc_env.get("USER") or "ubuntu")
    proc_env["LOGNAME"] = str(proc_env.get("LOGNAME") or proc_env["USER"])
    proc_env["NODE_NAME"] = str(proc_env.get("NODE_NAME") or clone_name)
    proc_env["HERMES_DISCORD_PLUGIN_DIR"] = str(DEFAULT_DISCORD_PLUGIN_ROOT)
    proc_env["HERMES_CORE_PLUGIN_DIR"] = str(DEFAULT_HERMES_CORE_PLUGIN_ROOT)
    proc_env["HERMES_DISCORD_PRIVATE_DIR"] = str(DEFAULT_DISCORD_PRIVATE_ROOT)
    proc_env["HERMES_PUBLIC_PLUGINS_ROOT"] = str(SHARED_PLUGINS_ROOT)
    proc_env["HERMES_PRIVATE_PLUGINS_ROOT"] = str(PRIVATE_PLUGINS_ROOT)
    proc_env["HERMES_PUBLIC_SCRIPTS_ROOT"] = str(SHARED_SCRIPTS_ROOT)
    proc_env["HERMES_PRIVATE_SCRIPTS_ROOT"] = str(PRIVATE_SCRIPTS_ROOT)
    proc_env["HERMES_AGENT_ROOT"] = str(runtime_agent_root)
    proc_env["HERMES_NODE_ROOT"] = str(clone_root)
    proc_env["HERMES_WIKI_ROOT"] = str(clone_root / "wiki")
    proc_env["PYTHONUNBUFFERED"] = "1"

    # Keep host-layer orchestrator behavior aligned with container nodes:
    # reapply Discord/runtime patches before gateway launch.
    prestart_script = _prestart_script_path()
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
    for legacy_pid in _orchestrator_legacy_pid_paths(clone_root):
        if legacy_pid == pid_path or not legacy_pid.exists():
            continue
        try:
            legacy_pid.unlink()
        except Exception:
            pass

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
    state = _orchestrator_process_state(clone_root)
    pid = state.get("pid")
    running = bool(state.get("running"))
    if not running or not isinstance(pid, int):
        for pid_path in _orchestrator_pid_candidates(clone_root):
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

    for pid_path in _orchestrator_pid_candidates(clone_root):
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
    env_autocreate = _ensure_clone_env_file(clone_name)
    env = _read_env_file(env_path)
    clone_root = _clone_root_path(clone_name)
    _ensure_node_log_topology(clone_name)
    container = _container_name(clone_name)
    state_code = _extract_state_mode(env)
    is_orchestrator = state_code == 1

    if clone_root.exists():
        # Heal legacy root-owned artifacts before any bootstrap writes.
        _ensure_clone_ownership(clone_root)
    discord_home_sync = _sync_discord_home_channel_env(clone_name, env_path)
    restart_reboot_sync = _sync_restart_reboot_env(clone_name, env_path)
    env = _read_env_file(env_path)
    runtime_env_overrides = _runtime_env_overrides(clone_name, env)
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
                    "model": _default_model_name_from_env(env),
                    "provider": _default_model_provider_from_env(env),
                    "base_url": str(env.get("DEFAULT_MODEL_BASE_URL", "") or ""),
                    "api_mode": str(env.get("DEFAULT_MODEL_API_MODE", "") or ""),
                },
                "fallback": {
                    "model": _fallback_model_name_from_env(env),
                    "provider": _fallback_model_provider_from_env(env),
                    "base_url": str(env.get("FALLBACK_MODEL_BASE_URL", "") or ""),
                    "api_mode": str(env.get("FALLBACK_MODEL_API_MODE", "") or ""),
                },
            },
            "warnings": ["model bootstrap deferred until filesystem seed completes"],
        }
    )
    env = _read_env_file(env_path)
    runtime_env_overrides = _runtime_env_overrides(clone_name, env)
    camofox_enabled = _is_camofox_enabled_env(env)
    openviking_enabled = _is_openviking_enabled_env(env)

    _log(clone_name, f"start requested: container={container} env={env_path}")

    if is_orchestrator and _docker_exists(container):
        # Heals legacy deployments where orchestrator used to run in Docker.
        _run(["docker", "rm", "-f", container], check=False)

    if not is_orchestrator and _docker_running(container):
        state = _docker_state(container)
        missing_mounts = _missing_required_worker_mounts(container, clone_name, clone_root)
        status = str(state.get("status") or "").strip().lower()
        if status != "restarting" and not missing_mounts:
            _ensure_worker_shared_mount_links(clone_root, clone_name, refresh_mirrors=False)
            return {
                "ok": True,
                "action": "start",
                "result": "already_running",
                "clone_name": clone_name,
                "container_name": container,
                "state_mode": STATE_LABELS.get(_extract_state_mode(env), "unknown"),
                "container_state": state,
                "env_autocreate": env_autocreate,
                "log_file": str(_management_log_path(clone_name)),
                "runtime_log_file": str(_clone_runtime_log_path(clone_name, clone_root=clone_root)),
                "attention_log_file": str(_attention_log_path(clone_name)),
                "hermes_log_dir": str(_clone_hermes_log_dir(clone_name, clone_root=clone_root)),
                "camofox": camofox_bootstrap,
                "openviking": openviking_bootstrap,
                "models": model_bootstrap,
                "discord_home_channel": str(runtime_env_overrides.get("DISCORD_HOME_CHANNEL", "") or ""),
                "discord_home_channel_sync": discord_home_sync,
                "restart_reboot_sync": restart_reboot_sync,
                "required_mounts_ok": True,
                "required_mounts_missing": [],
            }

        if status == "restarting":
            _log(
                clone_name,
                "start requested while container was restarting; forcing recreate",
            )
        else:
            _log(
                clone_name,
                "start requested while container had stale/missing mounts; forcing recreate: "
                + "; ".join(missing_mounts),
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
        runtime_env_overrides = _runtime_env_overrides(clone_name, env)
        openviking_enabled = _is_openviking_enabled_env(env)

        if fs_meta.get("orchestrator_baremetal"):
            host_start = _orchestrator_start_gateway(
                clone_name,
                clone_root,
                env_path,
                runtime_env_overrides=runtime_env_overrides,
            )
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
                "env_autocreate": env_autocreate,
                "log_file": str(_management_log_path(clone_name)),
                "runtime_log_file": str(_clone_runtime_log_path(clone_name, clone_root=clone_root)),
                "attention_log_file": str(_attention_log_path(clone_name)),
                "hermes_log_dir": str(_clone_hermes_log_dir(clone_name, clone_root=clone_root)),
                "camofox": camofox_bootstrap,
                "openviking": openviking_bootstrap,
                "models": model_bootstrap,
                "discord_home_channel": str(runtime_env_overrides.get("DISCORD_HOME_CHANNEL", "") or ""),
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
            runtime_env_overrides=runtime_env_overrides,
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
            "env_autocreate": env_autocreate,
            "log_file": str(_management_log_path(clone_name)),
            "runtime_log_file": str(_clone_runtime_log_path(clone_name, clone_root=clone_root)),
            "attention_log_file": str(_attention_log_path(clone_name)),
            "hermes_log_dir": str(_clone_hermes_log_dir(clone_name, clone_root=clone_root)),
            "camofox": camofox_bootstrap,
            "openviking": openviking_bootstrap,
            "models": model_bootstrap,
            "discord_home_channel": str(runtime_env_overrides.get("DISCORD_HOME_CHANNEL", "") or ""),
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
    env_autocreate = _ensure_clone_env_file(clone_name)
    env_path = _clone_env_path(clone_name)
    clone_root = _clone_root_path(clone_name)
    _ensure_node_log_topology(clone_name)
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
    required_mounts_missing: list[str] = []
    required_mounts_ok: bool | None = None
    if not is_orchestrator and state.get("exists"):
        required_mounts_missing = _missing_required_worker_mounts(container, clone_name, clone_root)
        required_mounts_ok = not required_mounts_missing
    runtime_contract_path = _clone_runtime_contract_path(clone_root)
    mgmt_log_file = _management_log_path(clone_name)
    openviking_account, openviking_user = _resolve_openviking_identity(env, clone_name) if env else ("", "")
    restart_reboot = _effective_restart_reboot_env(env) if env else {
        "restart_cmd": "",
        "reboot_cmd": "",
        "restart_delay_sec": "",
        "reboot_delay_sec": "",
    }
    return {
        "ok": True,
        "action": "status",
        "clone_name": clone_name,
        "container_name": "" if is_orchestrator else container,
        "runtime_type": "baremetal" if is_orchestrator else "container",
        "env_exists": env_path.exists(),
        "env_path": str(env_path),
        "env_autocreate": env_autocreate,
        "clone_root_exists": clone_root.exists(),
        "clone_root": str(clone_root),
        "state_mode": state_mode,
        "state_code": state_code,
        "camofox_enabled": _is_camofox_enabled_env(env) if env else False,
        "camofox_url": str(env.get("CAMOFOX_URL", "") or "") if env else "",
        "openviking_enabled": _is_openviking_enabled_env(env) if env else False,
        "openviking_endpoint": str(env.get("OPENVIKING_ENDPOINT", "") or "") if env else "",
        "openviking_account": openviking_account,
        "openviking_user": openviking_user,
        "openviking_supported": _clone_supports_openviking(clone_root) if clone_root.exists() else False,
        "default_model_env": _default_model_name_from_env(env) if env else "",
        "default_model_provider_env": _default_model_provider_from_env(env) if env else "",
        "fallback_model_env": _fallback_model_name_from_env(env) if env else "",
        "fallback_model_provider_env": _fallback_model_provider_from_env(env) if env else "",
        "discord_home_channel": _effective_discord_home_channel(env) if env else "",
        "discord_home_channel_id": str(env.get("DISCORD_HOME_CHANNEL_ID", "") or "") if env else "",
        "discord_restart_cmd": restart_reboot["restart_cmd"],
        "discord_reboot_cmd": restart_reboot["reboot_cmd"],
        "discord_restart_delay_sec": restart_reboot["restart_delay_sec"],
        "discord_reboot_delay_sec": restart_reboot["reboot_delay_sec"],
        "container_state": state,
        "required_mounts_ok": required_mounts_ok,
        "required_mounts_missing": required_mounts_missing,
        "runtime_contract_path": str(runtime_contract_path),
        "runtime_contract_exists": runtime_contract_path.exists(),
        "log_file": str(mgmt_log_file),
        "runtime_log_file": str(_clone_runtime_log_path(clone_name, clone_root=clone_root)),
        "attention_log_file": str(_attention_log_path(clone_name)),
        "hermes_log_dir": str(_clone_hermes_log_dir(clone_name, clone_root=clone_root)),
    }


def _action_stop(clone_name: str) -> Dict[str, Any]:
    container = _container_name(clone_name)
    env_autocreate = _ensure_clone_env_file(clone_name)
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
            "env_autocreate": env_autocreate,
        }

    if not _docker_exists(container):
        return {
            "ok": True,
            "action": "stop",
            "result": "not_found",
            "clone_name": clone_name,
            "container_name": container,
            "runtime_type": "container",
            "env_autocreate": env_autocreate,
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
        "env_autocreate": env_autocreate,
    }


def _action_delete(clone_name: str) -> Dict[str, Any]:
    container = _container_name(clone_name)
    env_autocreate = _ensure_clone_env_file(clone_name)
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
        "env_autocreate": env_autocreate,
    }


def _tail_file(path: Path, lines: int) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="ignore")
    parts = text.splitlines()
    return "\n".join(parts[-lines:])


def _truncate_log_file(path: Path) -> tuple[bool, str | None]:
    target = path
    try:
        if path.is_symlink():
            try:
                target = path.resolve(strict=True)
            except FileNotFoundError:
                return False, "broken_symlink"
        if not target.exists() or not target.is_file():
            return False, "not_file"
        with target.open("w", encoding="utf-8"):
            pass
        return True, None
    except Exception as exc:
        return False, str(exc)


def _discover_log_node_names() -> list[str]:
    names: set[str] = set(_discover_node_names())

    for root in (NODE_LOG_ROOT, ATTENTION_LOG_ROOT):
        try:
            if root.exists():
                for node_dir in root.iterdir():
                    if node_dir.is_dir():
                        names.add(node_dir.name)
        except Exception:
            continue

    ordered: list[str] = []
    for raw in sorted(names):
        try:
            ordered.append(_normalize_clone_name(raw))
        except Exception:
            continue
    return ordered


def _collect_node_log_files(clone_name: str) -> list[Path]:
    files: set[Path] = {
        _canonical_management_log_path(clone_name),
        _canonical_runtime_log_path(clone_name),
        _canonical_attention_log_path(clone_name),
        _node_hermes_log_dir(clone_name) / "agent.log",
        _node_hermes_log_dir(clone_name) / "errors.log",
        _node_hermes_log_dir(clone_name) / "gateway.log",
        _node_attention_dir(clone_name) / "hermes-errors.log",
    }

    for root in (_node_log_dir(clone_name), _node_attention_dir(clone_name)):
        if not root.exists():
            continue
        for path in root.rglob("*.log"):
            files.add(path)

    return sorted(files, key=lambda p: str(p))


def _action_logs_clean(clone_name: str | None, *, clean_all: bool) -> Dict[str, Any]:
    targets: list[str]
    if clean_all:
        targets = _discover_log_node_names()
    else:
        if not clone_name:
            raise CloneManagerError("logs clean requires node name or --all")
        targets = [clone_name]

    if not targets:
        return {
            "ok": True,
            "action": "logs_clean",
            "scope": "all" if clean_all else "node",
            "cleaned_nodes": [],
            "cleaned_files": 0,
            "skipped_files": 0,
            "failed": [],
        }

    cleaned_files = 0
    skipped_files = 0
    failed: list[Dict[str, str]] = []
    cleaned_nodes: list[str] = []

    for node in targets:
        _ensure_node_log_topology(node)
        cleaned_nodes.append(node)
        for log_path in _collect_node_log_files(node):
            ok, reason = _truncate_log_file(log_path)
            if ok:
                cleaned_files += 1
            else:
                skipped_files += 1
                if reason not in {"not_file", "broken_symlink"}:
                    failed.append(
                        {
                            "node": node,
                            "path": str(log_path),
                            "error": str(reason or "unknown"),
                        }
                    )

    return {
        "ok": len(failed) == 0,
        "action": "logs_clean",
        "scope": "all" if clean_all else "node",
        "cleaned_nodes": cleaned_nodes,
        "cleaned_files": cleaned_files,
        "skipped_files": skipped_files,
        "failed": failed,
    }


def _action_logs(clone_name: str, lines: int) -> Dict[str, Any]:
    clone_root: Path | None = None
    try:
        clone_root = _clone_root_path(clone_name)
    except Exception:
        clone_root = None
    _ensure_node_log_topology(clone_name)

    mgmt_log_file = _management_log_path(clone_name)
    runtime_log_file = _clone_runtime_log_path(clone_name)
    attention_log_file = _attention_log_path(clone_name)
    hermes_errors_log_file = _clone_hermes_log_path(clone_name, "errors.log", clone_root=clone_root)
    hermes_gateway_log_file = _clone_hermes_log_path(clone_name, "gateway.log", clone_root=clone_root)
    hermes_agent_log_file = _clone_hermes_log_path(clone_name, "agent.log", clone_root=clone_root)
    mgmt_text = _tail_file(mgmt_log_file, lines)
    runtime_text = _tail_file(runtime_log_file, lines)
    attention_text = _tail_file(attention_log_file, lines)
    hermes_errors_text = _tail_file(hermes_errors_log_file, lines)
    hermes_gateway_text = _tail_file(hermes_gateway_log_file, lines)
    hermes_agent_text = _tail_file(hermes_agent_log_file, lines)

    chunks: list[str] = []
    if mgmt_text:
        chunks.append(f"== management ({mgmt_log_file}) ==\n{mgmt_text}")
    if runtime_text:
        chunks.append(f"== runtime ({runtime_log_file}) ==\n{runtime_text}")
    if attention_text:
        chunks.append(f"== attention (warning+) ({attention_log_file}) ==\n{attention_text}")
    if hermes_errors_text:
        chunks.append(f"== hermes errors (warning+) ({hermes_errors_log_file}) ==\n{hermes_errors_text}")
    if hermes_gateway_text:
        chunks.append(f"== hermes gateway ({hermes_gateway_log_file}) ==\n{hermes_gateway_text}")
    if hermes_agent_text:
        chunks.append(f"== hermes agent ({hermes_agent_log_file}) ==\n{hermes_agent_text}")
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
        "attention_log_file": str(attention_log_file),
        "hermes_log_dir": str(_clone_hermes_log_dir(clone_name, clone_root=clone_root)),
        "hermes_errors_log_file": str(hermes_errors_log_file),
        "hermes_gateway_log_file": str(hermes_gateway_log_file),
        "hermes_agent_log_file": str(hermes_agent_log_file),
        "lines": lines,
        "log_text": text,
    }


def _discover_node_names() -> list[str]:
    names: set[str] = set()

    try:
        for env_path in ENVS_ROOT.glob("*.env"):
            if env_path.is_file():
                names.add(env_path.stem)
    except Exception:
        pass

    try:
        if CLONES_ROOT.exists():
            for node_root in CLONES_ROOT.iterdir():
                if node_root.is_dir():
                    names.add(node_root.name)
    except Exception:
        pass

    ordered: list[str] = []
    for raw in sorted(names):
        try:
            ordered.append(_normalize_clone_name(raw))
        except Exception:
            continue
    return ordered


def _action_backup(clone_name: str | None, *, backup_all: bool) -> Dict[str, Any]:
    target_nodes: list[str]
    skipped_nodes: list[str] = []
    if backup_all:
        discovered = _discover_node_names()
        target_nodes = []
        for node in discovered:
            if _clone_env_path(node).exists():
                target_nodes.append(node)
            else:
                skipped_nodes.append(node)
        if not target_nodes:
            raise CloneManagerError("no node profiles found to back up")
    else:
        if not clone_name:
            raise CloneManagerError("backup node requires clone name")
        target_nodes = [clone_name]

    BACKUPS_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    scope = "all" if backup_all else f"node-{target_nodes[0]}"
    archive_name = f"horc-backup-{scope}-{stamp}.tar.gz"
    archive_path = BACKUPS_ROOT / archive_name

    included: list[str] = []
    missing: list[str] = []
    included_global: list[str] = []
    included_runtime_seed: list[str] = []
    included_workspace_paths: list[str] = []
    request_dump_pruning: Dict[str, Any] = {}

    global_candidates: list[Path] = [
        PRIVATE_SCRIPTS_ROOT,
        PRIVATE_PLUGINS_ROOT,
        PRIVATE_SKILLS_ROOT,
        SHARED_WIKI_ROOT,
        SHARED_CRONS_ROOT,
        SHARED_MEMORY_ROOT,
        SHARED_NODE_DATA_ROOT if backup_all else _shared_node_data_dir(target_nodes[0]),
    ]
    if not backup_all:
        node_name = target_nodes[0]
        global_candidates.extend(
            [
                SHARED_MEMORY_ROOT / "openviking" / node_name,
                SHARED_MEMORY_ROOT / "viking" / node_name,
                SHARED_CRONS_ROOT / node_name,
            ]
        )

    dump_keep_last = _int_env("HERMES_REQUEST_DUMP_KEEP_LAST", 200)
    dump_keep_days = _int_env("HERMES_REQUEST_DUMP_KEEP_DAYS", 14)
    for node in target_nodes:
        prune_meta = _prune_request_dump_files(
            node,
            _clone_root_path(node),
            keep_last=dump_keep_last,
            keep_days=dump_keep_days,
        )
        if prune_meta.get("scanned", 0) > 0 or prune_meta.get("policy_enabled"):
            request_dump_pruning[node] = prune_meta

    with tarfile.open(archive_path, "w:gz") as tf:
        registry_added = _archive_add_path(tf, REGISTRY_PATH)
        if registry_added:
            included.append(registry_added)

        seen_global: set[str] = set()
        seen_global_roots: list[Path] = []
        for global_path in global_candidates:
            resolved = global_path.resolve() if global_path.exists() else global_path
            key = str(resolved)
            if key in seen_global:
                continue
            if any(
                resolved == root or str(resolved).startswith(f"{root}/")
                for root in seen_global_roots
            ):
                continue
            seen_global.add(key)
            added = _archive_add_path(tf, global_path)
            if added is not None:
                included.append(added)
                included_global.append(added)
                seen_global_roots.append(resolved)

        runtime_seed_specs = [
            {
                "source": HERMES_SOURCE_ROOT,
                "archive_name": "runtime_seed/hermes-agent",
                "exclude": (".venv", ".pytest_cache"),
            },
            {
                "source": HERMES_SOURCE_ROOT / ".venv",
                "archive_name": "runtime_seed/venv",
                "exclude": (),
            },
            {
                "source": PARENT_UV_STORE,
                "archive_name": "runtime_seed/uv",
                "exclude": (),
            },
        ]
        for spec in runtime_seed_specs:
            runtime_added = _archive_add_path(
                tf,
                Path(spec["source"]),
                archive_name=str(spec["archive_name"]),
                exclude_relative_prefixes=tuple(spec["exclude"]),
            )
            if runtime_added is not None:
                included.append(runtime_added)
                included_global.append(runtime_added)
                included_runtime_seed.append(runtime_added)
            else:
                missing.append(str(spec["source"]))

        for node in target_nodes:
            env_path = _clone_env_path(node)
            node_root = _clone_root_path(node)

            env_added = _archive_add_path(tf, env_path)
            if env_added is not None:
                included.append(env_added)
            else:
                missing.append(str(env_path))

            node_added = _archive_add_path(
                tf,
                node_root,
                exclude_relative_prefixes=NODE_BACKUP_EXCLUDE_PREFIXES,
            )
            if node_added is not None:
                included.append(node_added)
                workspace_arc = f"{node_added}/workspace"
                workspace_src = node_root / "workspace"
                if workspace_src.exists():
                    included_workspace_paths.append(workspace_arc)
                else:
                    missing.append(str(workspace_src))
            else:
                missing.append(str(node_root))

    backup_retention = _prune_backup_archives(
        keep_last=_int_env("HERMES_BACKUP_KEEP_LAST", 0),
    )
    size_bytes = archive_path.stat().st_size if archive_path.exists() else 0
    for node in target_nodes:
        _log(node, f"backup created: {archive_path}")

    return {
        "ok": True,
        "action": "backup",
        "scope": "all" if backup_all else "node",
        "nodes": target_nodes,
        "skipped_nodes": skipped_nodes,
        "archive": str(archive_path),
        "size_bytes": int(size_bytes),
        "included_paths": included,
        "included_global_paths": included_global,
        "included_runtime_seed_paths": included_runtime_seed,
        "included_workspace_paths": included_workspace_paths,
        "missing_paths": missing,
        "request_dump_pruning": request_dump_pruning,
        "backup_retention": backup_retention,
    }


def _restore_agents_root(restore_root: Path) -> Path:
    if (restore_root / "agents").is_dir():
        return restore_root / "agents"
    if restore_root.name == "agents" and restore_root.is_dir():
        return restore_root
    raise CloneManagerError(
        f"restore source does not include an agents/ tree: {restore_root}"
    )


def _collect_restore_source(restore_root: Path) -> Dict[str, Any]:
    agents_root = _restore_agents_root(restore_root)
    env_dir = agents_root / "envs"
    nodes_dir = agents_root / "nodes"
    registry_path = agents_root / "registry.json"

    env_files: Dict[str, Path] = {}
    if env_dir.exists():
        for env_path in sorted(env_dir.glob("*.env")):
            node = _normalize_clone_name(env_path.stem)
            env_files[node] = env_path

    node_dirs: Dict[str, Path] = {}
    if nodes_dir.exists():
        for node_path in sorted(nodes_dir.iterdir()):
            if not node_path.is_dir():
                continue
            node = _normalize_clone_name(node_path.name)
            node_dirs[node] = node_path

    if not registry_path.exists() and not env_files and not node_dirs:
        raise CloneManagerError(
            f"restore source has no registry/envs/nodes payload: {restore_root}"
        )

    legacy_private_root = agents_root / "private"
    runtime_seed_root = restore_root / "runtime_seed"

    return {
        "agents_root": agents_root,
        "registry_path": registry_path if registry_path.exists() else None,
        "env_files": env_files,
        "node_dirs": node_dirs,
        "private_scripts_path": (
            (restore_root / "scripts" / "private")
            if (restore_root / "scripts" / "private").exists()
            else ((legacy_private_root / "scripts") if (legacy_private_root / "scripts").exists() else None)
        ),
        "private_plugins_path": (
            (restore_root / "plugins" / "private")
            if (restore_root / "plugins" / "private").exists()
            else ((legacy_private_root / "plugins") if (legacy_private_root / "plugins").exists() else None)
        ),
        "skills_path": (
            (restore_root / "skills")
            if (restore_root / "skills").exists()
            else ((legacy_private_root / "skills") if (legacy_private_root / "skills").exists() else None)
        ),
        "crons_path": (
            (restore_root / "crons")
            if (restore_root / "crons").exists()
            else ((legacy_private_root / "crons") if (legacy_private_root / "crons").exists() else None)
        ),
        "legacy_shared_wiki_path": (
            (legacy_private_root / "shared" / "wiki")
            if (legacy_private_root / "shared" / "wiki").exists()
            else None
        ),
        "legacy_shared_memory_path": (
            (legacy_private_root / "shared" / "memory")
            if (legacy_private_root / "shared" / "memory").exists()
            else None
        ),
        "datas_path": (
            (restore_root / "datas")
            if (restore_root / "datas").exists()
            else ((restore_root / "data") if (restore_root / "data").exists() else None)
        ),
        "runtime_seed_hermes_path": (
            (runtime_seed_root / "hermes-agent")
            if (runtime_seed_root / "hermes-agent").exists()
            else None
        ),
        "runtime_seed_venv_path": (
            (runtime_seed_root / "venv")
            if (runtime_seed_root / "venv").exists()
            else None
        ),
        "runtime_seed_uv_path": (
            (runtime_seed_root / "uv")
            if (runtime_seed_root / "uv").exists()
            else None
        ),
    }


def _action_restore(restore_path: str) -> Dict[str, Any]:
    resolved = _resolve_backup_path(restore_path)
    archive_meta: Dict[str, Any] | None = None
    source_kind = "directory"

    with tempfile.TemporaryDirectory(prefix="horc-restore-", dir=str(BACKUPS_ROOT)) as tmp:
        restore_root: Path
        if resolved.is_file():
            source_kind = "archive"
            restore_root = Path(tmp)
            archive_meta = _extract_backup_archive(resolved, restore_root)
        elif resolved.is_dir():
            restore_root = resolved
        else:
            raise CloneManagerError(f"restore path is neither file nor directory: {resolved}")

        source = _collect_restore_source(restore_root)
        env_files: Dict[str, Path] = source["env_files"]
        node_dirs: Dict[str, Path] = source["node_dirs"]
        registry_path = source["registry_path"]
        private_scripts_path: Path | None = source.get("private_scripts_path")
        private_plugins_path: Path | None = source.get("private_plugins_path")
        skills_path: Path | None = source.get("skills_path")
        crons_path: Path | None = source.get("crons_path")
        legacy_shared_wiki_path: Path | None = source.get("legacy_shared_wiki_path")
        legacy_shared_memory_path: Path | None = source.get("legacy_shared_memory_path")
        datas_path: Path | None = source.get("datas_path")
        runtime_seed_hermes_path: Path | None = source.get("runtime_seed_hermes_path")
        runtime_seed_venv_path: Path | None = source.get("runtime_seed_venv_path")
        runtime_seed_uv_path: Path | None = source.get("runtime_seed_uv_path")

        target_nodes = sorted(set(env_files) | set(node_dirs))
        running_before: list[str] = []
        stop_results: Dict[str, str] = {}

        for node in target_nodes:
            status_before = _action_status(node)
            was_running = bool((status_before.get("container_state") or {}).get("running"))
            if not was_running:
                continue
            stop_payload = _action_stop(node)
            stop_results[node] = str(stop_payload.get("result") or "")
            status_after = _action_status(node)
            if bool((status_after.get("container_state") or {}).get("running")):
                raise CloneManagerError(f"failed to stop node before restore: {node}")
            running_before.append(node)

        restored_registry = False
        if isinstance(registry_path, Path) and registry_path.exists():
            REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(registry_path, REGISTRY_PATH)
            restored_registry = True

        restored_envs: list[str] = []
        for node, env_src in sorted(env_files.items()):
            env_dst = ENVS_ROOT / f"{node}.env"
            env_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(env_src, env_dst)
            try:
                env_dst.chmod(0o600)
            except Exception:
                pass
            restored_envs.append(str(env_dst))

        restored_runtime_seed: Dict[str, str] = {}
        if isinstance(runtime_seed_hermes_path, Path) and runtime_seed_hermes_path.exists():
            HERMES_SOURCE_ROOT.parent.mkdir(parents=True, exist_ok=True)
            _sync_dir(runtime_seed_hermes_path, HERMES_SOURCE_ROOT, delete=True)
            restored_runtime_seed["hermes_agent_root"] = str(HERMES_SOURCE_ROOT)
        if isinstance(runtime_seed_venv_path, Path) and runtime_seed_venv_path.exists():
            target_venv = HERMES_SOURCE_ROOT / ".venv"
            target_venv.parent.mkdir(parents=True, exist_ok=True)
            _sync_dir(runtime_seed_venv_path, target_venv, delete=True)
            restored_runtime_seed["seed_venv"] = str(target_venv)
        if isinstance(runtime_seed_uv_path, Path) and runtime_seed_uv_path.exists():
            PARENT_UV_STORE.parent.mkdir(parents=True, exist_ok=True)
            _sync_dir(runtime_seed_uv_path, PARENT_UV_STORE, delete=True)
            restored_runtime_seed["seed_uv_store"] = str(PARENT_UV_STORE)

        runtime_seed_source: Path | None
        try:
            runtime_seed_source = _parent_hermes_agent_source(clone_name="orchestrator")
        except CloneManagerError:
            runtime_seed_source = None

        restored_nodes: list[str] = []
        runtime_reseeded_nodes: list[str] = []
        for node, node_src in sorted(node_dirs.items()):
            node_dst = CLONES_ROOT / node
            if node_dst.exists() or node_dst.is_symlink():
                _remove_path(node_dst)
            _sync_dir(node_src, node_dst, delete=True)
            _ensure_clone_ownership(node_dst)
            _ensure_workspace_data_layout(node_dst, node)
            node_env = _read_env_file(ENVS_ROOT / f"{node}.env")
            try:
                restored_mode = _extract_state_mode(node_env)
            except CloneManagerError:
                restored_mode = 2
            if restored_mode == 1:
                _set_symlink(node_dst / "scripts", SCRIPTS_ROOT)
                _set_symlink(node_dst / "plugins", PLUGINS_ROOT)
                _set_symlink(node_dst / "cron", _orchestrator_cron_host_dir(node))
                legacy_crons = node_dst / "crons"
                if legacy_crons.exists() or legacy_crons.is_symlink():
                    _remove_path(legacy_crons)
            else:
                _ensure_worker_shared_mount_links(node_dst, node)

            runtime_missing = (
                not (node_dst / "hermes-agent" / "cli.py").exists()
                or not (node_dst / RUNTIME_UV_REL).exists()
            )
            if runtime_missing:
                if runtime_seed_source is None:
                    raise CloneManagerError(
                        "restore payload requires runtime reseed but no seed source is available. "
                        "Expected /local/hermes-agent or runtime_seed/hermes-agent in the backup."
                    )
                if restored_mode == 1:
                    _prepare_orchestrator_runtime_agent_tree(
                        clone_name=node,
                        clone_root=node_dst,
                        source_tree=runtime_seed_source,
                    )
                    _ensure_orchestrator_runtime(node)
                else:
                    _seed_code_tree(runtime_seed_source, node_dst / "hermes-agent")
                    _seed_clone_runtime(node_dst, allow_parent_seed=True)
                runtime_reseeded_nodes.append(node)

            _sync_discord_runtime_layout(node_dst, node, node_env)
            _sync_node_wiki_link(node_dst, node_env, containerized=(restored_mode != 1))
            _log(node, f"restore applied from {resolved}")
            restored_nodes.append(node)

        restored_private_plugins_root = ""
        if isinstance(private_plugins_path, Path) and private_plugins_path.exists():
            PRIVATE_PLUGINS_ROOT.mkdir(parents=True, exist_ok=True)
            _sync_dir(private_plugins_path, PRIVATE_PLUGINS_ROOT, delete=False)
            restored_private_plugins_root = str(PRIVATE_PLUGINS_ROOT)
        if isinstance(legacy_shared_wiki_path, Path) and legacy_shared_wiki_path.exists():
            target = PRIVATE_PLUGINS_ROOT / "wiki"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.mkdir(parents=True, exist_ok=True)
            _sync_dir(legacy_shared_wiki_path, target, delete=False)
            restored_private_plugins_root = str(PRIVATE_PLUGINS_ROOT)
        if isinstance(legacy_shared_memory_path, Path) and legacy_shared_memory_path.exists():
            target = PRIVATE_PLUGINS_ROOT / "memory"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.mkdir(parents=True, exist_ok=True)
            _sync_dir(legacy_shared_memory_path, target, delete=False)
            restored_private_plugins_root = str(PRIVATE_PLUGINS_ROOT)

        restored_private_scripts_root = ""
        if isinstance(private_scripts_path, Path) and private_scripts_path.exists():
            PRIVATE_SCRIPTS_ROOT.mkdir(parents=True, exist_ok=True)
            _sync_dir(private_scripts_path, PRIVATE_SCRIPTS_ROOT, delete=False)
            restored_private_scripts_root = str(PRIVATE_SCRIPTS_ROOT)

        restored_memory_root = str(SHARED_MEMORY_ROOT) if SHARED_MEMORY_ROOT.exists() else ""

        restored_datas_root = ""
        if isinstance(datas_path, Path) and datas_path.exists():
            SHARED_NODE_DATA_ROOT.parent.mkdir(parents=True, exist_ok=True)
            SHARED_NODE_DATA_ROOT.mkdir(parents=True, exist_ok=True)
            _sync_dir(datas_path, SHARED_NODE_DATA_ROOT, delete=False)
            restored_datas_root = str(SHARED_NODE_DATA_ROOT)
        elif SHARED_NODE_DATA_ROOT.exists():
            restored_datas_root = str(SHARED_NODE_DATA_ROOT)

        restored_skills_root = ""
        if isinstance(skills_path, Path) and skills_path.exists():
            PRIVATE_SKILLS_ROOT.parent.mkdir(parents=True, exist_ok=True)
            PRIVATE_SKILLS_ROOT.mkdir(parents=True, exist_ok=True)
            _sync_dir(skills_path, PRIVATE_SKILLS_ROOT, delete=False)
            restored_skills_root = str(PRIVATE_SKILLS_ROOT)

        restored_crons_root = ""
        if isinstance(crons_path, Path) and crons_path.exists():
            SHARED_CRONS_ROOT.parent.mkdir(parents=True, exist_ok=True)
            SHARED_CRONS_ROOT.mkdir(parents=True, exist_ok=True)
            _sync_dir(crons_path, SHARED_CRONS_ROOT, delete=False)
            restored_crons_root = str(SHARED_CRONS_ROOT)
        elif SHARED_CRONS_ROOT.exists():
            restored_crons_root = str(SHARED_CRONS_ROOT)

        restarted_nodes: list[str] = []
        restart_errors: Dict[str, str] = {}
        for node in running_before:
            env_path = _clone_env_path(node)
            node_root = _clone_root_path(node)
            if not env_path.exists() or not node_root.exists():
                restart_errors[node] = "skipped: env or node root missing after restore"
                continue
            try:
                _action_start(node, image=DEFAULT_DOCKER_IMAGE)
                restarted_nodes.append(node)
            except Exception as exc:
                restart_errors[node] = str(exc)

    return {
        "ok": True,
        "action": "restore",
        "source": str(resolved),
        "source_kind": source_kind,
        "restored_registry": restored_registry,
        "restored_envs": restored_envs,
        "restored_nodes": restored_nodes,
        "restored_private_scripts_root": restored_private_scripts_root,
        "restored_private_plugins_root": restored_private_plugins_root,
        "restored_memory_root": restored_memory_root,
        "restored_datas_root": restored_datas_root,
        "restored_skills_root": restored_skills_root,
        "restored_crons_root": restored_crons_root,
        "restored_runtime_seed": restored_runtime_seed,
        "runtime_reseeded_nodes": runtime_reseeded_nodes,
        "stopped_before_restore": running_before,
        "stop_results": stop_results,
        "restarted_after_restore": restarted_nodes,
        "restart_errors": restart_errors,
        "archive": archive_meta,
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


def _action_update_test(
    clone_name: str | None,
    source_branch: str,
    deprecate_plugins: list[str],
) -> Dict[str, Any]:
    requested_name = str(clone_name or UPDATE_TEST_NODE_DEFAULT).strip() or UPDATE_TEST_NODE_DEFAULT
    test_node = _normalize_clone_name(requested_name)
    if test_node == "orchestrator":
        raise CloneManagerError("update test target cannot be orchestrator; use a dedicated dummy node")

    run_dir, run_id, log_root_warning = _create_update_run_dir("test")
    report_path = run_dir / "report.json"
    plugin_matrix_path = run_dir / "plugin_matrix.json"
    prestart_stdout_log = run_dir / "prestart.stdout.log"
    prestart_stderr_log = run_dir / "prestart.stderr.log"
    prestart_log_copy = run_dir / "colmeio-prestart.log"

    payload: Dict[str, Any] = {
        "ok": False,
        "action": "update-test",
        "clone_name": test_node,
        "run_id": run_id,
        "result": False,
        "report_path": str(report_path),
        "plugin_matrix_path": str(plugin_matrix_path),
        "log_root_requested": str(UPDATE_TEST_LOG_ROOT.expanduser()),
        "log_root": str(run_dir.parent),
        "log_root_warning": log_root_warning,
        "run_dir": str(run_dir),
        "source_branch": str(source_branch or HERMES_AGENT_UPSTREAM_BRANCH),
        "deprecate_plugins": list(deprecate_plugins),
    }
    prestart_stdout_log.write_text("", encoding="utf-8")
    prestart_stderr_log.write_text("", encoding="utf-8")
    _atomic_write_json(
        plugin_matrix_path,
        {
            "steps": [],
            "summary": {
                "passed": 0,
                "failed": 0,
                "skipped_deprecated": 0,
                "pending": 0,
                "total": 0,
            },
            "deprecated_plugins": list(deprecate_plugins),
        },
    )

    error_message = ""
    try:
        snapshot_payload = _refresh_dummy_snapshot(source_branch, deprecate_plugins)
        payload["dummy_snapshot"] = snapshot_payload
        effective_deprecated_plugins = sorted(
            set(
                list(deprecate_plugins)
                + list(snapshot_payload.get("deprecated_plugins_present") or [])
            )
        )
        payload["effective_deprecated_plugins"] = effective_deprecated_plugins
        payload["deprecated_plugins_applied"] = list(snapshot_payload.get("deprecated_plugins_applied") or [])
        payload["deprecated_plugins_already_present"] = list(
            snapshot_payload.get("deprecated_plugins_already_present") or []
        )
        payload["deprecated_plugins_missing"] = list(snapshot_payload.get("deprecated_plugins_missing") or [])

        env_path = _clone_env_path(test_node)
        clone_root = _clone_root_path(test_node)
        container_name = _container_name(test_node)

        payload["env_path"] = str(env_path)
        payload["clone_root"] = str(clone_root)
        payload["container_name"] = container_name

        if _docker_exists(container_name):
            _run(["docker", "rm", "-f", container_name], check=False)
            _log(test_node, "update test: removed stale dummy container")

        env_seed = _seed_update_test_env_profile(test_node, env_path)
        payload["env_seed"] = env_seed

        if clone_root.exists():
            shutil.rmtree(clone_root, ignore_errors=True)
        node_data_root = _shared_node_data_dir(test_node)
        if node_data_root.exists():
            shutil.rmtree(node_data_root, ignore_errors=True)

        with _temporary_runtime_roots(
            source_root=UPDATE_DUMMY_HERMES_ROOT,
            plugins_root=UPDATE_DUMMY_PLUGINS_ROOT,
            scripts_root=UPDATE_DUMMY_SCRIPTS_ROOT,
        ):
            env = _read_env_file(env_path)
            fs_meta = _prepare_clone_filesystem(test_node, clone_root, env, env_path)
            prestart = _run_prestart_reapply(
                test_node,
                clone_root=clone_root,
                env_path=env_path,
                strict=True,
                capture_output=True,
            )

        payload["filesystem"] = fs_meta
        payload["prestart"] = {
            "script": prestart.get("script"),
            "returncode": prestart.get("returncode"),
            "failed_marker_path": prestart.get("failed_marker_path"),
            "failed_marker_exists": prestart.get("failed_marker_exists"),
            "prestart_log_path": prestart.get("prestart_log_path"),
            "failures": prestart.get("failures"),
        }

        prestart_stdout_log.write_text(str(prestart.get("stdout", "")), encoding="utf-8")
        prestart_stderr_log.write_text(str(prestart.get("stderr", "")), encoding="utf-8")
        payload["prestart_stdout_log"] = str(prestart_stdout_log)
        payload["prestart_stderr_log"] = str(prestart_stderr_log)

        prestart_log_path = Path(str(prestart.get("prestart_log_path") or ""))
        if prestart_log_path.exists():
            shutil.copy2(prestart_log_path, prestart_log_copy)
            payload["prestart_log_copy"] = str(prestart_log_copy)

        plugin_matrix = _build_plugin_matrix(
            prestart_log_path=prestart_log_path,
            deprecated_plugins=effective_deprecated_plugins,
        )
        _atomic_write_json(plugin_matrix_path, plugin_matrix)
        payload["plugin_matrix"] = plugin_matrix.get("summary", {})
        payload["plugin_matrix_path"] = str(plugin_matrix_path)

        failed_steps = prestart.get("failures")
        failed_list = failed_steps if isinstance(failed_steps, list) else []
        matrix_summary = plugin_matrix.get("summary", {}) if isinstance(plugin_matrix, dict) else {}
        matrix_failed = int(matrix_summary.get("failed", 0) or 0)
        matrix_pending = int(matrix_summary.get("pending", 0) or 0)
        failed = (
            bool(prestart.get("returncode"))
            or bool(prestart.get("failed_marker_exists"))
            or matrix_failed > 0
            or matrix_pending > 0
        )
        if failed:
            if failed_list:
                error_message = "prestart reapply failed steps: " + ", ".join(str(step) for step in failed_list)
            elif matrix_failed > 0:
                error_message = f"plugin matrix failed with {matrix_failed} failed step(s)"
            elif matrix_pending > 0:
                error_message = f"plugin matrix has {matrix_pending} unresolved step(s)"
            else:
                error_message = "prestart reapply failed in strict mode"
        else:
            payload["ok"] = True
            payload["result"] = True
            payload["message"] = "update preflight passed"
    except Exception as exc:
        error_message = str(exc) or "unexpected update-test failure"

    if error_message:
        payload["ok"] = False
        payload["result"] = False
        payload["error"] = error_message

    _atomic_write_json(report_path, payload)
    if error_message:
        raise CloneManagerError(f"update test failed; see {report_path} ({error_message})")
    return payload


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


def _promote_dummy_source_to_runtime() -> Dict[str, Any]:
    if not UPDATE_DUMMY_HERMES_ROOT.exists():
        raise CloneManagerError(
            f"dummy hermes snapshot not found: {UPDATE_DUMMY_HERMES_ROOT} "
            "(run 'horc update test' first)"
        )

    before_commit = _git_commit(HERMES_SOURCE_ROOT) if HERMES_SOURCE_ROOT.exists() else ""
    before_branch = _git_branch(HERMES_SOURCE_ROOT) if HERMES_SOURCE_ROOT.exists() else ""
    HERMES_SOURCE_ROOT.parent.mkdir(parents=True, exist_ok=True)
    _sync_dir(UPDATE_DUMMY_HERMES_ROOT, HERMES_SOURCE_ROOT, delete=True)
    after_commit = _git_commit(HERMES_SOURCE_ROOT)
    after_branch = _git_branch(HERMES_SOURCE_ROOT)

    changed = bool(before_commit and after_commit and before_commit != after_commit)
    if not before_commit and after_commit:
        changed = True

    return {
        "source": str(UPDATE_DUMMY_HERMES_ROOT),
        "target": str(HERMES_SOURCE_ROOT),
        "commit_before": before_commit,
        "commit_after": after_commit,
        "branch_before": before_branch,
        "branch_after": after_branch,
        "changed": changed,
    }


def _resolve_apply_target_nodes(target_mode: str, target_nodes_csv: str) -> list[str]:
    mode = str(target_mode or "").strip().lower()
    if mode == "all":
        targets = [name for name in _discover_node_names() if _clone_env_path(name).exists()]
        if not targets:
            raise CloneManagerError("update apply all found no node profiles under /local/agents/envs")
        return targets

    if mode != "node":
        raise CloneManagerError("update apply target mode must be 'all' or 'node'")

    parsed: list[str] = []
    seen: set[str] = set()
    for raw in str(target_nodes_csv or "").split(","):
        value = str(raw or "").strip()
        if not value:
            continue
        node = _normalize_clone_name(value)
        if node in seen:
            continue
        seen.add(node)
        parsed.append(node)

    if not parsed:
        raise CloneManagerError("update apply node requires a comma-separated node list")

    missing_env = [node for node in parsed if not _clone_env_path(node).exists()]
    if missing_env:
        raise CloneManagerError(
            "update apply node includes targets without env profiles: "
            + ", ".join(missing_env)
        )
    return parsed


def _action_restart_node_for_rollout(node_name: str) -> Dict[str, Any]:
    stop_payload = _action_stop(node_name)
    start_payload = _action_start(node_name, image=DEFAULT_DOCKER_IMAGE)
    return {
        "stop": stop_payload,
        "start": start_payload,
    }


def _action_update_apply(
    *,
    target_mode: str,
    target_nodes_csv: str,
    source_branch: str,
    deprecate_plugins: list[str],
) -> Dict[str, Any]:
    run_dir, run_id, log_root_warning = _create_update_run_dir("apply")
    report_path = run_dir / "report.json"
    plugin_matrix_path = run_dir / "plugin_matrix.json"

    payload: Dict[str, Any] = {
        "ok": False,
        "action": "update-apply",
        "run_id": run_id,
        "result": False,
        "target_mode": str(target_mode or ""),
        "target_nodes_csv": str(target_nodes_csv or ""),
        "source_branch": str(source_branch or HERMES_AGENT_UPSTREAM_BRANCH),
        "deprecate_plugins": list(deprecate_plugins),
        "report_path": str(report_path),
        "plugin_matrix_path": str(plugin_matrix_path),
        "run_dir": str(run_dir),
        "log_root_requested": str(UPDATE_TEST_LOG_ROOT.expanduser()),
        "log_root": str(run_dir.parent),
        "log_root_warning": log_root_warning,
    }
    _atomic_write_json(
        plugin_matrix_path,
        {
            "steps": [],
            "summary": {
                "passed": 0,
                "failed": 0,
                "skipped_deprecated": 0,
                "pending": 0,
                "total": 0,
            },
            "deprecated_plugins": list(deprecate_plugins),
        },
    )

    error_message = ""
    targets: list[str] = []
    updated_nodes: list[str] = []
    pending_nodes: list[str] = []
    rollout_results: list[Dict[str, Any]] = []

    try:
        targets = _resolve_apply_target_nodes(target_mode, target_nodes_csv)
        payload["targets"] = targets

        preflight = _action_update_test(
            clone_name=UPDATE_TEST_NODE_DEFAULT,
            source_branch=source_branch,
            deprecate_plugins=deprecate_plugins,
        )
        payload["preflight"] = {
            "ok": bool(preflight.get("ok")),
            "run_id": preflight.get("run_id"),
            "report_path": preflight.get("report_path"),
            "plugin_matrix_path": preflight.get("plugin_matrix_path"),
            "run_dir": preflight.get("run_dir"),
            "clone_name": preflight.get("clone_name"),
        }

        preflight_matrix_path = Path(str(preflight.get("plugin_matrix_path") or ""))
        if preflight_matrix_path.exists():
            shutil.copy2(preflight_matrix_path, plugin_matrix_path)
            payload["plugin_matrix_path"] = str(plugin_matrix_path)

        backup = _action_backup(clone_name=None, backup_all=True)
        payload["backup"] = {
            "ok": bool(backup.get("ok")),
            "archive": backup.get("archive"),
            "scope": backup.get("scope"),
            "nodes": backup.get("nodes"),
        }

        payload["promote_source"] = _promote_dummy_source_to_runtime()
        payload["runtime_deprecations"] = _deprecate_plugins(
            public_plugins_root=SHARED_PLUGINS_ROOT,
            plugin_names=deprecate_plugins,
        )
        payload["deprecated_plugins_applied"] = list(
            payload["runtime_deprecations"].get("deprecated_plugins_applied") or []
        )
        payload["deprecated_plugins_already_present"] = list(
            payload["runtime_deprecations"].get("deprecated_plugins_already_present") or []
        )
        payload["deprecated_plugins_missing"] = list(
            payload["runtime_deprecations"].get("deprecated_plugins_missing") or []
        )

        for idx, node_name in enumerate(targets):
            node_payload: Dict[str, Any] = {"node": node_name, "status": "pending"}
            try:
                update_payload = _action_update_node(
                    node_name,
                    source_branch=source_branch,
                    refresh_template=False,
                )
                restart_payload = _action_restart_node_for_rollout(node_name)
                node_payload["update"] = update_payload
                node_payload["restart"] = restart_payload
                node_payload["status"] = "updated"
                updated_nodes.append(node_name)
                rollout_results.append(node_payload)
            except Exception as exc:
                node_payload["status"] = "failed"
                node_payload["error"] = str(exc)
                rollout_results.append(node_payload)
                pending_nodes = targets[idx + 1 :]
                raise CloneManagerError(
                    f"update apply failed on node '{node_name}' (fail-fast): {exc}"
                ) from exc

        payload["rollout"] = rollout_results
        payload["updated_nodes"] = updated_nodes
        payload["pending_nodes"] = pending_nodes
        payload["ok"] = True
        payload["result"] = True
        payload["message"] = "update apply completed"
    except Exception as exc:
        error_message = str(exc) or "unexpected update-apply failure"
        payload["ok"] = False
        payload["result"] = False
        payload["error"] = error_message
        payload["rollout"] = rollout_results
        if targets:
            payload["updated_nodes"] = updated_nodes
            if not pending_nodes:
                pending_nodes = [node for node in targets if node not in updated_nodes]
            payload["pending_nodes"] = pending_nodes

    _atomic_write_json(report_path, payload)
    if error_message:
        raise CloneManagerError(f"update apply failed; see {report_path} ({error_message})")
    return payload


def _action_update_node(
    clone_name: str,
    source_branch: str,
    *,
    refresh_template: bool = True,
) -> Dict[str, Any]:
    env_path = _clone_env_path(clone_name)
    clone_root = _clone_root_path(clone_name)
    if not env_path.exists():
        raise CloneManagerError(f"clone env not found: {env_path}")
    if not clone_root.exists():
        raise CloneManagerError(f"clone root not found: {clone_root}")

    env = _read_env_file(env_path)
    state_code = _extract_state_mode(env)
    template_payload: Dict[str, Any]
    if refresh_template:
        template_payload = _action_update_template(source_branch)
    else:
        template_payload = {
            "ok": True,
            "action": "update",
            "target": "template",
            "skipped": True,
            "reason": "template refresh skipped by caller",
            "source_root": str(HERMES_SOURCE_ROOT),
        }

    if state_code == 1:
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
            _orchestrator_start_gateway(
                clone_name,
                clone_root,
                env_path,
                runtime_env_overrides=_runtime_env_overrides(clone_name, env),
            )

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
                "agents/nodes/orchestrator/hermes-agent; /local/hermes-agent stays template-only."
            ),
        }

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
    backup_all: bool,
    restore_path: str,
    logs_clean: bool,
    target_mode: str,
    target_nodes_csv: str,
    deprecate_plugins_raw: str,
) -> Dict[str, Any]:
    deprecate_plugins = _parse_deprecate_plugins(deprecate_plugins_raw)
    if action == "update-test":
        return _action_update_test(
            clone_name,
            source_branch=source_branch,
            deprecate_plugins=deprecate_plugins,
        )
    if action == "update-apply":
        return _action_update_apply(
            target_mode=target_mode,
            target_nodes_csv=target_nodes_csv,
            source_branch=source_branch,
            deprecate_plugins=deprecate_plugins,
        )
    if action in {"update", "test-update"}:
        raise CloneManagerError(
            "legacy update action rejected. Use 'horc update test' or "
            "'horc update apply all|node <csv>'"
        )
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
        if logs_clean:
            return _action_logs_clean(clone_name, clean_all=backup_all or not clone_name)
        if not clone_name:
            raise CloneManagerError("logs requires clone name")
        return _action_logs(clone_name, lines=lines)
    if action == "backup":
        return _action_backup(clone_name, backup_all=backup_all)
    if action == "restore":
        return _action_restore(restore_path)
    raise CloneManagerError(f"unsupported action: {action}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes clone lifecycle manager")
    parser.add_argument(
        "action",
        choices=[
            "start",
            "status",
            "stop",
            "delete",
            "logs",
            "backup",
            "restore",
            "update-test",
            "update-apply",
            "update",
            "test-update",
        ],
    )
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
        "--clean",
        dest="logs_clean",
        action="store_true",
        help="Clean/truncate canonical logs (logs action)",
    )
    parser.add_argument(
        "--all",
        dest="backup_all",
        action="store_true",
        help="Apply to all nodes (backup action, or logs with --clean)",
    )
    parser.add_argument("--path", dest="restore_path", default=None, help="Backup file path for restore action")
    parser.add_argument(
        "--source-branch",
        default=str(os.getenv("HERMES_AGENT_UPDATE_BRANCH", HERMES_AGENT_UPSTREAM_BRANCH) or HERMES_AGENT_UPSTREAM_BRANCH),
        help="Source git branch used by update test/apply when syncing hermes-agent",
    )
    parser.add_argument(
        "--target-mode",
        default="",
        help="Update apply target mode: all or node",
    )
    parser.add_argument(
        "--target-nodes",
        default="",
        help="Comma-separated node names for update apply --target-mode node",
    )
    parser.add_argument(
        "--deprecate-plugins",
        default="",
        help="Comma-separated plugin names to move under plugins/public/deprecated/",
    )
    return parser


def main() -> int:
    _load_optional_env_file(HOST_BOOTSTRAP_ENV_FILE)
    _ensure_dirs()
    parser = _build_parser()
    args = parser.parse_args()

    try:
        clone_name: str | None
        restore_path = ""
        if args.action == "restore":
            raw_restore = args.restore_path or args.name_positional
            restore_path = str(raw_restore or "").strip()
            if not restore_path:
                raise CloneManagerError("restore requires backup path (use positional path or --path)")
            clone_name = None
        elif args.action == "logs" and bool(args.logs_clean):
            raw_name = args.name_flag or args.name_positional
            if raw_name and str(raw_name).strip().lower() not in {"all", "*"}:
                clone_name = _normalize_clone_name(raw_name)
            else:
                clone_name = None
        elif args.action == "update-test":
            raw_name = (
                args.name_flag
                or args.name_positional
                or str(os.getenv("HERMES_UPDATE_TEST_NODE", UPDATE_TEST_NODE_DEFAULT) or UPDATE_TEST_NODE_DEFAULT)
            )
            clone_name = _normalize_clone_name(raw_name)
        elif args.action in {"backup"}:
            raw_name = args.name_flag or args.name_positional
            clone_name = _normalize_clone_name(raw_name) if raw_name else None
            if args.action == "backup" and args.backup_all:
                clone_name = None
        elif args.action == "update-apply":
            clone_name = None
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
            backup_all=bool(args.backup_all),
            restore_path=restore_path,
            logs_clean=bool(args.logs_clean),
            target_mode=str(args.target_mode or ""),
            target_nodes_csv=str(args.target_nodes or ""),
            deprecate_plugins_raw=str(args.deprecate_plugins or ""),
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
