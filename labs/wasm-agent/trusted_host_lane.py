"""Bounded trusted-host adapter execution without exporting host credentials."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from fixture_outcomes import lane_outcome


class TrustedHostLaneError(RuntimeError):
    pass


def artifact_digest(root: Path, relative_paths: list[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(set(relative_paths)):
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise TrustedHostLaneError("trusted-host artifact path escapes workspace") from exc
        if not path.is_file():
            raise TrustedHostLaneError(f"trusted-host artifact is missing: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _command(root: Path, adapter: dict[str, Any], task_path: Path) -> list[str]:
    declared = adapter.get("liveCommand")
    if not isinstance(declared, list) or len(declared) < 2 or declared[0] != "python3":
        raise TrustedHostLaneError("trusted-host adapter requires a Python workspace command")
    resolved = [str(task_path) if str(item) == "{task}" else str(item) for item in declared]
    script = (root / resolved[1]).resolve()
    try:
        script.relative_to(root.resolve())
    except ValueError as exc:
        raise TrustedHostLaneError("trusted-host adapter command escapes workspace") from exc
    if not script.is_file() or str(script.relative_to(root)) not in adapter.get("trustedHostFiles", []):
        raise TrustedHostLaneError("trusted-host adapter script is not artifact-bound")
    resolved[1] = str(script)
    return resolved


def _environment(
    adapter: dict[str, Any], root: Path, events_path: Path | None = None,
    diagnostics_path: Path | None = None,
) -> dict[str, str]:
    allowed = {
        "PATH", "HOME", "CODEX_HOME", "TMPDIR", "SSL_CERT_FILE", "CODEX_CA_CERTIFICATE",
        "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY", "https_proxy", "http_proxy",
        "all_proxy", "no_proxy",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env.update({
        "MF5_PROVIDER_KIND": "codex_subscription",
        "MF5_ADAPTER_SERVER": str(root / "plugins/wasm-agent/server"),
        "MF5_SOURCE_ROOT": str(root),
        "MF5_WORKSPACE_ROOT": str(root),
        "MF5_CODEX_MODEL": str(adapter.get("codexModel") or "gpt-5.6-sol"),
        "MF5_ROUTE_CAPS_JSON": json.dumps(adapter.get("routeCapabilities") or ["repo.read"]),
        "MF5_BROWSER_ENTRY_URL": str(adapter.get("browserEntryUrl") or ""),
        "MF5_RUNTIME_ENTITIES_JSON": json.dumps(adapter.get("runtimeEntities") or []),
        "FRONTIER_MODEL": str(adapter.get("runtimeModel") or ""),
        "PYTHONPATH": str(root / "labs/wasm-agent"),
    })
    if events_path is not None:
        env["WASM_AGENT_EVENTS_PATH"] = str(events_path)
    if diagnostics_path is not None:
        env["MF5_RUN_DIAGNOSTICS_PATH"] = str(diagnostics_path)
    return env


def execute(
    root: Path,
    adapter: dict[str, Any],
    task: dict[str, Any],
    *,
    timeout: int,
) -> tuple[dict[str, Any], str]:
    files = adapter.get("trustedHostFiles")
    if adapter.get("executionBoundary") != "trusted_host" or not isinstance(files, list) or not files:
        raise TrustedHostLaneError("trusted-host execution boundary is undeclared")
    observed_digest = artifact_digest(root, [str(item) for item in files])
    if observed_digest != adapter.get("adapterArtifactSha256") or observed_digest != adapter.get("candidateDigest"):
        raise TrustedHostLaneError("trusted-host adapter digest mismatch")
    temporary = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix="mf5-fixture-", suffix=".json", delete=False,
    )
    task_path = Path(temporary.name)
    events_path = task_path.with_suffix(".events.jsonl")
    diagnostics_path = task_path.with_suffix(".diagnostics.json")
    try:
        json.dump(task, temporary, separators=(",", ":"))
        temporary.close()
        os.chmod(task_path, 0o600)
        command = _command(root, adapter, task_path)
        completed = subprocess.run(
            command, cwd=root, env=_environment(adapter, root, events_path, diagnostics_path),
            capture_output=True, text=True,
            timeout=max(1, min(timeout, 600)), check=False,
        )
    except subprocess.TimeoutExpired as exc:
        events_path.unlink(missing_ok=True)
        diagnostics_path.unlink(missing_ok=True)
        raise TrustedHostLaneError("trusted-host adapter timed out") from exc
    finally:
        if not temporary.closed:
            temporary.close()
        task_path.unlink(missing_ok=True)
    events: list[dict[str, Any]] = []
    if events_path.is_file():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
        events_path.unlink(missing_ok=True)
    diagnostics: dict[str, Any] = {}
    if diagnostics_path.is_file():
        try:
            diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
        except ValueError:
            diagnostics = {}
        diagnostics_path.unlink(missing_ok=True)
    answer = completed.stdout.strip()
    candidate_available = completed.returncode == 0 and bool(answer)
    outcome = lane_outcome(candidate_available)
    lane = {
        "schema": "wasm-agent.safe-lab.trusted-host-lane-result.v1",
        **outcome,
        "adapter": adapter.get("id"),
        "model": adapter.get("runtimeModel"),
        "task": {
            "fixtureId": (task.get("fixture") or {}).get("id"),
            "taskDigest": task.get("taskDigest"),
            "adjudication": task.get("adjudication"),
            "rankingAllowed": bool((task.get("adjudication") or {}).get("rankingAllowed")),
        },
        "readinessCandidatePassed": candidate_available,
        "comparable": candidate_available and bool((task.get("adjudication") or {}).get("rankingAllowed")),
        "command": {
            "returncode": completed.returncode,
            "stdoutChars": len(completed.stdout),
            "stdoutSha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
            "stderrChars": len(completed.stderr),
            "stderrTail": completed.stderr[-1200:] if completed.returncode else "",
        },
        "credentialBoundary": "host_codex_cache_not_exported",
        "toolCallCount": len(events),
        "toolEvents": events[:32],
        "providerCalls": int(diagnostics.get("providerCalls") or 0),
        "providerAttempts": int(diagnostics.get("providerAttempts") or 0),
        "usageTotals": diagnostics.get("usageTotals") if isinstance(diagnostics.get("usageTotals"), dict) else {},
    }
    return lane, answer
