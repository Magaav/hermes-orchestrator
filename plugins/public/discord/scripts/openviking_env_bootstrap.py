#!/usr/bin/env python3
"""Bootstrap OpenViking defaults from profile .env flags.

Goal:
- Treat OPENVIKING_ENABLED=1 as an intent flag (legacy MEMORY_OPENVIKING supported).
- If enabled, normalize OPENVIKING_* env defaults.
- Enforce memory.provider=openviking in config.yaml (when supported).
- Keep startup fail-open when endpoint is unavailable.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml


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


def _infer_config_file(env_file: Path) -> Path:
    # /x/.hermes/.env -> /x/.hermes/config.yaml
    if env_file.name == ".env" and env_file.parent.name == ".hermes":
        return env_file.parent / "config.yaml"

    # /local/agents/<name>.env -> /local/agents/<name>/.hermes/config.yaml
    if env_file.suffix == ".env":
        clone_name = env_file.stem
        return env_file.parent / clone_name / ".hermes" / "config.yaml"

    return env_file.parent / "config.yaml"


def _infer_agent_root(config_file: Path) -> Path:
    # /x/.hermes/config.yaml -> /x/hermes-agent
    if config_file.parent.name == ".hermes":
        return config_file.parent.parent / "hermes-agent"
    return config_file.parent / "hermes-agent"


def _probe_health(base_url: str, timeout_sec: float) -> Tuple[bool, str]:
    health_url = f"{str(base_url).rstrip('/')}/health"
    try:
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=max(0.5, timeout_sec)) as resp:  # nosec B310
            status = int(getattr(resp, "status", 0) or 0)
            if 200 <= status < 300:
                return True, f"healthy ({status})"
            return False, f"unexpected HTTP status {status}"
    except Exception as exc:
        return False, str(exc)


def _load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        return {}
    return data


def _save_config(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")
    try:
        path.chmod(0o600)
    except Exception:
        pass


def _provider_supported(agent_root: Path) -> Tuple[bool, str]:
    provider_init = agent_root / "plugins" / "memory" / "openviking" / "__init__.py"
    if provider_init.exists():
        return True, "ok"
    return False, (
        f"openviking provider plugin missing in {agent_root}. "
        "Older node code detected; run 'horc agent update <node>' and start again."
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap OpenViking from OPENVIKING_ENABLED in .env")
    parser.add_argument("--env-file", required=True, help="Path to profile env file")
    parser.add_argument("--config-file", default="", help="Optional explicit config.yaml path")
    parser.add_argument("--agent-root", default="", help="Optional explicit hermes-agent root for compatibility check")
    parser.add_argument("--enable-var", default="OPENVIKING_ENABLED", help="Boolean enable env var key")
    parser.add_argument("--provider", default="openviking", help="Memory provider name to enforce")
    parser.add_argument("--default-endpoint", default="http://127.0.0.1:1933", help="Default OPENVIKING_ENDPOINT")
    parser.add_argument("--default-account", default="colmeio", help="Default OPENVIKING_ACCOUNT")
    parser.add_argument("--default-user", default="colmeio", help="Default OPENVIKING_USER")
    parser.add_argument(
        "--persist-env",
        action="store_true",
        help="Persist computed OPENVIKING_* defaults into env file (disabled by default)",
    )
    parser.add_argument("--health-timeout-sec", type=float, default=2.0, help="Health probe timeout")
    parser.add_argument("--strict-health", action="store_true", help="Fail when endpoint health probe fails")
    parser.add_argument("--skip-health-probe", action="store_true", help="Skip endpoint reachability probe")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    env_file = Path(str(args.env_file)).expanduser()
    if not env_file.exists():
        print(json.dumps({"ok": False, "error": f"env file not found: {env_file}"}))
        return 1

    config_file = Path(str(args.config_file)).expanduser() if str(args.config_file).strip() else _infer_config_file(env_file)
    agent_root = Path(str(args.agent_root)).expanduser() if str(args.agent_root).strip() else _infer_agent_root(config_file)

    env = _read_env(env_file)
    enable_raw = str(env.get(args.enable_var, "") or "").strip()
    legacy_enable_raw = str(env.get("MEMORY_OPENVIKING", "") or "").strip()
    enabled = _is_truthy(enable_raw) if enable_raw else _is_truthy(legacy_enable_raw)
    enable_source = str(args.enable_var) if enable_raw else ("MEMORY_OPENVIKING" if legacy_enable_raw else str(args.enable_var))

    endpoint = str(env.get("OPENVIKING_ENDPOINT", "") or "").strip() or str(args.default_endpoint)
    account = str(env.get("OPENVIKING_ACCOUNT", "") or "").strip()
    user = str(env.get("OPENVIKING_USER", "") or "").strip()
    default_account = str(args.default_account or "").strip()
    default_user = str(args.default_user or "").strip()
    if not account and not user:
        account = default_account or "default"
        user = default_user or account
    elif account and not user:
        user = account
    elif user and not account:
        account = user

    payload: Dict[str, Any] = {
        "ok": True,
        "env_file": str(env_file),
        "config_file": str(config_file),
        "agent_root": str(agent_root),
        "enabled": enabled,
        "enable_var": str(args.enable_var),
        "enable_source": enable_source,
        "provider": str(args.provider),
        "changed": False,
        "env_changed": False,
        "provider_changed": False,
        "effective": {
            "endpoint": endpoint,
            "account": account,
            "user": user,
        },
        "compatibility": {"supported": True, "message": "ok"},
        "health": {"attempted": False, "reachable": False, "message": "not checked"},
        "degraded": False,
    }

    if not enabled:
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    env_changed = False
    if args.persist_env:
        if not str(env.get("OPENVIKING_ENDPOINT", "") or "").strip():
            env_changed = _upsert_env_value(env_file, "OPENVIKING_ENDPOINT", endpoint) or env_changed
        if not str(env.get("OPENVIKING_ACCOUNT", "") or "").strip():
            env_changed = _upsert_env_value(env_file, "OPENVIKING_ACCOUNT", account) or env_changed
        if not str(env.get("OPENVIKING_USER", "") or "").strip():
            env_changed = _upsert_env_value(env_file, "OPENVIKING_USER", user) or env_changed

        env = _read_env(env_file)
        endpoint = str(env.get("OPENVIKING_ENDPOINT", "") or "").strip() or endpoint
        account = str(env.get("OPENVIKING_ACCOUNT", "") or "").strip() or account
        user = str(env.get("OPENVIKING_USER", "") or "").strip() or user

    payload["env_changed"] = env_changed
    payload["effective"] = {
        "endpoint": endpoint,
        "account": account,
        "user": user,
    }

    supported, support_message = _provider_supported(agent_root)
    payload["compatibility"] = {"supported": supported, "message": support_message}

    provider_changed = False
    if supported:
        cfg = _load_config(config_file)
        prev_provider = ""
        memory_cfg = cfg.get("memory")
        if not isinstance(memory_cfg, dict):
            memory_cfg = {}
        prev_provider = str(memory_cfg.get("provider", "") or "")
        if prev_provider != str(args.provider):
            memory_cfg["provider"] = str(args.provider)
            cfg["memory"] = memory_cfg
            _save_config(config_file, cfg)
            provider_changed = True
        payload["provider_previous"] = prev_provider
        payload["provider_current"] = str(args.provider)
    else:
        payload["provider_previous"] = None
        payload["provider_current"] = None
        payload["degraded"] = True

    if endpoint and not args.skip_health_probe:
        reachable, msg = _probe_health(endpoint, timeout_sec=float(args.health_timeout_sec))
        payload["health"] = {"attempted": True, "reachable": reachable, "message": msg}
        if not reachable:
            payload["degraded"] = True
            if args.strict_health:
                payload["ok"] = False
    elif endpoint and args.skip_health_probe:
        payload["health"] = {"attempted": False, "reachable": False, "message": "skipped"}

    payload["provider_changed"] = provider_changed
    payload["changed"] = bool(env_changed or provider_changed)

    rc = 0 if payload.get("ok") else 1
    print(json.dumps(payload, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
