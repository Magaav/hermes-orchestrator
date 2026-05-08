#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PLUGIN_ROOT / "server" / "static_server.py"
DEFAULT_STATE_DIR = PLUGIN_ROOT / "state"
DEFAULT_APP_URL = "http://127.0.0.1:8877"
DEFAULT_BRIDGE_URL = "http://127.0.0.1:8790"
DEFAULT_AGENTS_ROOT = Path("/local/agents")
RUNNING_TASK_STATUSES = {"queued", "submitted", "running", "started"}

spec = importlib.util.spec_from_file_location("wasm_agent_static_server", SERVER_PATH)
server_mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = server_mod
spec.loader.exec_module(server_mod)


@dataclass
class ProbeResult:
    name: str
    ok: bool
    status: int
    surface: str
    category: str
    summary: str
    evidence: str
    severity: str = "high"
    confidence: float = 0.86
    exploitability: float = 0.55
    proposed_action: str = ""


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_http(method: str, url: str, *, body: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: float = 8) -> tuple[int, dict[str, Any], str]:
    data = json.dumps(body or {}).encode("utf-8") if body is not None else None
    req_headers = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        req_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=req_headers, method=method.upper())
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            status = int(response.status)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        status = int(exc.code)
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {}
    return status, payload if isinstance(payload, dict) else {}, raw[:1200]


def error_code(payload: dict[str, Any]) -> str:
    return str((payload.get("error") if isinstance(payload.get("error"), dict) else {}).get("code") or "")


def auth_probe(base_url: str, path: str, surface: str, name: str) -> ProbeResult:
    status, payload, raw = read_http("GET", f"{base_url}{path}")
    ok = status == HTTPStatus.UNAUTHORIZED and error_code(payload) == "auth_required"
    return ProbeResult(
        name=name,
        ok=ok,
        status=status,
        surface=surface,
        category="auth-gate",
        summary=f"{path} must reject unauthenticated access",
        evidence=f"GET {path} -> HTTP {status}; body={json.dumps(payload or raw, ensure_ascii=True)[:900]}",
        proposed_action=f"Require an authenticated allowed-account session before serving {path}.",
    )


def browser_stream_origin_probe(base_url: str) -> ProbeResult:
    key = base64.b64encode(uuid.uuid4().bytes).decode("ascii")
    headers = {
        "Connection": "Upgrade",
        "Upgrade": "websocket",
        "Sec-WebSocket-Key": key,
        "Sec-WebSocket-Version": "13",
        "Origin": "https://attacker.invalid",
    }
    cookie = local_admin_cookie()
    if cookie:
        headers["Cookie"] = cookie
    status, payload, raw = read_http("GET", f"{base_url}/browser/stream", headers=headers)
    code = error_code(payload)
    ok = (
        status == HTTPStatus.FORBIDDEN
        and code in {"origin_rejected", "browser_disabled"}
    ) or (
        not cookie
        and status == HTTPStatus.UNAUTHORIZED
        and code == "auth_required"
    )
    auth_note = "authenticated admin cookie" if cookie else "no local admin cookie; auth gate checked before Origin guard"
    return ProbeResult(
        name="browser_stream_cross_origin_rejected",
        ok=ok,
        status=status,
        surface="browser",
        category="websocket-origin",
        summary="/browser/stream must reject cross-origin WebSocket upgrades",
        evidence=f"GET /browser/stream upgrade with Origin attacker.invalid ({auth_note}) -> HTTP {status}; body={json.dumps(payload or raw, ensure_ascii=True)[:900]}",
        proposed_action="Reject missing or cross-origin WebSocket Origin headers before the browser stream upgrade.",
    )


def config_probe(base_url: str) -> ProbeResult:
    status, payload, raw = read_http("GET", f"{base_url}/config.json")
    auth = payload.get("auth") if isinstance(payload.get("auth"), dict) else {}
    exposed = "adminEmail" in auth or "admin_email" in raw or "ADMIN_EMAIL" in raw
    ok = status == HTTPStatus.OK and not exposed
    return ProbeResult(
        name="public_config_no_admin_email",
        ok=ok,
        status=status,
        surface="config",
        category="config-leak",
        summary="/config.json must not expose admin allowlist labels",
        evidence=f"GET /config.json -> HTTP {status}; auth_keys={sorted(auth.keys()) if isinstance(auth, dict) else []}",
        severity="medium",
        confidence=0.78,
        exploitability=0.35,
        proposed_action="Keep private allowlists in wa.env/server-side state and expose only boolean login configuration.",
    )


def run_deterministic_probes(base_url: str) -> list[ProbeResult]:
    clean = base_url.rstrip("/")
    return [
        auth_probe(clean, "/health", "auth", "health_requires_auth"),
        auth_probe(clean, "/bridge/nodes", "bridge", "bridge_nodes_requires_auth"),
        auth_probe(clean, "/security-loop/status", "auth", "security_loop_requires_auth"),
        browser_stream_origin_probe(clean),
        config_probe(clean),
    ]


def finding_from_probe(probe: ProbeResult, run_id: str) -> dict[str, Any]:
    return {
        "id": f"{run_id}-{probe.name}",
        "source_node": "wasm-agent-security-loop",
        "target_surface": probe.surface,
        "category": probe.category,
        "severity": probe.severity,
        "confidence": probe.confidence,
        "exploitability": probe.exploitability,
        "summary": probe.summary,
        "evidence_preview": probe.evidence,
        "proposed_action": probe.proposed_action,
    }


def runner_server(state_dir: Path) -> Any:
    return SimpleNamespace(state_dir=state_dir)


def local_admin_cookie() -> str:
    path = server_mod.auth_db_path()
    if not path.exists():
        return ""
    try:
        with sqlite3.connect(path, timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT id, email FROM user_tb ORDER BY last_login_at DESC").fetchall()
    except Exception:
        return ""
    for row in rows:
        if server_mod.is_admin_email(str(row["email"])):
            return server_mod.auth_cookie(str(row["id"])).split(";", 1)[0]
    return ""


def authenticated_route_map(base_url: str) -> list[dict[str, Any]]:
    cookie = local_admin_cookie()
    routes = [
        "/auth/session",
        "/health",
        "/config.json",
        "/account/devices",
        "/storage/export",
        "/security-loop/status",
        "/security-loop/findings",
        "/security-loop/runs",
        "/bridge/nodes",
        "/bridge/tasks",
        "/bridge/resources",
    ]
    if not cookie:
        return [{"route": "admin-session", "status": "unavailable", "summary": "No local allowed admin session was available for authenticated route coverage."}]
    coverage: list[dict[str, Any]] = []
    for route in routes:
        status, payload, raw = read_http("GET", f"{base_url.rstrip('/')}{route}", headers={"Cookie": cookie}, timeout=8)
        code = error_code(payload)
        coverage.append({
            "route": route,
            "status": status,
            "ok": status < 500 and code not in {"auth_required", "not_admin"},
            "error_code": code,
            "summary": json.dumps(payload or raw, ensure_ascii=True)[:220],
        })
    return coverage


def save_finding(state_dir: Path, finding: dict[str, Any]) -> dict[str, Any]:
    return server_mod.save_security_loop_finding(runner_server(state_dir), finding, {
        "id": "0",
        "email": "security-loop-runner@local",
        "role": "admin",
    })


def task_prompt_attack(surfaces: list[str], authenticated_routes: list[dict[str, Any]] | None = None) -> str:
    surface_text = ", ".join(surfaces)
    route_text = json.dumps(authenticated_routes or [], indent=2, sort_keys=True, ensure_ascii=True)
    return f"""You are hermes-attack running a bounded defensive audit for owned Hermes/Colmeio surfaces only.

Scope: wasm-agent, Hermes bridge, node lifecycle controls, account auth, storage import/export, attachments, service-worker caching, Host Browser/CDP, and public config.
Focus surfaces this run: {surface_text}.

Authenticated platform context:
- The host runner exercised owned wasm-agent routes with a local allowed admin session.
- Cookies and tokens are intentionally withheld from you; do not ask for or print them.
- Use this route map to understand what an authenticated user can reach, then look for leaks, unsafe state transitions, missing authorization boundaries, cache exposure, and bridge abuse paths.
{route_text}

Rules:
- Do not scan third-party targets, brute force credentials, run DDoS/load pressure, or attempt persistence.
- Prefer safe HTTP requests, source inspection, config review, and proof-by-status/evidence.
- If a finding is real, return a JSON array of hermes.security_loop.finding.v1-compatible objects with: target_surface, category, severity, confidence, exploitability, summary, evidence_preview, proposed_action.
- Include exact local request/response evidence when relevant. Keep secrets redacted.
- If no issue is found, return an empty JSON array and a short note."""


def task_prompt_defense(findings: list[dict[str, Any]]) -> str:
    return """You are hermes-defense. Review these security-loop findings and produce bounded mitigation plans.

Do not apply changes directly. For each actionable finding, provide:
- risk summary
- smallest fix
- files/functions to inspect
- tests to add or run
- rollback trigger
- residual risk

Findings:
""" + json.dumps(findings, indent=2, sort_keys=True, ensure_ascii=True)


def parse_env_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}
    env: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            env[key] = value
    return env


def docker_container_ip(container_name: str) -> str:
    try:
        proc = subprocess.run(
            ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container_name],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip().splitlines()[0].strip() if (proc.stdout or "").strip() else ""


def node_runs_api(agents_root: Path, node: str) -> dict[str, str]:
    env = parse_env_file(agents_root / "envs" / f"{node}.env")
    explicit_url_key = f"HERMES_WASM_AGENT_RUNS_API_{node.upper().replace('-', '_')}_URL"
    explicit_key_key = f"HERMES_WASM_AGENT_RUNS_API_{node.upper().replace('-', '_')}_KEY"
    explicit_url = env.get(explicit_url_key, "").strip()
    if explicit_url:
        return {"url": explicit_url.rstrip("/"), "key": env.get(explicit_key_key, env.get("API_SERVER_KEY", "")).strip()}
    port = str(env.get("API_SERVER_PORT") or "").strip()
    if not port and node == "orchestrator":
        port = "8642"
    if not port:
        raise RuntimeError(f"{node} env does not define API_SERVER_PORT")
    host = str(env.get("API_SERVER_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    if node != "orchestrator" and host in {"0.0.0.0", "127.0.0.1", "localhost"}:
        host = docker_container_ip(f"hermes-node-{node}")
        if not host:
            raise RuntimeError(f"{node} container IP is unavailable; start the node first")
    return {"url": f"http://{host}:{port}".rstrip("/"), "key": str(env.get("API_SERVER_KEY") or "").strip()}


def runs_api_headers(config: dict[str, str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    if config.get("key"):
        headers["Authorization"] = f"Bearer {config['key']}"
    return headers


def submit_runs_api_task(agents_root: Path, target_node: str, prompt: str) -> dict[str, Any]:
    config = node_runs_api(agents_root, target_node)
    status, payload, raw = read_http(
        "POST",
        f"{config['url']}/v1/runs",
        body={
            "input": prompt,
            "session_id": f"wasm-agent-security-loop-{target_node}",
            "instructions": "You are serving a wasm-agent host-owned security-loop task. Keep output bounded, structured, and secrets redacted.",
        },
        headers=runs_api_headers(config),
        timeout=20,
    )
    if status >= 400 or not payload.get("run_id"):
        message = error_code(payload) or raw or f"HTTP {status}"
        raise RuntimeError(f"{target_node} Runs API rejected task: {message}")
    return {
        "schema": "hermes.wasm_agent.security_loop.runs_api_task.v1",
        "task_id": str(payload["run_id"]),
        "run_id": str(payload["run_id"]),
        "status": str(payload.get("status") or "started"),
        "target_node": target_node,
        "api_url": config["url"],
        "prompt": prompt,
    }


def poll_runs_api_task(agents_root: Path, target_node: str, run_id: str, wait_sec: float) -> dict[str, Any]:
    config = node_runs_api(agents_root, target_node)
    deadline = time.time() + max(0.0, wait_sec)
    latest: dict[str, Any] = {}
    while time.time() <= deadline:
        status, payload, raw = read_http(
            "GET",
            f"{config['url']}/v1/runs/{run_id}",
            headers=runs_api_headers(config),
            timeout=10,
        )
        if status >= 400:
            raise RuntimeError(error_code(payload) or raw or f"HTTP {status}")
        latest = payload
        run_status = str(latest.get("status") or "")
        if run_status not in RUNNING_TASK_STATUSES:
            break
        time.sleep(2)
    if wait_sec > 0 and str(latest.get("status") or "") in RUNNING_TASK_STATUSES:
        try:
            latest["stop_status"] = stop_runs_api_task(agents_root, target_node, run_id)
        except Exception as exc:
            latest["stop_status"] = {"error": str(exc)}
        latest["status"] = "timeout"
    result = {"response": str(latest.get("output") or "")}
    return {
        "schema": "hermes.wasm_agent.security_loop.runs_api_task.v1",
        "task_id": run_id,
        "run_id": run_id,
        "status": str(latest.get("status") or "timeout"),
        "target_node": target_node,
        "api_url": config["url"],
        "result": result,
        "usage": latest.get("usage") if isinstance(latest.get("usage"), dict) else {},
        "error": latest.get("error") or None,
        "stop_status": latest.get("stop_status") if isinstance(latest.get("stop_status"), dict) else {},
    }


def stop_runs_api_task(agents_root: Path, target_node: str, run_id: str) -> dict[str, Any]:
    config = node_runs_api(agents_root, target_node)
    status, payload, raw = read_http(
        "POST",
        f"{config['url']}/v1/runs/{run_id}/stop",
        headers=runs_api_headers(config),
        timeout=8,
    )
    if status >= 400:
        raise RuntimeError(error_code(payload) or raw or f"HTTP {status}")
    return payload


def submit_bridge_task(bridge_url: str, target_node: str, prompt: str) -> dict[str, Any]:
    status, payload, raw = read_http(
        "POST",
        f"{bridge_url.rstrip('/')}/task",
        body={"prompt": prompt, "target_node": target_node, "async": True},
        timeout=20,
    )
    if status >= 400 or payload.get("ok") is False:
        message = error_code(payload) or raw or f"HTTP {status}"
        raise RuntimeError(f"{target_node} task rejected: {message}")
    return payload


def poll_bridge_task(bridge_url: str, task_id: str, wait_sec: float) -> dict[str, Any]:
    deadline = time.time() + max(0.0, wait_sec)
    latest: dict[str, Any] = {}
    while time.time() <= deadline:
        status, payload, raw = read_http("GET", f"{bridge_url.rstrip('/')}/tasks/{task_id}", timeout=8)
        if status >= 400 or payload.get("ok") is False:
            raise RuntimeError(error_code(payload) or raw or f"HTTP {status}")
        latest = payload.get("task") if isinstance(payload.get("task"), dict) else payload
        if str(latest.get("status") or "") not in {"queued", "submitted", "running"}:
            return latest
        time.sleep(2)
    return latest or {"task_id": task_id, "status": "timeout"}


def extract_json_array(text: str) -> list[Any]:
    clean = text.strip()
    if not clean:
        return []
    candidates = [clean]
    start = clean.find("[")
    end = clean.rfind("]")
    if start >= 0 and end > start:
        candidates.append(clean[start:end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and isinstance(parsed.get("findings"), list):
            return parsed["findings"]
    return []


def findings_from_task(task: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    raw_items: list[Any] = []
    if isinstance(result.get("findings"), list):
        raw_items = result["findings"]
    else:
        response = str(result.get("response") or result.get("output") or result.get("text") or "")
        raw_items = extract_json_array(response)
    findings: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        findings.append({
            **item,
            "id": item.get("id") or item.get("finding_id") or f"{run_id}-hermes-attack-{index + 1}",
            "source_node": item.get("source_node") or "hermes-attack",
            "task_id": task.get("task_id") or item.get("task_id") or "",
        })
    return findings


def compact_task(task: dict[str, Any]) -> dict[str, Any]:
    compact = {key: value for key, value in task.items() if key != "prompt"}
    prompt = str(task.get("prompt") or "")
    if prompt:
        compact["prompt_preview"] = prompt[:220]
        compact["prompt_length"] = len(prompt)
    return compact


def bridge_node_stats(bridge_url: str, node: str) -> dict[str, Any]:
    status, payload, raw = read_http("GET", f"{bridge_url.rstrip('/')}/nodes/{node}/stats?bucket=daily&days=1", timeout=10)
    if status >= 400 or payload.get("ok") is False:
        return {"error": error_code(payload) or raw or f"HTTP {status}"}
    return payload.get("stats") if isinstance(payload.get("stats"), dict) else payload


def stats_token_total(stats: dict[str, Any]) -> int:
    usage = stats.get("usage") if isinstance(stats.get("usage"), dict) else {}
    usage_totals = usage.get("totals") if isinstance(usage.get("totals"), dict) else {}
    status = stats.get("status") if isinstance(stats.get("status"), dict) else {}
    activity = status.get("activity") if isinstance(status.get("activity"), dict) else {}
    total = usage_totals.get("total_tokens") or activity.get("total_tokens") or 0
    try:
        return max(0, int(float(total)))
    except (TypeError, ValueError):
        return 0


def stats_api_calls(stats: dict[str, Any]) -> int:
    usage = stats.get("usage") if isinstance(stats.get("usage"), dict) else {}
    usage_totals = usage.get("totals") if isinstance(usage.get("totals"), dict) else {}
    status = stats.get("status") if isinstance(stats.get("status"), dict) else {}
    activity = status.get("activity") if isinstance(status.get("activity"), dict) else {}
    total = usage_totals.get("api_calls") or activity.get("api_calls") or 0
    try:
        return max(0, int(float(total)))
    except (TypeError, ValueError):
        return 0


def run_key(mode: str, delivery: str, surfaces: list[str]) -> str:
    payload = {"mode": mode, "delivery": delivery, "surfaces": sorted(set(surfaces))}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def recent_runs(state_dir: Path, *, limit: int = 25) -> list[dict[str, Any]]:
    run_dir = state_dir / "security-loop" / "runs"
    if not run_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(run_dir.glob("security-run-*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(run, dict):
            items.append(run)
        if len(items) >= limit:
            break
    return items


def run_is_clean(run: dict[str, Any]) -> bool:
    return (
        str(run.get("runner_status") or "") == "completed"
        and int(run.get("finding_count") or 0) == 0
        and int(run.get("failed_probe_count") or 0) == 0
        and int(run.get("error_count") or 0) == 0
    )


def clean_repeat_streak(runs: list[dict[str, Any]], key: str) -> int:
    streak = 0
    for run in runs:
        candidate_key = run.get("run_key") or run_key(str(run.get("mode") or ""), str(run.get("delivery") or "runs-api"), list(run.get("surfaces") or []))
        if candidate_key != key:
            continue
        if str(run.get("runner_status") or "") != "completed":
            continue
        if not run_is_clean(run):
            break
        streak += 1
    return streak


def value_summary(
    *,
    clean_streak_before: int,
    max_clean_repeat: int,
    token_delta: int,
    api_delta: int,
    finding_count: int,
    failed_probe_count: int,
    error_count: int,
    skipped: bool,
) -> dict[str, Any]:
    if skipped:
        verdict = "limit_reached"
        recommendation = "Repeated clean audits reached the configured limit; skip node tokens until code, config, routes, or scope changes."
    elif finding_count or failed_probe_count or error_count:
        verdict = "useful"
        recommendation = "Findings or probe failures need triage before public launch."
    elif token_delta > 0 and clean_streak_before + 1 >= max_clean_repeat:
        verdict = "stable_clean_limit_next"
        recommendation = "This clean pass spent tokens; the next identical clean run should be skipped unless forced."
    elif token_delta > 0:
        verdict = "clean_but_spent_tokens"
        recommendation = "Clean result is regression evidence; keep repeats bounded to avoid paying for the same coverage."
    else:
        verdict = "clean_low_cost"
        recommendation = "Clean result with little or no node-token movement; useful as a cheap launch-readiness heartbeat."
    return {
        "verdict": verdict,
        "recommendation": recommendation,
        "clean_repeat_streak_before": clean_streak_before,
        "clean_repeat_streak_after": clean_streak_before + (0 if skipped else 1 if not (finding_count or failed_probe_count or error_count) else 0),
        "max_clean_repeat": max_clean_repeat,
        "token_delta": token_delta,
        "api_call_delta": api_delta,
        "launch_candidate": verdict in {"limit_reached", "stable_clean_limit_next", "clean_low_cost"},
    }


def record_run(state_dir: Path, payload: dict[str, Any]) -> None:
    run_dir = state_dir / "security-loop" / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    server_mod.write_json_file(run_dir / f"{payload['run_id']}.json", payload)
    server_mod.write_json_file(state_dir / "security-loop" / "latest-run.json", payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bounded wasm-agent security-loop automation.")
    parser.add_argument("--app-url", default=DEFAULT_APP_URL, help="wasm-agent app origin to probe")
    parser.add_argument("--bridge-url", default=DEFAULT_BRIDGE_URL, help="Hermes bridge origin for node tasks")
    parser.add_argument("--agents-root", default=str(DEFAULT_AGENTS_ROOT), help="Hermes agents root for native Runs API delivery")
    parser.add_argument("--delivery", choices=["runs-api", "bridge"], default="runs-api", help="node task delivery backend")
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR), help="wasm-agent state directory")
    parser.add_argument("--mode", choices=["probes", "nodes", "all"], default="all", help="work to run")
    parser.add_argument("--surface", action="append", default=[], help="surface focus; may be passed more than once")
    parser.add_argument("--wait-sec", type=float, default=0.0, help="seconds to wait for Hermes-node task results")
    parser.add_argument("--no-defense", action="store_true", help="skip hermes-defense mitigation task")
    parser.add_argument("--max-clean-repeat", type=int, default=int(os.getenv("HERMES_WASM_AGENT_SECURITY_MAX_CLEAN_REPEAT", "3")), help="skip native node tasks after this many identical clean runs")
    parser.add_argument("--force-node-task", action="store_true", help="run Hermes-node tasks even after the clean-repeat limit")
    parser.add_argument("--lock-file", default="", help="optional lock file; defaults to state/security-loop/security_loop_run.lock")
    parser.add_argument("--no-lock", action="store_true", help="allow overlapping runner processes")
    parser.add_argument("--dry-run", action="store_true", help="print planned actions without writing findings or queueing tasks")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state_dir = Path(args.state_dir).resolve()
    agents_root = Path(args.agents_root).resolve()
    lock_handle = None
    if not args.no_lock and not args.dry_run:
        lock_path = Path(args.lock_file).resolve() if args.lock_file else state_dir / "security-loop" / "security_loop_run.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = lock_path.open("w", encoding="utf-8")
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({
                "schema": "hermes.wasm_agent.security_loop.run.v1",
                "runner_status": "skipped",
                "reason": "security_loop_run_already_running",
                "lock_file": str(lock_path),
            }, indent=2, sort_keys=True))
            return 0
        lock_handle.write(f"{time.time()} {uuid.uuid4().hex}\n")
        lock_handle.flush()
    run_id = f"security-run-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    surfaces = args.surface or ["auth", "bridge", "browser", "storage", "attachments", "service-worker", "config"]
    key = run_key(args.mode, args.delivery, surfaces)
    previous_runs = recent_runs(state_dir)
    clean_streak_before = clean_repeat_streak(previous_runs, key)
    max_clean_repeat = max(1, int(args.max_clean_repeat or 1))
    node_task_skipped = False
    pre_attack_stats: dict[str, Any] = {}
    post_attack_stats: dict[str, Any] = {}
    token_delta = 0
    api_delta = 0
    value: dict[str, Any] = {}
    started_at = utc_now()
    probes: list[ProbeResult] = []
    authenticated_routes: list[dict[str, Any]] = []
    probe_findings: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    errors: list[str] = []

    def run_snapshot(*, finished: bool) -> dict[str, Any]:
        return {
            "schema": "hermes.wasm_agent.security_loop.run.v1",
            "run_id": run_id,
            "runner_status": "completed" if finished else "running",
            "started_at": started_at,
            "finished_at": utc_now() if finished else "",
            "mode": args.mode,
            "surfaces": surfaces,
            "run_key": key,
            "app_url": args.app_url,
            "bridge_url": args.bridge_url,
            "delivery": args.delivery,
            "probe_count": len(probes),
            "failed_probe_count": len(probe_findings),
            "authenticated_route_count": len(authenticated_routes),
            "finding_count": len(findings),
            "findings": findings,
            "tasks": tasks,
            "errors": errors,
            "error_count": len(errors),
            "value": value,
            "dry_run": bool(args.dry_run),
        }

    def record_progress() -> None:
        if not args.dry_run:
            record_run(state_dir, run_snapshot(finished=False))

    record_progress()

    if args.mode in {"probes", "all"}:
        try:
            probes = run_deterministic_probes(args.app_url)
            authenticated_routes = authenticated_route_map(args.app_url)
            probe_findings = [finding_from_probe(probe, run_id) for probe in probes if not probe.ok]
            findings.extend(probe_findings)
            if not args.dry_run:
                for finding in probe_findings:
                    save_finding(state_dir, finding)
        except Exception as exc:
            errors.append(f"probe_error: {exc}")
        record_progress()

    if args.mode in {"nodes", "all"}:
        if not authenticated_routes:
            authenticated_routes = authenticated_route_map(args.app_url)
        attack_prompt = task_prompt_attack(surfaces, authenticated_routes)
        node_task_skipped = clean_streak_before >= max_clean_repeat and not args.force_node_task and not args.dry_run
        if node_task_skipped:
            tasks.append({
                "target_node": "hermes-attack",
                "task": {
                    "status": "skipped",
                    "reason": "clean_repeat_limit",
                    "clean_repeat_streak": clean_streak_before,
                    "max_clean_repeat": max_clean_repeat,
                },
            })
            record_progress()
        elif not args.dry_run:
            pre_attack_stats = bridge_node_stats(args.bridge_url, "hermes-attack")
        if args.dry_run:
            tasks.append({"target_node": "hermes-attack", "dry_run": True, "prompt_chars": len(attack_prompt)})
        elif not node_task_skipped:
            try:
                if args.delivery == "bridge":
                    attack_task = submit_bridge_task(args.bridge_url, "hermes-attack", attack_prompt)
                    attack_status = attack_task.get("task", attack_task)
                    attack_task_entry = {"target_node": "hermes-attack", "task": compact_task(attack_status) if isinstance(attack_status, dict) else attack_status}
                    tasks.append(attack_task_entry)
                    record_progress()
                    if args.wait_sec > 0 and isinstance(attack_status, dict) and attack_status.get("task_id"):
                        attack_status = poll_bridge_task(args.bridge_url, str(attack_status["task_id"]), args.wait_sec)
                else:
                    attack_status = submit_runs_api_task(agents_root, "hermes-attack", attack_prompt)
                    attack_task_entry = {"target_node": "hermes-attack", "task": compact_task(attack_status)}
                    tasks.append(attack_task_entry)
                    record_progress()
                    if args.wait_sec > 0 and attack_status.get("run_id"):
                        attack_status = poll_runs_api_task(agents_root, "hermes-attack", str(attack_status["run_id"]), args.wait_sec)
                attack_task_entry["task"] = compact_task(attack_status) if isinstance(attack_status, dict) else attack_status
                if str(attack_status.get("status") or "") == "failed":
                    errors.append(f"hermes-attack task failed: {json.dumps(attack_status.get('error') or {}, ensure_ascii=True)[:500]}")
                attack_findings = findings_from_task(attack_status, run_id)
                for finding in attack_findings:
                    save_finding(state_dir, finding)
                findings.extend(attack_findings)
                record_progress()
            except Exception as exc:
                errors.append(f"hermes-attack: {exc}")
        if findings and not args.no_defense:
            defense_prompt = task_prompt_defense(findings)
            if args.dry_run:
                tasks.append({"target_node": "hermes-defense", "dry_run": True, "prompt_chars": len(defense_prompt)})
            else:
                try:
                    if args.delivery == "bridge":
                        defense_task = submit_bridge_task(args.bridge_url, "hermes-defense", defense_prompt)
                        defense_status = defense_task.get("task", defense_task)
                    else:
                        defense_status = submit_runs_api_task(agents_root, "hermes-defense", defense_prompt)
                    tasks.append({"target_node": "hermes-defense", "task": compact_task(defense_status) if isinstance(defense_status, dict) else defense_status})
                    record_progress()
                except Exception as exc:
                    errors.append(f"hermes-defense: {exc}")

    if pre_attack_stats and not args.dry_run:
        post_attack_stats = bridge_node_stats(args.bridge_url, "hermes-attack")
        token_delta = max(0, stats_token_total(post_attack_stats) - stats_token_total(pre_attack_stats))
        api_delta = max(0, stats_api_calls(post_attack_stats) - stats_api_calls(pre_attack_stats))
    value = value_summary(
        clean_streak_before=clean_streak_before,
        max_clean_repeat=max_clean_repeat,
        token_delta=token_delta,
        api_delta=api_delta,
        finding_count=len(findings),
        failed_probe_count=len(probe_findings),
        error_count=len(errors),
        skipped=node_task_skipped,
    )
    run = run_snapshot(finished=True)
    if not args.dry_run:
        record_run(state_dir, run)
    print(json.dumps(run, indent=2, sort_keys=True, ensure_ascii=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
