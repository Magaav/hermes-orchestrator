#!/usr/bin/env python3
"""Prove packaged Hermes can reach exact GLM-5.2 only through a private gateway."""

from __future__ import annotations

import json
import hashlib
import os
import secrets
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "wasm-agent-frontier:latest"
ADAPTER_VOLUME = "wasm-agent-adapter-hermes-0-17-0-v2"
SOURCE_VOLUME = "wasm-agent-safe-lab-local-v11"
FIXTURE_VOLUME = "wasm-agent-safe-lab-output-v1"
TOOL_CONTRACT = ROOT / "labs/wasm-agent/tool-authority-contract.json"
REPORT = ROOT / "reports/context/latest/hermes-live-adapter-result.json"


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False, **kwargs)


def env_value(name: str) -> str:
    for line in (ROOT / "plugins/wasm-agent/conf/wa.env").read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def main() -> int:
    stamp = str(int(time.time()))
    network = f"wa-hermes-proof-{stamp}"
    gateway = f"wa-hermes-gateway-{stamp}"
    gateway_volume = f"wa-hermes-gateway-result-{stamp}"
    workspace_volume = f"wa-hermes-work-{stamp}"
    gateway_env_file = ROOT / f"labs/wasm-agent/staging/hermes-gateway-{stamp}.env"
    lane_env_file = ROOT / f"labs/wasm-agent/staging/hermes-lane-{stamp}.env"
    broker_token = secrets.token_urlsafe(32)
    tool_nonce = secrets.token_hex(16)
    expected_tool_sha256 = hashlib.sha256(f"{tool_nonce}\n".encode()).hexdigest()
    tool_contract_sha256 = hashlib.sha256(TOOL_CONTRACT.read_bytes()).hexdigest()
    upstream_key = env_value("OPENCODE_GO_API_KEY")
    errors: list[str] = []
    receipts: list[dict] = []
    hermes_stdout = ""
    network_evidence: dict = {}
    authority_evidence: dict = {}
    tool_evidence: dict = {}
    started = time.monotonic()
    try:
        if not upstream_key:
            raise RuntimeError("upstream key missing")
        gateway_env_file.parent.mkdir(parents=True, exist_ok=True)
        gateway_env_file.write_text(
            f"UPSTREAM_API_KEY={upstream_key}\nLAB_BROKER_TOKEN={broker_token}\nLAB_MAX_OUTPUT_TOKENS=512\n",
            encoding="utf-8",
        )
        lane_env_file.write_text(
            f"OPENAI_API_KEY={broker_token}\nHERMES_INFERENCE_PROVIDER=custom:lab\n"
            "HERMES_INFERENCE_MODEL=glm-5.2\nHOME=/workspace/home\nHERMES_HOME=/workspace/home/.hermes\n"
            "PYTHONPATH=/adapter/src\n",
            encoding="utf-8",
        )
        os.chmod(gateway_env_file, 0o600)
        os.chmod(lane_env_file, 0o600)
        for command in (["docker", "network", "create", "--internal", network], ["docker", "volume", "create", gateway_volume], ["docker", "volume", "create", workspace_volume]):
            result = run(command)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip())
        launched = run([
            "docker", "run", "-d", "--name", gateway, "--network", network,
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "10000:10000", "--pids-limit", "64", "--memory", "256m", "--cpus", "0.25",
            "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=32m", "--env-file", str(gateway_env_file),
            "-v", f"{gateway_volume}:/gateway-output", "--entrypoint", "python3", IMAGE,
            "/usr/local/bin/model-gateway",
        ])
        if launched.returncode != 0:
            raise RuntimeError(launched.stderr.strip())
        connected = run(["docker", "network", "connect", "bridge", gateway])
        if connected.returncode != 0:
            raise RuntimeError(connected.stderr.strip())
        healthy = False
        for _ in range(20):
            probe = run([
                "docker", "exec", gateway, "python3", "-c",
                "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8787/health',timeout=2).status)",
            ])
            if probe.returncode == 0 and "200" in probe.stdout:
                healthy = True
                break
            time.sleep(0.25)
        if not healthy:
            raise RuntimeError("private gateway did not become healthy")
        lane_security = [
            "--network", network, "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--user", "10000:10000", "--pids-limit", "128",
            "--memory", "2g", "--cpus", "1", "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=128m",
        ]
        lane_mounts = [
            "-v", f"{ADAPTER_VOLUME}:/adapter:ro", "-v", f"{SOURCE_VOLUME}:/source:ro",
            "-v", f"{FIXTURE_VOLUME}:/fixtures:ro", "-v", f"{workspace_volume}:/workspace",
        ]
        isolation_probe = run([
            "docker", "run", "--rm", "--network", network, "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", "32", "--memory", "128m", "--cpus", "0.1",
            "--entrypoint", "python3", IMAGE, "-c",
            "import json,urllib.error,urllib.request; "
            f"g=urllib.request.urlopen('http://{gateway}:8787/health',timeout=2).status==200; "
            "u='https://opencode.ai/zen/go/v1/chat/completions'; "
            "\ntry: urllib.request.urlopen(u,timeout=3); direct=True\n"
            "except urllib.error.HTTPError: direct=True\n"
            "except (urllib.error.URLError,TimeoutError): direct=False\n"
            "print(json.dumps({'gatewayReachable':g,'directUpstreamBlocked':not direct})); "
            "raise SystemExit(0 if g and not direct else 4)",
        ], timeout=15)
        if isolation_probe.returncode != 0:
            raise RuntimeError("lane network isolation proof failed")
        network_evidence = json.loads(isolation_probe.stdout.strip().splitlines()[-1])
        authority_probe = run([
            "docker", "run", "--rm", *lane_security, *lane_mounts,
            "--entrypoint", "python3", IMAGE, "-c",
            "import json,pathlib; e={}; w=pathlib.Path('/workspace/.authority-probe'); "
            "w.write_text('ok'); e['workspaceWritable']=w.read_text()=='ok'; w.unlink(); "
            "\ndef denied(path):\n try: pathlib.Path(path).write_text('x'); return False\n except OSError: return True\n"
            "e['sourceReadOnly']=denied('/source/.authority-write'); "
            "e['fixturesReadOnly']=denied('/fixtures/.authority-write'); "
            "e['runtimeSocketsAbsent']=not pathlib.Path('/var/run/docker.sock').exists() and not pathlib.Path('/run/containerd/containerd.sock').exists(); "
            "e['blockDeviceAbsent']=not pathlib.Path('/dev/sda').exists(); print(json.dumps(e)); "
            "raise SystemExit(0 if all(e.values()) else 5)",
        ])
        if authority_probe.returncode != 0:
            raise RuntimeError("lane mount and authority proof failed")
        authority_evidence = json.loads(authority_probe.stdout.strip().splitlines()[-1])
        config = (
            "model:\n  default: glm-5.2\n  provider: custom:lab\n  context_length: 131072\n"
            "custom_providers:\n  - name: lab\n"
            f"    base_url: http://{gateway}:8787/v1\n"
            "    key_env: OPENAI_API_KEY\n    api_mode: chat_completions\n    max_output_tokens: 512\n"
        )
        initialized = run([
            "docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--user", "10000:10000",
            "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=16m", "-v", f"{workspace_volume}:/workspace",
            "-e", f"HERMES_LAB_CONFIG={config}", "--entrypoint", "python3", IMAGE, "-c",
            "import os,pathlib; p=pathlib.Path('/workspace/home/.hermes/config.yaml'); "
            "p.parent.mkdir(parents=True,exist_ok=True); p.write_text(os.environ['HERMES_LAB_CONFIG'])",
        ])
        if initialized.returncode != 0:
            raise RuntimeError("Hermes workspace initialization failed")
        hermes = run([
            "docker", "run", "--rm", *lane_security, "--env-file", str(lane_env_file), *lane_mounts,
            "--workdir", "/workspace", "--entrypoint", "/adapter/venv/bin/python", IMAGE,
            "-m", "hermes_cli.main", "--safe-mode", "--ignore-rules", "-t", "terminal",
            "-m", "glm-5.2", "--provider", "custom:lab", "-z",
            f"Use the terminal tool to write exactly {tool_nonce} followed by one newline to "
            "/workspace/hermes-tool-proof.txt. Then reply exactly DONE.",
        ], timeout=120)
        hermes_stdout = hermes.stdout.strip()
        if hermes.returncode != 0:
            errors.append(f"Hermes exited {hermes.returncode}: {hermes.stderr[-1000:]}")
        tool_read = run([
            "docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "-v", f"{workspace_volume}:/workspace:ro",
            "--entrypoint", "python3", IMAGE, "-c",
            "import hashlib,json,pathlib; p=pathlib.Path('/workspace/hermes-tool-proof.txt'); "
            "b=p.read_bytes() if p.is_file() else b''; "
            "print(json.dumps({'fileExists':p.is_file(),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}))",
        ])
        if tool_read.returncode == 0:
            tool_evidence = json.loads(tool_read.stdout.strip().splitlines()[-1])
        if not tool_evidence.get("fileExists") or tool_evidence.get("sha256") != expected_tool_sha256:
            errors.append("Hermes terminal tool did not produce the exact private workspace artifact")
        receipt_read = run([
            "docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "-v", f"{gateway_volume}:/gateway-output:ro",
            "--entrypoint", "cat", IMAGE, "/gateway-output/receipts.jsonl",
        ])
        if receipt_read.returncode == 0:
            receipts = [json.loads(line) for line in receipt_read.stdout.splitlines() if line.strip()]
        successful_receipts = [item for item in receipts if item.get("upstreamCalled") is True]
        blocked_receipts = [item for item in receipts if item.get("duplicateClass") == "waste_blocked"]
        if not successful_receipts:
            errors.append("gateway produced no successful upstream receipt")
        elif any(
            item.get("returnedModel") != "frank/GLM-5.2"
            or item.get("status") != 200
            or item.get("contractMatch") is not True
            for item in successful_receipts
        ):
            errors.append("gateway receipt did not prove exact GLM-5.2 success")
        if any(int(item.get("duplicateOrdinal") or 0) > 2 for item in successful_receipts):
            errors.append("duplicate policy exceeded for an identical model request")
        if blocked_receipts:
            errors.append("Hermes attempted a third identical model request; gateway blocked token waste")
        if not any(int(item.get("toolCallCount") or 0) > 0 for item in successful_receipts):
            errors.append("gateway receipts did not observe a model tool call")
        if not hermes_stdout:
            errors.append("Hermes returned no visible answer")
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
    finally:
        gateway_env_file.unlink(missing_ok=True)
        lane_env_file.unlink(missing_ok=True)
        run(["docker", "rm", "-f", gateway])
        run(["docker", "network", "rm", network])
        for volume in (gateway_volume, workspace_volume):
            run(["docker", "volume", "rm", volume])
    result = {
        "ok": not errors,
        "classification": "hermes_live_adapter_pass" if not errors else "hermes_live_adapter_fail",
        "checkedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "durationMs": round((time.monotonic() - started) * 1000),
        "adapter": "hermes",
        "adapterVersion": "0.17.0",
        "adapterVolume": ADAPTER_VOLUME,
        "modelRequest": "glm-5.2",
        "modelReturned": next((item.get("returnedModel") for item in receipts if item.get("returnedModel")), ""),
        "gatewayReceipts": receipts,
        "networkEvidence": network_evidence,
        "authorityContractSha256": tool_contract_sha256,
        "authorityEvidence": authority_evidence,
        "toolEvidence": tool_evidence,
        "toolExpectedSha256": expected_tool_sha256,
        "answerChars": len(hermes_stdout),
        "providerCredentialInLane": False,
        "laneGeneralInternet": not bool(network_evidence.get("directUpstreamBlocked")),
        "toolAuthorityVerified": not errors,
        "comparability": "verified" if not errors else "failed",
        "errors": errors,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
