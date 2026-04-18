#!/usr/bin/env python3
"""Validate Discord ACL contract files before startup/update."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

import yaml


def _runtime_node_name(raw: str | None = None) -> str:
    text = str(raw or os.getenv("NODE_NAME", "") or "").strip().lower()
    if text.endswith(".json"):
        text = text[:-5]
    return text or "orchestrator"


def _private_root(raw: str | None = None) -> Path:
    configured = str(raw or os.getenv("HERMES_DISCORD_PRIVATE_DIR", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path("/local/plugins/private/discord")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_yaml(path: Path) -> Dict[str, Any]:
    parsed = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_models(raw: Any) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}

    entries: list[Dict[str, Any]] = []
    if isinstance(raw, dict):
        models = raw.get("models")
        if isinstance(models, dict):
            for key, value in models.items():
                if isinstance(value, dict):
                    item = dict(value)
                    item.setdefault("key", str(key))
                    entries.append(item)
        elif isinstance(models, list):
            entries.extend(item for item in models if isinstance(item, dict))
    elif isinstance(raw, list):
        entries.extend(item for item in raw if isinstance(item, dict))

    for item in entries:
        key = str(item.get("key") or "").strip()
        provider = str(item.get("provider") or "").strip()
        model = str(item.get("model") or "").strip()
        if not key or not provider or not model:
            continue
        out[key] = {
            "key": key,
            "provider": provider,
            "model": model,
        }
    return out


def check_contract(*, private_root: Path, node_name: str) -> Dict[str, Any]:
    role_acl_path = private_root / "acl" / f"{node_name}_acl.json"
    channel_cfg_path = private_root / "hooks" / "channel_acl" / "config.yaml"
    models_path = private_root / "models" / f"{node_name}_models.json"

    errors: list[str] = []

    role_acl: Dict[str, Any] = {}
    if not role_acl_path.exists():
        errors.append(f"missing role ACL file: {role_acl_path}")
    else:
        try:
            payload = _load_json(role_acl_path)
            role_acl = payload if isinstance(payload, dict) else {}
            commands = role_acl.get("commands")
            if not isinstance(commands, dict):
                errors.append(f"role ACL invalid commands map: {role_acl_path}")
            policy = role_acl.get("policy") if isinstance(role_acl.get("policy"), dict) else {}
            if str(policy.get("unmapped_command") or "").strip().lower() != "deny":
                errors.append(f"role ACL must enforce policy.unmapped_command=deny: {role_acl_path}")
        except Exception as exc:
            errors.append(f"invalid role ACL JSON {role_acl_path}: {exc}")

    channel_cfg: Dict[str, Any] = {}
    if not channel_cfg_path.exists():
        errors.append(f"missing channel ACL config: {channel_cfg_path}")
    else:
        try:
            channel_cfg = _load_yaml(channel_cfg_path)
            channels = channel_cfg.get("channels")
            if not isinstance(channels, dict):
                errors.append(f"channel ACL missing channels map: {channel_cfg_path}")
        except Exception as exc:
            errors.append(f"invalid channel ACL YAML {channel_cfg_path}: {exc}")

    models: Dict[str, Dict[str, str]] = {}
    if not models_path.exists():
        errors.append(f"missing private models file: {models_path}")
    else:
        try:
            models_raw = _load_json(models_path)
            models = _normalize_models(models_raw)
            if not models:
                errors.append(f"private models file has no valid entries: {models_path}")
        except Exception as exc:
            errors.append(f"invalid private models JSON {models_path}: {exc}")

    channels = channel_cfg.get("channels") if isinstance(channel_cfg.get("channels"), dict) else {}
    for channel_id, entry in channels.items():
        if not isinstance(entry, dict):
            continue
        mode = str(entry.get("mode") or "livre").strip().lower()
        if mode not in {"condicionado", "specific"}:
            continue
        model_key = str(entry.get("model_key") or "").strip()
        if not model_key:
            errors.append(
                f"channel {channel_id} is condicionado but missing model_key in {channel_cfg_path}"
            )
            continue
        if model_key not in models:
            errors.append(
                f"channel {channel_id} references unknown model_key `{model_key}` not found in {models_path}"
            )

    return {
        "ok": not errors,
        "node": node_name,
        "private_root": str(private_root),
        "role_acl_path": str(role_acl_path),
        "channel_acl_path": str(channel_cfg_path),
        "models_path": str(models_path),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Discord ACL contract files")
    parser.add_argument("--private-root", default="", help="Discord private root (default from env)")
    parser.add_argument("--node-name", default="", help="Node name (default from NODE_NAME)")
    args = parser.parse_args()

    payload = check_contract(
        private_root=_private_root(args.private_root),
        node_name=_runtime_node_name(args.node_name),
    )
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
