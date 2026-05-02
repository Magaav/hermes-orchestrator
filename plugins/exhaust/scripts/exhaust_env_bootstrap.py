#!/usr/bin/env python3
"""Sync and enable the exhaust Hermes project plugin from a node env file.

This script is intentionally optional and self-contained. It lets an existing
orchestrator prestart pipeline derive Hermes project-plugin state from:

    PLUGINS_EXHAUST=true

It does not patch Hermes core.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict

import yaml


PLUGIN_NAME = "exhaust"
ENABLE_ENV = "PLUGINS_EXHAUST"
VALID_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DEFAULT_PLUGIN_SOURCE = Path(__file__).resolve().parents[1]


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


def _infer_config_file(env_file: Path) -> Path:
    if env_file.name == ".env" and env_file.parent.name == ".hermes":
        return env_file.parent / "config.yaml"
    if env_file.suffix == ".env":
        return Path("/local/agents/nodes") / env_file.stem / ".hermes" / "config.yaml"
    return env_file.parent / "config.yaml"


def _load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def _save_config(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _remove_from_list(values: list[str], target: str) -> bool:
    before = list(values)
    values[:] = [value for value in values if value != target]
    return before != values


def _ensure_in_list(values: list[str], target: str) -> bool:
    if target in values:
        return False
    values.append(target)
    return True


def _sync_tree(src: Path, dst: Path) -> bool:
    changed = False
    if not src.exists():
        raise FileNotFoundError(f"plugin source not found: {src}")
    if not dst.exists():
        dst.mkdir(parents=True, exist_ok=True)
        changed = True
    src_entries = {child.name: child for child in src.iterdir()}
    dst_entries = {child.name: child for child in dst.iterdir()} if dst.exists() else {}
    for name, dst_child in dst_entries.items():
        if name not in src_entries:
            if dst_child.is_dir() and not dst_child.is_symlink():
                shutil.rmtree(dst_child)
            else:
                dst_child.unlink()
            changed = True
    for name, src_child in src_entries.items():
        dst_child = dst / name
        if src_child.is_dir():
            if dst_child.exists() and not dst_child.is_dir():
                dst_child.unlink()
                changed = True
            changed = _sync_tree(src_child, dst_child) or changed
            continue
        if dst_child.exists() and dst_child.is_dir():
            shutil.rmtree(dst_child)
            changed = True
        if (not dst_child.exists()) or (not filecmp.cmp(src_child, dst_child, shallow=False)):
            shutil.copy2(src_child, dst_child)
            changed = True
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap the exhaust plugin into a Hermes node runtime.")
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--config-file", default="")
    parser.add_argument("--plugin-source", default=str(DEFAULT_PLUGIN_SOURCE))
    parser.add_argument("--plugin-name", default=PLUGIN_NAME)
    args = parser.parse_args()

    env_file = Path(args.env_file).expanduser()
    config_file = Path(args.config_file).expanduser() if args.config_file.strip() else _infer_config_file(env_file)
    plugin_source = Path(args.plugin_source).expanduser()
    plugin_name = str(args.plugin_name).strip() or PLUGIN_NAME

    env = _read_env(env_file)
    enabled = _is_truthy(env.get(ENABLE_ENV, ""))
    config = _load_config(config_file)
    plugins_cfg = config.setdefault("plugins", {})
    enabled_list = plugins_cfg.setdefault("enabled", [])
    disabled_list = plugins_cfg.setdefault("disabled", [])
    if not isinstance(enabled_list, list):
        enabled_list = []
        plugins_cfg["enabled"] = enabled_list
    if not isinstance(disabled_list, list):
        disabled_list = []
        plugins_cfg["disabled"] = disabled_list

    plugin_target = config_file.parent / "plugins" / plugin_name
    changed = False
    synced = False

    if enabled:
        changed = _upsert_env_value(env_file, "HERMES_ENABLE_PROJECT_PLUGINS", "true") or changed
        synced = _sync_tree(plugin_source, plugin_target)
        changed = synced or changed
        changed = _ensure_in_list(enabled_list, plugin_name) or changed
        changed = _remove_from_list(disabled_list, plugin_name) or changed
        _save_config(config_file, config)
    else:
        changed = _remove_from_list(enabled_list, plugin_name) or changed
        if changed:
            _save_config(config_file, config)

    print(
        json.dumps(
            {
                "ok": True,
                "enabled": enabled,
                "changed": changed,
                "plugin_synced": synced,
                "plugin_target": str(plugin_target),
                "config_file": str(config_file),
                "env_file": str(env_file),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
