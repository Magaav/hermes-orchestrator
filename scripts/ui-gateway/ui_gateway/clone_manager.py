from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .settings import GatewaySettings


VALID_NODE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
ALLOWED_ACTIONS = {"start", "stop", "restart"}


class CloneManagerError(RuntimeError):
    """Raised when clone_manager interaction fails."""


class CloneManagerClient:
    def __init__(
        self,
        *,
        script_path: Path,
        python_bin: str,
        timeout_sec: float = 90.0,
    ) -> None:
        self.script_path = script_path
        self.python_bin = python_bin
        self.timeout_sec = timeout_sec

    def _run(self, args: list[str]) -> dict[str, Any]:
        cmd = [self.python_bin, str(self.script_path), *args]
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=self.timeout_sec,
            check=False,
        )

        payload: dict[str, Any]
        raw = (proc.stdout or "").strip()
        if raw:
            try:
                parsed = json.loads(raw)
                payload = parsed if isinstance(parsed, dict) else {"ok": False, "error": "invalid_payload"}
            except Exception:
                payload = {"ok": False, "error": f"non_json_stdout: {raw[:500]}"}
        else:
            payload = {"ok": False, "error": "empty_stdout"}

        if proc.returncode != 0 or not bool(payload.get("ok")):
            stderr = (proc.stderr or "").strip()
            err = str(payload.get("error") or stderr or f"clone_manager_failed({proc.returncode})")
            raise CloneManagerError(err)

        return payload

    def status(self, node: str) -> dict[str, Any]:
        return self._run(["status", "--name", node])

    def logs(self, node: str, *, lines: int) -> dict[str, Any]:
        safe_lines = max(10, min(int(lines), 5000))
        return self._run(["logs", "--name", node, "--lines", str(safe_lines)])

    def start(self, node: str) -> dict[str, Any]:
        return self._run(["start", "--name", node])

    def stop(self, node: str) -> dict[str, Any]:
        return self._run(["stop", "--name", node])



def validate_node_name(node: str) -> str:
    normalized = str(node or "").strip().lower()
    if not VALID_NODE_RE.fullmatch(normalized):
        raise CloneManagerError(f"invalid node name: {node!r}")
    return normalized



def validate_action(action: str) -> str:
    normalized = str(action or "").strip().lower()
    if normalized not in ALLOWED_ACTIONS:
        raise CloneManagerError(
            f"unsupported action '{action}'. Allowed actions: {', '.join(sorted(ALLOWED_ACTIONS))}"
        )
    return normalized



def discover_nodes(settings: GatewaySettings) -> list[str]:
    names: set[str] = set()

    registry_path = settings.agents_root / "registry.json"
    if registry_path.exists() and registry_path.is_file():
        try:
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
            clones = payload.get("clones") if isinstance(payload, dict) else None
            if isinstance(clones, dict):
                for key, value in clones.items():
                    if isinstance(key, str):
                        names.add(key)
                    if isinstance(value, dict):
                        clone_name = value.get("clone_name")
                        if isinstance(clone_name, str):
                            names.add(clone_name)
        except Exception:
            pass

    env_root = settings.agents_root / "envs"
    if env_root.exists():
        for path in env_root.glob("*.env"):
            names.add(path.stem)

    nodes_root = settings.agents_root / "nodes"
    if nodes_root.exists():
        for path in nodes_root.iterdir():
            if path.is_dir():
                names.add(path.name)

    normalized: list[str] = []
    for name in sorted(names):
        try:
            normalized.append(validate_node_name(name))
        except CloneManagerError:
            continue

    # Keep orchestrator first for UI readability.
    if "orchestrator" in normalized:
        normalized.remove("orchestrator")
        normalized.insert(0, "orchestrator")
    return normalized
