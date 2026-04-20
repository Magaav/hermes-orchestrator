from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


@dataclass(frozen=True)
class GuardSettings:
    repo_root: Path
    clone_manager_script: Path
    python_bin: str
    agents_root: Path
    logs_root: Path
    node_logs_root: Path
    attention_logs_root: Path
    node_activity_root: Path
    guard_logs_root: Path
    poll_interval_sec: float
    restart_cooldown_sec: float
    retry_ceiling: int
    stall_timeout_sec: float
    attention_warn_threshold: int
    discord_webhook_url: str


def load_settings() -> GuardSettings:
    repo_root = Path(__file__).resolve().parents[4]
    logs_root = Path(str(os.getenv("HERMES_LOGS_ROOT", "/local/logs"))).resolve()
    agents_root = Path(str(os.getenv("HERMES_AGENTS_ROOT", "/local/agents"))).resolve()

    return GuardSettings(
        repo_root=repo_root,
        clone_manager_script=Path(
            str(
                os.getenv(
                    "HERMES_GUARD_CLONE_MANAGER_SCRIPT",
                    str(repo_root / "scripts" / "public" / "clone" / "clone_manager.py"),
                )
            )
        ).resolve(),
        python_bin=str(os.getenv("HERMES_GUARD_PYTHON_BIN", os.getenv("PYTHON", "python3")) or "python3").strip() or "python3",
        agents_root=agents_root,
        logs_root=logs_root,
        node_logs_root=Path(str(os.getenv("HERMES_AGENTS_NODE_LOG_ROOT", str(logs_root / "nodes")))).resolve(),
        attention_logs_root=Path(
            str(
                os.getenv(
                    "HERMES_AGENTS_ATTENTION_LOG_ROOT",
                    str(logs_root / "attention" / "nodes"),
                )
            )
        ).resolve(),
        node_activity_root=Path(
            str(
                os.getenv(
                    "HERMES_AGENTS_ACTIVITY_LOG_ROOT",
                    str(logs_root / "nodes" / "activities"),
                )
            )
        ).resolve(),
        guard_logs_root=Path(
            str(
                os.getenv(
                    "HERMES_GUARD_LOG_ROOT",
                    str(logs_root / "guard"),
                )
            )
        ).resolve(),
        poll_interval_sec=max(5.0, _env_float("HERMES_GUARD_POLL_INTERVAL_SEC", 30.0)),
        restart_cooldown_sec=max(5.0, _env_float("HERMES_GUARD_RESTART_COOLDOWN_SEC", 300.0)),
        retry_ceiling=max(1, _env_int("HERMES_GUARD_RETRY_CEILING", 3)),
        stall_timeout_sec=max(30.0, _env_float("HERMES_GUARD_STALL_TIMEOUT_SEC", 900.0)),
        attention_warn_threshold=max(1, _env_int("HERMES_GUARD_ATTENTION_WARN_THRESHOLD", 5)),
        discord_webhook_url=str(os.getenv("HERMES_GUARD_DISCORD_WEBHOOK_URL", "") or "").strip(),
    )
