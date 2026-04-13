from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


_TRUE_VALUES = {"1", "true", "yes", "on"}


def env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in _TRUE_VALUES


@dataclass(frozen=True)
class GatewaySettings:
    host: str
    port: int
    repo_root: Path
    clone_manager_script: Path
    python_bin: str
    agents_root: Path
    logs_root: Path
    node_logs_root: Path
    attention_logs_root: Path
    ui_root: Path
    api_token: str
    experimental: bool
    poll_interval_sec: float
    max_tail_lines: int
    read_limit_per_minute: int
    write_limit_per_minute: int


def _default_python_bin() -> str:
    explicit = str(os.getenv("WASM_UI_PYTHON_BIN", "") or "").strip()
    if explicit:
        return explicit
    return os.getenv("PYTHON", "python3")


def load_settings() -> GatewaySettings:
    repo_root = Path(__file__).resolve().parents[3]
    logs_root = Path(str(os.getenv("HERMES_LOGS_ROOT", "/local/logs"))).resolve()
    agents_root = Path(str(os.getenv("HERMES_AGENTS_ROOT", "/local/agents"))).resolve()
    ui_root = Path(str(os.getenv("WASM_UI_ROOT", str(repo_root / "apps" / "wasm-ui")))).resolve()

    clone_manager_script = Path(
        str(
            os.getenv(
                "WASM_UI_CLONE_MANAGER_SCRIPT",
                str(repo_root / "scripts" / "clone" / "clone_manager.py"),
            )
        )
    ).resolve()

    host = str(os.getenv("WASM_UI_HOST", "127.0.0.1") or "127.0.0.1").strip() or "127.0.0.1"
    port = int(str(os.getenv("WASM_UI_PORT", "8787") or "8787"))

    return GatewaySettings(
        host=host,
        port=port,
        repo_root=repo_root,
        clone_manager_script=clone_manager_script,
        python_bin=_default_python_bin(),
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
        ui_root=ui_root,
        api_token=str(os.getenv("WASM_UI_API_TOKEN", "") or "").strip(),
        experimental=env_bool("WASM_UI_EXPERIMENTAL", default=False),
        poll_interval_sec=float(str(os.getenv("WASM_UI_POLL_INTERVAL_SEC", "2.0") or "2.0")),
        max_tail_lines=max(20, min(5000, int(str(os.getenv("WASM_UI_MAX_TAIL_LINES", "1500") or "1500")))),
        read_limit_per_minute=max(10, int(str(os.getenv("WASM_UI_READ_LIMIT_PER_MINUTE", "180") or "180"))),
        write_limit_per_minute=max(3, int(str(os.getenv("WASM_UI_WRITE_LIMIT_PER_MINUTE", "45") or "45"))),
    )
