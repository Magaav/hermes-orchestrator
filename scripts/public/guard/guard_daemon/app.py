from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import request as urllib_request
import argparse
import json
import os
import re
import subprocess
import time

from .settings import GuardSettings, load_settings


GOOD_STATUSES = {"running", "healthy", "ok"}
TRANSITION_STATUSES = {"starting", "restarting"}
BAD_RUNNING_STATUSES = {"dead", "error", "exited", "failed", "paused", "unhealthy"}
VALID_NODE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


class GuardError(RuntimeError):
    """Raised when Guard cannot evaluate or remediate a node."""


class CloneManagerClient:
    def __init__(self, *, script_path: Path, python_bin: str, timeout_sec: float = 120.0) -> None:
        self.script_path = script_path
        self.python_bin = python_bin
        self.timeout_sec = timeout_sec

    def _run(self, args: list[str]) -> dict[str, Any]:
        proc = subprocess.run(
            [self.python_bin, str(self.script_path), *args],
            text=True,
            capture_output=True,
            timeout=self.timeout_sec,
            check=False,
        )

        raw = (proc.stdout or "").strip()
        if raw:
            try:
                payload = json.loads(raw)
            except Exception as exc:
                raise GuardError(f"clone_manager returned non-json stdout: {raw[:240]}") from exc
        else:
            payload = {"ok": False, "error": "empty_stdout"}

        if proc.returncode != 0 or not bool(payload.get("ok")):
            stderr = (proc.stderr or "").strip()
            raise GuardError(str(payload.get("error") or stderr or f"clone_manager_failed({proc.returncode})"))
        return payload if isinstance(payload, dict) else {"ok": False, "error": "invalid_payload"}

    def status(self, node: str) -> dict[str, Any]:
        return self._run(["status", "--name", node])

    def restart(self, node: str) -> dict[str, Any]:
        return {
            "stop": self._run(["stop", "--name", node]),
            "start": self._run(["start", "--name", node]),
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(ts: str) -> datetime | None:
    raw = str(ts or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _tail_lines(path: Path, lines: int) -> list[str]:
    if not path.exists() or not path.is_file():
        return []
    max_lines = max(1, int(lines))
    buffer: list[str] = []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            buffer.append(line.rstrip("\n"))
            if len(buffer) > max_lines:
                buffer = buffer[-max_lines:]
    return buffer


def _count_tail_lines(path: Path, lines: int) -> int:
    return len(_tail_lines(path, lines))


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists() or not path.is_file():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp.replace(path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _append_summary(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line if line.endswith("\n") else f"{line}\n")


def _discover_nodes(settings: GuardSettings) -> list[str]:
    names: set[str] = set()
    registry_path = settings.agents_root / "registry.json"
    registry = _read_json(registry_path, {})
    clones = registry.get("clones") if isinstance(registry, dict) else None
    if isinstance(clones, dict):
        for key, value in clones.items():
            if isinstance(key, str):
                names.add(key)
            if isinstance(value, dict):
                clone_name = value.get("clone_name")
                if isinstance(clone_name, str):
                    names.add(clone_name)

    env_root = settings.agents_root / "envs"
    if env_root.exists():
        for path in env_root.glob("*.env"):
            names.add(path.stem)

    nodes_root = settings.agents_root / "nodes"
    if nodes_root.exists():
        for path in nodes_root.iterdir():
            if path.is_dir():
                names.add(path.name)

    normalized = sorted(
        name.strip().lower()
        for name in names
        if isinstance(name, str) and VALID_NODE_RE.fullmatch(name.strip().lower())
    )
    if "orchestrator" in normalized:
        normalized.remove("orchestrator")
        normalized.insert(0, "orchestrator")
    return normalized


def _latest_log_age_sec(paths: list[Path]) -> float | None:
    mtimes: list[float] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            mtimes.append(path.stat().st_mtime)
        except OSError:
            continue
    if not mtimes:
        return None
    return max(0.0, time.time() - max(mtimes))


def _jsonl_tail(path: Path, limit: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw in _tail_lines(path, limit * 3):
        try:
            parsed = json.loads(raw)
        except Exception:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records[-limit:]


def send_discord_alert(webhook_url: str, payload: dict[str, Any]) -> tuple[bool, str]:
    url = str(webhook_url or "").strip()
    if not url:
        return False, "discord_webhook_unset"

    node = str(payload.get("node") or "").strip() or "unknown"
    event_type = str(payload.get("event_type") or "guard_event")
    decision = str(payload.get("decision") or "unknown")
    symptoms = payload.get("symptoms") if isinstance(payload.get("symptoms"), list) else []
    retries = int(payload.get("retry_count") or 0)
    retry_ceiling = int(payload.get("retry_ceiling") or 0)
    remediation = str(payload.get("remediation_action") or "none")
    remediation_result = str(payload.get("remediation_result") or "none")

    message = (
        f"[guard] node={node} event={event_type} decision={decision} "
        f"action={remediation} result={remediation_result} "
        f"retries={retries}/{retry_ceiling} "
        f"symptoms={','.join(str(item) for item in symptoms) or 'none'}"
    )[:1800]

    body = json.dumps({"content": message}, ensure_ascii=False).encode("utf-8")
    request = urllib_request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib_request.urlopen(request, timeout=10.0) as response:  # nosec B310
            return True, f"http_{getattr(response, 'status', 200)}"
    except urllib_error.HTTPError as exc:
        return False, f"http_{exc.code}"
    except Exception as exc:
        return False, str(exc)


class GuardDaemon:
    def __init__(
        self,
        settings: GuardSettings,
        *,
        client: CloneManagerClient | None = None,
        alert_sender: Callable[[str, dict[str, Any]], tuple[bool, str]] = send_discord_alert,
    ) -> None:
        self.settings = settings
        self.client = client or CloneManagerClient(
            script_path=settings.clone_manager_script,
            python_bin=settings.python_bin,
        )
        self.alert_sender = alert_sender

    @property
    def _runs_path(self) -> Path:
        return self.settings.guard_logs_root / "runs.jsonl"

    @property
    def _summary_path(self) -> Path:
        return self.settings.guard_logs_root / "summary.log"

    @property
    def _state_path(self) -> Path:
        return self.settings.guard_logs_root / "state.json"

    def _ensure_paths(self) -> None:
        self.settings.guard_logs_root.mkdir(parents=True, exist_ok=True)
        self.settings.node_activity_root.mkdir(parents=True, exist_ok=True)

    def _load_previous_state(self) -> dict[str, Any]:
        state = _read_json(self._state_path, {})
        return state if isinstance(state, dict) else {}

    def _maybe_alert(
        self,
        *,
        previous_node_state: dict[str, Any],
        alert_key: str,
        alert_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not alert_key:
            return {
                "sent": False,
                "reason": "alert_key_missing",
                "key": "",
            }

        previous_key = str(previous_node_state.get("last_alert_key") or "")
        if previous_key == alert_key:
            return {
                "sent": False,
                "reason": "duplicate",
                "key": alert_key,
            }

        ok, status = self.alert_sender(self.settings.discord_webhook_url, alert_payload)
        return {
            "sent": ok,
            "reason": status,
            "key": alert_key,
        }

    def _build_paths(self, node: str, status_payload: dict[str, Any]) -> dict[str, Path]:
        return {
            "management": Path(
                str(status_payload.get("log_file") or self.settings.node_logs_root / node / "management.log")
            ),
            "runtime": Path(
                str(status_payload.get("runtime_log_file") or self.settings.node_logs_root / node / "runtime.log")
            ),
            "attention": Path(
                str(
                    status_payload.get("attention_log_file")
                    or self.settings.attention_logs_root / node / "warning-plus.log"
                )
            ),
            "hermes_errors": Path(
                str(status_payload.get("hermes_errors_log_file") or self.settings.node_logs_root / node / "hermes" / "errors.log")
            ),
            "hermes_gateway": Path(
                str(status_payload.get("hermes_gateway_log_file") or self.settings.node_logs_root / node / "hermes" / "gateway.log")
            ),
            "hermes_agent": Path(
                str(status_payload.get("hermes_agent_log_file") or self.settings.node_logs_root / node / "hermes" / "agent.log")
            ),
            "activity": self.settings.node_activity_root / f"{node}.jsonl",
        }

    def _evaluate_node(
        self,
        *,
        node: str,
        previous_node_state: dict[str, Any],
        cycle_id: str,
        now_ts: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        retry_count = int(previous_node_state.get("retry_count") or 0)
        cooldown_until_raw = str(previous_node_state.get("cooldown_until") or "")
        cooldown_until = _parse_iso(cooldown_until_raw)

        record: dict[str, Any] = {
            "ts": now_ts,
            "cycle_id": cycle_id,
            "node": node,
            "symptoms": [],
            "decision": "healthy",
            "remediation_action": "none",
            "remediation_result": "none",
            "retry_count": retry_count,
            "retry_ceiling": self.settings.retry_ceiling,
            "cooldown_until": cooldown_until_raw,
            "retry_exhausted": False,
            "alert": {"sent": False, "reason": "none", "key": ""},
        }

        try:
            status_payload = self.client.status(node)
        except Exception as exc:
            record["symptoms"] = ["status-error"]
            record["decision"] = "skipped"
            record["remediation_result"] = "status-unavailable"
            record["error"] = str(exc)
            alert = self._maybe_alert(
                previous_node_state=previous_node_state,
                alert_key="skipped:status-error",
                alert_payload={
                    **record,
                    "event_type": "node_unhealthy_no_remediation",
                },
            )
            record["alert"] = alert
            node_state = {
                "node": node,
                "decision": record["decision"],
                "symptoms": record["symptoms"],
                "remediation_action": record["remediation_action"],
                "remediation_result": record["remediation_result"],
                "retry_count": retry_count,
                "retry_exhausted": False,
                "cooldown_until": cooldown_until_raw,
                "updated_at": now_ts,
                "last_alert_key": alert.get("key") if alert.get("sent") else previous_node_state.get("last_alert_key", ""),
                "status": "unknown",
                "running": None,
                "attention_events_last_200": 0,
                "last_log_age_sec": None,
            }
            return record, node_state

        paths = self._build_paths(node, status_payload)
        container_state = status_payload.get("container_state") if isinstance(status_payload.get("container_state"), dict) else {}
        running = bool(container_state.get("running"))
        status_text = str(container_state.get("status") or "unknown").strip().lower()
        required_mounts_ok = status_payload.get("required_mounts_ok")
        attention_events = _count_tail_lines(paths["attention"], 200)
        last_log_age_sec = _latest_log_age_sec([
            paths["runtime"],
            paths["hermes_errors"],
            paths["hermes_gateway"],
            paths["hermes_agent"],
            paths["activity"],
        ])
        stalled = bool(running and last_log_age_sec is not None and last_log_age_sec >= self.settings.stall_timeout_sec)

        symptoms: list[str] = []
        restartable = False
        skip_reasons: list[str] = []

        if attention_events >= self.settings.attention_warn_threshold:
            symptoms.append("attention-spike")
        if required_mounts_ok is False:
            symptoms.append("required-mounts-missing")
            skip_reasons.append("required-mounts-missing")
        if not running:
            symptoms.append("not-running")
            restartable = True
        elif status_text in BAD_RUNNING_STATUSES:
            symptoms.append(f"bad-status:{status_text}")
            restartable = True
        elif status_text in TRANSITION_STATUSES:
            symptoms.append(f"transition:{status_text}")
            skip_reasons.append(f"transition:{status_text}")
        if stalled:
            symptoms.append("stalled")
            restartable = True

        if not symptoms:
            record["decision"] = "healthy"
            retry_count = 0
            cooldown_until_raw = ""
            node_state = {
                "node": node,
                "decision": "healthy",
                "symptoms": [],
                "remediation_action": "none",
                "remediation_result": "none",
                "retry_count": 0,
                "retry_exhausted": False,
                "cooldown_until": "",
                "updated_at": now_ts,
                "last_alert_key": "",
                "status": status_text,
                "running": running,
                "attention_events_last_200": attention_events,
                "last_log_age_sec": last_log_age_sec,
                "required_mounts_ok": required_mounts_ok,
            }
            record.update({
                "running": running,
                "status": status_text,
                "attention_events_last_200": attention_events,
                "last_log_age_sec": last_log_age_sec,
                "required_mounts_ok": required_mounts_ok,
                "retry_count": 0,
                "cooldown_until": "",
            })
            return record, node_state

        record.update({
            "symptoms": symptoms,
            "running": running,
            "status": status_text,
            "attention_events_last_200": attention_events,
            "last_log_age_sec": last_log_age_sec,
            "required_mounts_ok": required_mounts_ok,
        })

        if restartable:
            now_dt = _parse_iso(now_ts) or datetime.now(timezone.utc)
            if cooldown_until is not None and cooldown_until > now_dt:
                record["decision"] = "cooldown-active"
                record["remediation_result"] = "cooldown-active"
            elif retry_count >= self.settings.retry_ceiling:
                record["decision"] = "retry-exhausted"
                record["remediation_result"] = "retry-ceiling-reached"
                record["retry_exhausted"] = True
                alert = self._maybe_alert(
                    previous_node_state=previous_node_state,
                    alert_key="retry-exhausted",
                    alert_payload={
                        **record,
                        "event_type": "retry_ceiling_reached",
                    },
                )
                record["alert"] = alert
            else:
                record["remediation_action"] = "restart"
                start_alert = self._maybe_alert(
                    previous_node_state=previous_node_state,
                    alert_key=f"restart-started:{retry_count + 1}",
                    alert_payload={
                        **record,
                        "event_type": "remediation_started",
                    },
                )
                record["alert"] = start_alert
                retry_count += 1
                cooldown_until_ts = datetime.fromtimestamp(
                    time.time() + self.settings.restart_cooldown_sec,
                    tz=timezone.utc,
                ).isoformat().replace("+00:00", "Z")
                record["retry_count"] = retry_count
                record["cooldown_until"] = cooldown_until_ts
                try:
                    restart_payload = self.client.restart(node)
                    record["decision"] = "restarted"
                    record["remediation_result"] = "restart-succeeded"
                    record["restart_payload"] = restart_payload
                except Exception as exc:
                    record["decision"] = "restart-failed"
                    record["remediation_result"] = "restart-failed"
                    record["error"] = str(exc)
                    fail_alert = self._maybe_alert(
                        previous_node_state={"last_alert_key": start_alert.get("key", "")},
                        alert_key=f"restart-failed:{retry_count}",
                        alert_payload={
                            **record,
                            "event_type": "remediation_failed",
                        },
                    )
                    record["alert"] = fail_alert
        elif skip_reasons:
            record["decision"] = "skipped"
            record["remediation_result"] = "skip-no-restart"
            alert = self._maybe_alert(
                previous_node_state=previous_node_state,
                alert_key=f"skipped:{'|'.join(skip_reasons)}",
                alert_payload={
                    **record,
                    "event_type": "node_unhealthy_no_remediation",
                },
            )
            record["alert"] = alert
        else:
            record["decision"] = "warned"
            record["remediation_result"] = "notify-only"
            alert = self._maybe_alert(
                previous_node_state=previous_node_state,
                alert_key=f"warned:{'|'.join(symptoms)}",
                alert_payload={
                    **record,
                    "event_type": "node_unhealthy_no_remediation",
                },
            )
            record["alert"] = alert
            retry_count = 0
            cooldown_until_raw = ""
            record["retry_count"] = 0
            record["cooldown_until"] = ""

        last_alert_key = previous_node_state.get("last_alert_key", "")
        alert_payload = record.get("alert") if isinstance(record.get("alert"), dict) else {}
        if alert_payload.get("sent") and alert_payload.get("key"):
            last_alert_key = alert_payload["key"]
        elif record["decision"] == "healthy":
            last_alert_key = ""

        node_state = {
            "node": node,
            "decision": record["decision"],
            "symptoms": symptoms,
            "remediation_action": record["remediation_action"],
            "remediation_result": record["remediation_result"],
            "retry_count": int(record.get("retry_count") or retry_count),
            "retry_exhausted": bool(record.get("retry_exhausted")),
            "cooldown_until": str(record.get("cooldown_until") or cooldown_until_raw or ""),
            "updated_at": now_ts,
            "last_alert_key": last_alert_key,
            "status": status_text,
            "running": running,
            "attention_events_last_200": attention_events,
            "last_log_age_sec": last_log_age_sec,
            "required_mounts_ok": required_mounts_ok,
        }
        return record, node_state

    def _build_summary(self, nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
        decisions = [str(node.get("decision") or "") for node in nodes.values()]
        return {
            "total_nodes": len(nodes),
            "healthy_nodes": sum(1 for decision in decisions if decision == "healthy"),
            "warned_nodes": sum(1 for decision in decisions if decision in {"warned", "skipped", "restart-failed", "retry-exhausted"}),
            "remediated_nodes": sum(1 for decision in decisions if decision == "restarted"),
            "cooldown_nodes": sum(1 for decision in decisions if decision == "cooldown-active"),
            "retry_exhausted_nodes": sum(1 for decision in decisions if decision == "retry-exhausted"),
        }

    def _summary_line(self, record: dict[str, Any]) -> str:
        symptoms = ",".join(str(item) for item in record.get("symptoms") or []) or "none"
        return (
            f"[{record['ts']}] "
            f"cycle={record['cycle_id']} "
            f"node={record['node']} "
            f"decision={record['decision']} "
            f"action={record['remediation_action']} "
            f"result={record['remediation_result']} "
            f"retries={record['retry_count']}/{record['retry_ceiling']} "
            f"cooldown_until={record.get('cooldown_until') or '-'} "
            f"symptoms={symptoms}"
        )

    def run_once(self) -> dict[str, Any]:
        self._ensure_paths()
        previous_state = self._load_previous_state()
        previous_nodes = previous_state.get("nodes") if isinstance(previous_state.get("nodes"), dict) else {}
        cycle_id = datetime.now(timezone.utc).strftime("guard-%Y%m%dT%H%M%SZ")
        now_ts = _utc_now()

        nodes: dict[str, dict[str, Any]] = {}
        for node in _discover_nodes(self.settings):
            previous_node_state = previous_nodes.get(node) if isinstance(previous_nodes, dict) else {}
            if not isinstance(previous_node_state, dict):
                previous_node_state = {}
            record, node_state = self._evaluate_node(
                node=node,
                previous_node_state=previous_node_state,
                cycle_id=cycle_id,
                now_ts=now_ts,
            )
            nodes[node] = node_state
            _append_jsonl(self._runs_path, record)
            _append_summary(self._summary_path, self._summary_line(record))

        snapshot = {
            "daemon_status": "running",
            "updated_at": now_ts,
            "last_cycle_id": cycle_id,
            "config": {
                "poll_interval_sec": self.settings.poll_interval_sec,
                "restart_cooldown_sec": self.settings.restart_cooldown_sec,
                "retry_ceiling": self.settings.retry_ceiling,
                "stall_timeout_sec": self.settings.stall_timeout_sec,
                "attention_warn_threshold": self.settings.attention_warn_threshold,
            },
            "summary": self._build_summary(nodes),
            "nodes": nodes,
            "paths": {
                "runs": str(self._runs_path),
                "summary_log": str(self._summary_path),
                "state": str(self._state_path),
            },
        }
        _write_json(self._state_path, snapshot)
        return snapshot

    def run_forever(self) -> None:
        self._ensure_paths()
        while True:
            self.run_once()
            time.sleep(self.settings.poll_interval_sec)


def run_guard(settings: GuardSettings | None = None, *, once: bool = False) -> dict[str, Any] | None:
    resolved = settings or load_settings()
    if not resolved.clone_manager_script.exists():
        raise GuardError(f"clone_manager script not found: {resolved.clone_manager_script}")

    daemon = GuardDaemon(resolved)
    if once:
        snapshot = daemon.run_once()
        print(json.dumps(snapshot, ensure_ascii=False))
        return snapshot

    print(
        "[guard] starting doctor loop "
        f"(poll_interval_sec={resolved.poll_interval_sec}, "
        f"restart_cooldown_sec={resolved.restart_cooldown_sec}, "
        f"retry_ceiling={resolved.retry_ceiling})"
    )
    daemon.run_forever()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes Orchestrator guard daemon")
    parser.add_argument("--once", action="store_true", help="Run one guard cycle and exit")
    args = parser.parse_args()

    try:
        run_guard(once=bool(args.once))
        return 0
    except GuardError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
