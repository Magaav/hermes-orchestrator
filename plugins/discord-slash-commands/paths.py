"""Path helpers for the canonical Discord slash commands plugin."""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
from pathlib import Path


def plugin_root() -> Path:
    return Path(__file__).resolve().parent


def runtime_node_name() -> str:
    raw = str(os.getenv("NODE_NAME", "") or "").strip().lower()
    if raw.endswith(".json"):
        raw = raw[:-5]
    return raw or "orchestrator"


def resolve_runtime_hermes_home() -> Path:
    configured = str(os.getenv("HERMES_HOME", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    local_hermes = Path("/local/.hermes")
    if local_hermes.exists() or Path("/local").exists():
        return local_hermes
    return Path.home() / ".hermes"


def resolve_runtime_cache_root() -> Path:
    configured = str(os.getenv("HERMES_DISCORD_SLASH_CACHE_ROOT", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    node_root = str(os.getenv("HERMES_NODE_ROOT", "") or "").strip()
    if node_root:
        return Path(node_root).expanduser() / "workspace" / "plugins" / "discord-slash-commands" / "cache"
    home = str(os.getenv("HOME", "") or "").strip()
    if home and Path(home).expanduser().name in {"orchestrator", runtime_node_name()}:
        return Path(home).expanduser() / "workspace" / "plugins" / "discord-slash-commands" / "cache"
    if Path("/local/.clone-meta/bootstrap.json").exists():
        return Path("/local/workspace/plugins/discord-slash-commands/cache")
    return resolve_runtime_hermes_home() / "discord-slash-commands" / "cache"


def resolve_custom_catalog_file() -> Path:
    configured = str(os.getenv("DISCORD_COMMANDS_FILE", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return resolve_runtime_cache_root() / "catalogs" / "custom_commands.json"


def resolve_discord_commands_file() -> Path:
    return resolve_custom_catalog_file()


def resolve_node_activation_file() -> Path:
    return resolve_runtime_cache_root() / "state" / "node_activation.json"


def resolve_app_scope_file() -> Path:
    return resolve_runtime_cache_root() / "state" / "app_scope.json"


def resolve_status_active_model_file() -> Path:
    return resolve_runtime_cache_root() / "status" / "active_model.json"


def resolve_migration_file() -> Path:
    return resolve_runtime_cache_root() / "migration.json"


def resolve_governance_root() -> Path:
    configured = str(os.getenv("HERMES_DISCORD_PRIVATE_DIR", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return resolve_runtime_cache_root() / "governance"


def resolve_governance_acl_file() -> Path:
    return resolve_governance_root() / "acl.json"


def resolve_governance_models_file() -> Path:
    return resolve_governance_root() / "models.json"


def resolve_governance_channel_acl_file() -> Path:
    return resolve_governance_root() / "channel_acl.yaml"


def resolve_governance_users_file() -> Path:
    return resolve_governance_root() / "discord_users.json"


def resolve_governance_compat_acl_file(node_name: str | None = None) -> Path:
    node = str(node_name or runtime_node_name()).strip().lower() or "orchestrator"
    return resolve_governance_root() / "acl" / f"{node}_acl.json"


def resolve_governance_compat_models_file(node_name: str | None = None) -> Path:
    node = str(node_name or runtime_node_name()).strip().lower() or "orchestrator"
    return resolve_governance_root() / "models" / f"{node}_models.json"


def resolve_governance_compat_channel_acl_file() -> Path:
    return resolve_governance_root() / "hooks" / "channel_acl" / "config.yaml"


def resolve_acl_path(node_name: str | None = None) -> Path:
    return resolve_governance_acl_file()


def resolve_models_path(node_name: str | None = None) -> Path:
    return resolve_governance_compat_models_file(node_name=node_name)


def resolve_legacy_bridge_handlers_path() -> Path:
    return Path("/local/plugins/public/discord/hooks/discord_slash_bridge/handlers.py")


def resolve_legacy_role_acl_path() -> Path:
    return Path("/local/plugins/public/discord/hooks/discord_slash_bridge/role_acl.py")


def resolve_legacy_slash_handlers_path() -> Path:
    return Path("/local/plugins/public/discord/hooks/discord_slash_bridge/handlers.py")


def resolve_legacy_channel_acl_path() -> Path:
    return plugin_root() / "channel_acl" / "handler.py"


def resolve_metrics_script_path() -> Path:
    candidates = [
        Path("/local/skills/custom/colmeio/colmeio-metrics/scripts/metrics_logger.py"),
        Path("/local/hermes-agent/.hermes/skills/custom/colmeio/colmeio-metrics/scripts/metrics_logger.py"),
        Path.home() / ".hermes/skills/custom/colmeio/colmeio-metrics/scripts/metrics_logger.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolve_faltas_pipeline_script() -> Path:
    candidates = [
        Path("/local/skills/custom/colmeio/colmeio-lista-de-faltas/scripts/faltas_pipeline.py"),
        Path("/local/hermes-agent/.hermes/skills/custom/colmeio/colmeio-lista-de-faltas/scripts/faltas_pipeline.py"),
        Path.home() / ".hermes/skills/custom/colmeio/colmeio-lista-de-faltas/scripts/faltas_pipeline.py",
        Path("/local/agents/nodes/colmeio/.hermes/skills/custom/colmeio/colmeio-lista-de-faltas/scripts/faltas_pipeline.py"),
        Path("/opt/data/skills/custom/colmeio/colmeio-lista-de-faltas/scripts/faltas_pipeline.py"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolve_scientific_pipeline_script() -> Path:
    candidates = [
        Path("/local/skills/custom/scientific-paper-meta-analysis/scripts/pipeline.py"),
        Path("/local/hermes-agent/.hermes/skills/custom/scientific-paper-meta-analysis/scripts/pipeline.py"),
        Path.home() / ".hermes/skills/custom/scientific-paper-meta-analysis/scripts/pipeline.py",
        Path("/local/agents/nodes/paracelsus/.hermes/skills/custom/scientific-paper-meta-analysis/scripts/pipeline.py"),
        Path("/opt/data/skills/custom/scientific-paper-meta-analysis/scripts/pipeline.py"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolve_runtime_env_file() -> Path:
    return resolve_runtime_hermes_home() / ".env"


def resolve_register_script_path() -> Path:
    return plugin_root() / "scripts" / "register_guild_plugin_commands.py"


@functools.lru_cache(maxsize=None)
def _python_supports_modules(candidate: str, required_modules: tuple[str, ...]) -> bool:
    if not candidate or not Path(candidate).exists():
        return False
    if not required_modules:
        return True
    script = (
        "import importlib.util, sys; "
        "sys.exit(0 if all(importlib.util.find_spec(name) for name in sys.argv[1:]) else 1)"
    )
    try:
        proc = subprocess.run(
            [candidate, "-c", script, *required_modules],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    except Exception:
        return False
    return proc.returncode == 0


def resolve_python_bin(*, required_modules: tuple[str, ...] = ()) -> str:
    candidates = (
        "/local/hermes-agent/.venv/bin/python",
        "/local/hermes-agent/.venv/bin/python3",
        "/usr/bin/python3",
        shutil.which("python3"),
        shutil.which("python"),
    )
    for candidate in candidates:
        if candidate and _python_supports_modules(str(candidate), tuple(required_modules)):
            return str(candidate)
    return str(shutil.which("python3") or "python3")
