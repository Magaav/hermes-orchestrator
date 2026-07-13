#!/usr/bin/env python3
"""Trusted host lifecycle for one brokered safe-lab run."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "wasm-agent-frontier:latest"
STAGING = ROOT / "labs/wasm-agent/staging"


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False, **kwargs)


def configured_secret(name: str) -> str:
    path = ROOT / "plugins/wasm-agent/conf/wa.env"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"\'')
    return ""


class SafeLabHost:
    def __init__(self, prefix: str) -> None:
        self.stamp = f"{int(time.time())}-{secrets.token_hex(3)}"
        self.prefix = prefix
        self.network = f"wa-{prefix}-net-{self.stamp}"
        self.gateway = f"wa-{prefix}-gateway-{self.stamp}"
        self.broker_token = secrets.token_urlsafe(32)
        self.gateway_volume = ""
        self.volumes: list[str] = []
        self.temp_files: list[Path] = []
        self.cleanup_errors: list[str] = []

    def create_volume(self, label: str) -> str:
        name = f"wa-{self.prefix}-{label}-{self.stamp}"
        completed = run(["docker", "volume", "create", name])
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or f"failed to create volume {name}")
        self.volumes.append(name)
        return name

    def env_file(self, label: str, values: dict[str, str]) -> Path:
        STAGING.mkdir(parents=True, exist_ok=True)
        path = STAGING / f"{self.prefix}-{label}-{self.stamp}.env"
        lines: list[str] = []
        for key, value in values.items():
            if "\n" in value or "\r" in value:
                raise ValueError(f"environment value contains newline: {key}")
            lines.append(f"{key}={value}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
        self.temp_files.append(path)
        return path

    def start_gateway(
        self, *, max_output_tokens: int, max_provider_calls: int = 4,
        benchmark_scenario: bool = False,
    ) -> None:
        upstream_key = configured_secret("OPENCODE_GO_API_KEY")
        if not upstream_key:
            raise RuntimeError("upstream key missing")
        made = run(["docker", "network", "create", "--internal", self.network])
        if made.returncode != 0:
            raise RuntimeError(made.stderr.strip() or "failed to create private network")
        self.gateway_volume = self.create_volume("gateway")
        gateway_env = self.env_file("gateway", {
            "UPSTREAM_API_KEY": upstream_key,
            "LAB_BROKER_TOKEN": self.broker_token,
            "LAB_MAX_OUTPUT_TOKENS": str(max_output_tokens),
            "LAB_MAX_PROVIDER_CALLS": str(max_provider_calls),
            "LAB_BENCHMARK_SCENARIO": "true" if benchmark_scenario else "false",
        })
        launched = run([
            "docker", "run", "-d", "--name", self.gateway, "--network", self.network,
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "10000:10000", "--pids-limit", "64", "--memory", "256m", "--cpus", "0.25",
            "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=32m", "--env-file", str(gateway_env),
            "-v", f"{self.gateway_volume}:/gateway-output", "--entrypoint", "python3", IMAGE,
            "/usr/local/bin/model-gateway",
        ])
        if launched.returncode != 0:
            raise RuntimeError(launched.stderr.strip() or "failed to start model gateway")
        connected = run(["docker", "network", "connect", "bridge", self.gateway])
        if connected.returncode != 0:
            raise RuntimeError(connected.stderr.strip() or "failed to grant gateway egress")
        for _ in range(20):
            healthy = run([
                "docker", "exec", self.gateway, "python3", "-c",
                "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8787/health',timeout=2).status)",
            ])
            if healthy.returncode == 0 and "200" in healthy.stdout:
                return
            time.sleep(0.25)
        raise RuntimeError("private gateway did not become healthy")

    def endpoint(self) -> str:
        return f"http://{self.gateway}:8787/v1"

    def lane_token(self, lane_id: str) -> str:
        if not lane_id.startswith("harness-") or not lane_id.removeprefix("harness-").isdigit():
            raise ValueError("invalid broker lane id")
        return f"{self.broker_token}.{lane_id}"

    def network_evidence(self) -> dict:
        probe = run([
            "docker", "run", "--rm", "--network", self.network, "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", "32", "--memory", "128m", "--cpus", "0.1",
            "--entrypoint", "python3", IMAGE, "-c",
            "import json,urllib.error,urllib.request; "
            f"g=urllib.request.urlopen('http://{self.gateway}:8787/health',timeout=2).status==200; "
            "u='https://opencode.ai/zen/go/v1/chat/completions'; "
            "\ntry: urllib.request.urlopen(u,timeout=3); direct=True\n"
            "except urllib.error.HTTPError: direct=True\n"
            "except (urllib.error.URLError,TimeoutError): direct=False\n"
            "print(json.dumps({'gatewayReachable':g,'directUpstreamBlocked':not direct})); "
            "raise SystemExit(0 if g and not direct else 4)",
        ], timeout=15)
        if probe.returncode != 0:
            raise RuntimeError("lane network isolation proof failed")
        return json.loads(probe.stdout.strip().splitlines()[-1])

    def read_volume_file(self, volume: str, path: str) -> str:
        completed = run([
            "docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "-v", f"{volume}:/data:ro",
            "--entrypoint", "cat", IMAGE, f"/data/{path.lstrip('/')}",
        ])
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or f"missing volume artifact {path}")
        return completed.stdout

    def receipts(self) -> list[dict]:
        if not self.gateway_volume:
            return []
        try:
            text = self.read_volume_file(self.gateway_volume, "receipts.jsonl")
        except RuntimeError:
            return []
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def cleanup(self) -> None:
        removed = run(["docker", "rm", "-f", self.gateway])
        if removed.returncode not in (0, 1) and removed.stderr.strip():
            self.cleanup_errors.append(removed.stderr.strip())
        network = run(["docker", "network", "rm", self.network])
        if network.returncode not in (0, 1) and network.stderr.strip():
            self.cleanup_errors.append(network.stderr.strip())
        for volume in reversed(self.volumes):
            result = run(["docker", "volume", "rm", volume])
            if result.returncode != 0:
                self.cleanup_errors.append(result.stderr.strip() or f"failed to remove {volume}")
        for path in self.temp_files:
            path.unlink(missing_ok=True)
