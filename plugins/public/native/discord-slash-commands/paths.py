"""Path helpers for the native Discord slash commands plugin."""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
from pathlib import Path


def resolve_private_discord_root() -> Path:
    configured = str(os.getenv("HERMES_DISCORD_PRIVATE_DIR", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path("/local/plugins/private/discord")


def resolve_discord_commands_file() -> Path:
    configured = str(os.getenv("DISCORD_COMMANDS_FILE", "") or "").strip()
    if configured:
        return Path(configured).expanduser()

    node_name = str(os.getenv("NODE_NAME", "") or "").strip()
    if node_name:
        return resolve_private_discord_root() / "commands" / f"{node_name}.json"

    return resolve_private_discord_root() / "commands" / "colmeio.json"


def resolve_legacy_bridge_handlers_path() -> Path:
    return Path("/local/plugins/public/discord/hooks/discord_slash_bridge/handlers.py")


def resolve_metrics_script_path() -> Path:
    candidates = [
        Path("/local/skills/custom/colmeio/colmeio-metrics/scripts/metrics_logger.py"),
        Path("/local/hermes-agent") / ".hermes" / "skills" / "custom" / "colmeio" / "colmeio-metrics" / "scripts" / "metrics_logger.py",
        Path.home() / ".hermes" / "skills" / "custom" / "colmeio" / "colmeio-metrics" / "scripts" / "metrics_logger.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolve_faltas_pipeline_script() -> Path:
    candidates = [
        Path("/local/skills/custom/colmeio/colmeio-lista-de-faltas/scripts/faltas_pipeline.py"),
        Path("/local/hermes-agent") / ".hermes" / "skills" / "custom" / "colmeio" / "colmeio-lista-de-faltas" / "scripts" / "faltas_pipeline.py",
        Path.home() / ".hermes" / "skills" / "custom" / "colmeio" / "colmeio-lista-de-faltas" / "scripts" / "faltas_pipeline.py",
        Path("/local/agents/nodes/colmeio/.hermes/skills/custom/colmeio/colmeio-lista-de-faltas/scripts/faltas_pipeline.py"),
        Path("/opt/data/skills/custom/colmeio/colmeio-lista-de-faltas/scripts/faltas_pipeline.py"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


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
