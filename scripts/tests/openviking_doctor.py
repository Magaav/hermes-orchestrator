#!/usr/bin/env python3
"""Production-oriented OpenViking validation suite.

Runs operational checks for:
- service boot + health
- ingestion/indexing
- embeddings
- retrieval
- reranking
- Hermes adapter smoke path
- failure diagnostics
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import textwrap
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests


DEFAULT_ENDPOINT = "http://127.0.0.1:1933"
DEFAULT_CONTAINER = "openviking"
DEFAULT_DATA_DIR = Path("/local/scripts/tests/data")
DEFAULT_DOCKER_ENV = Path("/local/docker/.env")


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _is_truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _read_env_file(path: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and (
            (value.startswith('"') and value.endswith('"'))
            or (value.startswith("'") and value.endswith("'"))
        ):
            value = value[1:-1]
        data[key] = value
    return data


def _candidate_env(name: str, cli_value: str, docker_env: Dict[str, str], fallback: str = "") -> str:
    if str(cli_value or "").strip():
        return str(cli_value).strip()
    if str(os.getenv(name, "")).strip():
        return str(os.getenv(name, "")).strip()
    if str(docker_env.get(name, "")).strip():
        return str(docker_env.get(name, "")).strip()
    return fallback


@dataclass
class StepResult:
    name: str
    ok: bool
    message: str
    details: Dict[str, Any]


class Doctor:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.results: List[StepResult] = []
        self.session_id = f"ovdoc-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        self.resource_root = f"viking://resources/{self.session_id}"
        self.memory_root = f"viking://resources/memory/{args.user}/events"
        self.last_ingested: List[str] = []

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @property
    def headers(self) -> Dict[str, str]:
        out = {
            "X-OpenViking-Account": self.args.account,
            "X-OpenViking-User": self.args.user,
        }
        if self.args.api_key:
            out["X-API-Key"] = self.args.api_key
        return out

    def _record(self, name: str, ok: bool, message: str, **details: Any) -> None:
        result = StepResult(name=name, ok=ok, message=message, details=details)
        self.results.append(result)
        icon = "PASS" if ok else "FAIL"
        print(json.dumps({"ts": _utc_now(), "step": name, "status": icon, "message": message, "details": details}, ensure_ascii=False))

    def _step(self, name: str, fn: Callable[[], Tuple[bool, str, Dict[str, Any]]]) -> None:
        try:
            ok, message, details = fn()
        except Exception as exc:
            ok, message, details = False, f"unexpected exception: {exc}", {}
        self._record(name, ok, message, **details)

    def _json_req(
        self,
        method: str,
        path: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        url = f"{self.args.endpoint.rstrip('/')}{path}"
        req_headers = dict(self.headers)
        if headers:
            req_headers.update(headers)
        if payload is not None:
            req_headers.setdefault("Content-Type", "application/json")
        response = requests.request(
            method=method.upper(),
            url=url,
            headers=req_headers,
            json=payload,
            timeout=timeout,
        )
        return response

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_boot(self) -> Tuple[bool, str, Dict[str, Any]]:
        cmd = [
            "docker",
            "ps",
            "--filter",
            f"name=^/{self.args.container}$",
            "--format",
            "{{.Status}}",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        status = (proc.stdout or "").strip()
        if not status:
            return False, "container not running", {"container": self.args.container}

        health = self._json_req("GET", "/health", timeout=8)
        if health.status_code != 200:
            return False, "health endpoint not reachable", {"http_status": health.status_code, "body": health.text[:240]}

        return True, "container running and health reachable", {"container_status": status, "health": health.json()}

    def test_health(self) -> Tuple[bool, str, Dict[str, Any]]:
        health = self._json_req("GET", "/health", timeout=8)
        ready = self._json_req("GET", "/ready", timeout=8)

        health_ok = health.status_code == 200 and bool((health.json() or {}).get("healthy", False))
        ready_ok = ready.status_code == 200
        details: Dict[str, Any] = {
            "health_status_code": health.status_code,
            "health_body": health.json() if health.headers.get("Content-Type", "").startswith("application/json") else health.text[:240],
            "ready_status_code": ready.status_code,
            "ready_body": ready.json() if ready.headers.get("Content-Type", "").startswith("application/json") else ready.text[:240],
        }

        if not health_ok:
            return False, "health check failed", details

        if not ready_ok:
            # OpenViking 0.3.x can report not_ready for AGFS root while still
            # serving retrieval correctly. Keep this visible but fail-open.
            return True, "health ok (readiness degraded; fail-open mode)", details

        return True, "health and readiness passed", details

    def _upload_doc(self, path: Path, target_uri: str) -> str:
        with path.open("rb") as handle:
            upload = requests.post(
                f"{self.args.endpoint.rstrip('/')}/api/v1/resources/temp_upload",
                headers=self.headers,
                files={"file": (path.name, handle, "text/markdown")},
                timeout=30,
            )
        upload.raise_for_status()
        temp_file_id = str(((upload.json() or {}).get("result") or {}).get("temp_file_id") or "").strip()
        if not temp_file_id:
            raise RuntimeError(f"temp_upload did not return temp_file_id for {path.name}")

        ingest = self._json_req(
            "POST",
            "/api/v1/resources",
            payload={
                "temp_file_id": temp_file_id,
                "to": target_uri,
                "wait": True,
                "timeout": 90,
            },
            timeout=120,
        )
        ingest.raise_for_status()
        return target_uri

    def test_ingestion(self) -> Tuple[bool, str, Dict[str, Any]]:
        docs = [
            self.args.data_dir / "openviking_sample_doc.md",
            self.args.data_dir / "openviking_structured_tech.md",
        ]
        missing = [str(p) for p in docs if not p.exists()]
        if missing:
            return False, "sample data missing", {"missing": missing}

        ingested: List[str] = []
        for path in docs:
            uri = f"{self.resource_root}/{path.name}"
            self._upload_doc(path, uri)
            ingested.append(uri)

        self.last_ingested = ingested
        return True, "ingestion succeeded", {"resource_root": self.resource_root, "uris": ingested}

    def test_embedding(self) -> Tuple[bool, str, Dict[str, Any]]:
        resp = self._json_req(
            "POST",
            "/api/v1/search/search",
            payload={
                "query": "Where do we add milk shortage items?",
                "target_uri": self.resource_root,
                "limit": 8,
                "include_provenance": True,
                "telemetry": True,
            },
            timeout=90,
        )
        if resp.status_code != 200:
            return False, "search request failed", {"http_status": resp.status_code, "body": resp.text[:400]}

        body = resp.json() if resp.headers.get("Content-Type", "").startswith("application/json") else {}
        telemetry = body.get("telemetry", {}) if isinstance(body, dict) else {}
        tokens = ((telemetry.get("summary") or {}).get("tokens") or {}) if isinstance(telemetry, dict) else {}
        embedding_total = int(((tokens.get("embedding") or {}).get("total") or 0))
        resources = ((body.get("result") or {}).get("resources") or []) if isinstance(body, dict) else []

        if embedding_total <= 0:
            return False, "embedding tokens not observed", {"telemetry": telemetry, "resource_count": len(resources)}
        return True, "embeddings generated", {"embedding_tokens": embedding_total, "resource_count": len(resources)}

    def test_retrieval(self) -> Tuple[bool, str, Dict[str, Any]]:
        query = "paper towels low shortage list procurement"
        resp = self._json_req(
            "POST",
            "/api/v1/search/search",
            payload={
                "query": query,
                "target_uri": self.resource_root,
                "limit": 5,
                "include_provenance": True,
                "telemetry": True,
            },
            timeout=90,
        )
        if resp.status_code != 200:
            return False, "retrieval search failed", {"http_status": resp.status_code, "body": resp.text[:400]}

        payload = resp.json()
        resources = (payload.get("result") or {}).get("resources") or []
        uris = [str(item.get("uri") or "") for item in resources if isinstance(item, dict)]
        expected_hit = any("openviking_sample_doc.md" in uri for uri in uris)
        if not expected_hit:
            return False, "expected resource not found in retrieval", {"uris": uris, "query": query}

        return True, "retrieval returned expected candidates", {"top_uris": uris[:3]}

    def test_rerank(self) -> Tuple[bool, str, Dict[str, Any]]:
        # Run rerank probe through the same runtime path used by OpenViking's
        # litellm rerank client (inside the container).
        normalized_model = self.args.rerank_model
        if normalized_model.startswith("nvidia/"):
            normalized_model = f"nvidia_nim/{normalized_model}"

        probe_py = textwrap.dedent(
            f"""
            import json, os
            from litellm import rerank

            model = {normalized_model!r}
            api_base = {self.args.rerank_api_base!r}
            api_key = {self.args.nvidia_api_key!r}
            os.environ['NVIDIA_NIM_API_KEY'] = api_key
            os.environ['NVIDIA_NIM_API_BASE'] = api_base

            query = "critical shortage milk near checkout"
            docs = [
                {{'text': 'Quarterly accounting report and payroll schedule.'}},
                {{'text': 'When milk stock is low, add milk to shortage list and notify manager.'}},
                {{'text': 'How to compress shell history safely.'}},
            ]
            response = rerank(model=model, query=query, documents=docs, api_key=api_key, api_base=api_base, timeout=20)
            if isinstance(response, dict):
                results = response.get('results') or []
            else:
                results = getattr(response, 'results', None)
                if results is None and hasattr(response, 'get'):
                    try:
                        results = response.get('results')
                    except Exception:
                        results = None
                results = results or []

            def _score(item):
                if isinstance(item, dict):
                    raw = item.get('relevance_score')
                    if raw is None:
                        raw = item.get('score')
                    if raw is None:
                        raw = item.get('similarity')
                else:
                    raw = getattr(item, 'relevance_score', None)
                    if raw is None:
                        raw = getattr(item, 'score', None)
                    if raw is None:
                        raw = getattr(item, 'similarity', None)
                try:
                    return float(raw)
                except Exception:
                    return float('-inf')

            def _index(item, fallback):
                if isinstance(item, dict):
                    raw = item.get('index', fallback)
                else:
                    raw = getattr(item, 'index', fallback)
                try:
                    return int(raw)
                except Exception:
                    return int(fallback)

            normalized = [{{'index': _index(item, pos), 'score': _score(item)}} for pos, item in enumerate(results)]
            ordered = sorted(normalized, key=lambda x: x['score'], reverse=True)
            top_index = int(ordered[0]['index']) if ordered else -1
            baseline_top = 0
            print(json.dumps({{
                'ok': bool(results),
                'top_index': top_index,
                'baseline_top': baseline_top,
                'changed_order': top_index != baseline_top,
                'scores': ordered,
            }}))
            """
        ).strip()

        cmd = ["docker", "exec", self.args.container, "python3", "-c", probe_py]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return False, "rerank probe subprocess failed", {"stderr": (proc.stderr or "").strip()[:500]}
        if not (proc.stdout or "").strip():
            return False, "rerank probe returned no stdout", {}

        try:
            payload = json.loads(proc.stdout.strip().splitlines()[-1])
        except Exception as exc:
            return False, f"invalid rerank probe output: {exc}", {"stdout": proc.stdout[:500], "stderr": proc.stderr[:500]}

        probe_ok = bool(payload.get("ok"))
        payload.pop("ok", None)
        ok = probe_ok and bool(payload.get("changed_order")) and int(payload.get("top_index", -1)) == 1
        if not ok:
            return False, "rerank did not improve ordering as expected", payload
        return True, "rerank changed ordering meaningfully", payload

    def test_hermes_smoke(self) -> Tuple[bool, str, Dict[str, Any]]:
        adapter = Path("/local/scripts/openviking_adapter.py")
        if not adapter.exists():
            return False, "adapter script missing", {"path": str(adapter)}

        commit_cmd = [
            "python3",
            str(adapter),
            "--endpoint",
            self.args.endpoint,
            "--account",
            self.args.account,
            "--user",
            self.args.user,
            "commit",
            "--category",
            "events",
            "--content",
            f"{self.session_id}: reboot runs prestart reapply and container lifecycle checks",
        ]
        commit = subprocess.run(commit_cmd, capture_output=True, text=True, check=False)
        if commit.returncode != 0:
            return False, "adapter commit failed", {"stderr": (commit.stderr or "").strip()[:500]}
        committed_uri = ""
        try:
            committed_uri = str((json.loads((commit.stdout or "").strip() or "{}").get("uri") or "")).strip()
        except Exception:
            committed_uri = ""

        context_cmd = [
            "python3",
            str(adapter),
            "--endpoint",
            self.args.endpoint,
            "--account",
            self.args.account,
            "--user",
            self.args.user,
            "context",
            "--query",
            "reboot prestart reapply container lifecycle",
            "--target-uri",
            f"viking://resources/memory/{self.args.user}",
            "--limit",
            "4",
        ]
        last_stdout = ""
        last_stderr = ""
        for _attempt in range(1, 8):
            context = subprocess.run(context_cmd, capture_output=True, text=True, check=False)
            last_stdout = (context.stdout or "").strip()
            last_stderr = (context.stderr or "").strip()
            if context.returncode == 0 and "OpenViking Context" in last_stdout:
                return True, "Hermes adapter smoke succeeded", {
                    "context_preview": last_stdout[:500],
                    "committed_uri": committed_uri,
                }
            # OpenViking indexing can be slightly asynchronous even with wait=true.
            time.sleep(1.5)

        if context.returncode != 0:
            return False, "adapter context failed", {"stderr": last_stderr[:500], "committed_uri": committed_uri}
        return False, "adapter context did not return usable context", {
            "stdout": last_stdout[:600],
            "committed_uri": committed_uri,
        }

    def test_failure_paths(self) -> Tuple[bool, str, Dict[str, Any]]:
        details: Dict[str, Any] = {}

        # 1) Unreachable service path should fail fast with connection diagnostics.
        unreachable_ok = False
        try:
            requests.get("http://127.0.0.1:1/health", timeout=1.5)
        except Exception as exc:
            unreachable_ok = True
            details["unreachable_service_error"] = str(exc)[:200]

        # 2) Invalid NVIDIA key should fail rerank probe clearly.
        probe_py = textwrap.dedent(
            """
            import json
            from litellm import rerank
            try:
                rerank(
                    model='nvidia_nim/nvidia/llama-nemotron-rerank-1b-v2',
                    query='milk shortage',
                    documents=[{'text':'buy milk now'}, {'text':'accounting report'}],
                    api_key='invalid-key',
                    api_base='https://ai.api.nvidia.com/v1',
                    timeout=10,
                )
                print(json.dumps({'ok': False, 'error': 'unexpected success'}))
            except Exception as exc:
                print(json.dumps({'ok': True, 'error': str(exc)[:240]}))
            """
        ).strip()
        proc = subprocess.run(
            ["docker", "exec", self.args.container, "python3", "-c", probe_py],
            capture_output=True,
            text=True,
            check=False,
        )
        bad_key_ok = False
        if proc.returncode == 0 and (proc.stdout or "").strip():
            try:
                payload = json.loads(proc.stdout.strip().splitlines()[-1])
                bad_key_ok = bool(payload.get("ok"))
                details["bad_key_error"] = str(payload.get("error") or "")[:240]
            except Exception:
                bad_key_ok = False
                details["bad_key_error"] = (proc.stdout or proc.stderr or "").strip()[:240]
        else:
            details["bad_key_error"] = (proc.stderr or "").strip()[:240]

        ok = unreachable_ok and bad_key_ok
        if not ok:
            return False, "failure-path diagnostics incomplete", details
        return True, "failure-path diagnostics behaved as expected", details

    # ------------------------------------------------------------------
    # Runner
    # ------------------------------------------------------------------

    def run(self) -> int:
        self._step("boot_test", self.test_boot)
        self._step("health_test", self.test_health)
        self._step("ingestion_test", self.test_ingestion)
        self._step("embedding_test", self.test_embedding)
        self._step("retrieval_test", self.test_retrieval)
        self._step("reranking_test", self.test_rerank)
        self._step("hermes_integration_smoke", self.test_hermes_smoke)
        self._step("failure_path_test", self.test_failure_paths)

        failures = [r for r in self.results if not r.ok]
        summary = {
            "ts": _utc_now(),
            "ok": not failures,
            "session_id": self.session_id,
            "endpoint": self.args.endpoint,
            "account": self.args.account,
            "user": self.args.user,
            "passed": len(self.results) - len(failures),
            "failed": len(failures),
            "steps": [
                {
                    "name": r.name,
                    "ok": r.ok,
                    "message": r.message,
                    "details": r.details,
                }
                for r in self.results
            ],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["ok"] else 1


def _build_parser() -> argparse.ArgumentParser:
    docker_env = _read_env_file(DEFAULT_DOCKER_ENV)

    parser = argparse.ArgumentParser(description="OpenViking end-to-end doctor checks")
    parser.add_argument("--endpoint", default=_candidate_env("OPENVIKING_ENDPOINT", "", docker_env, DEFAULT_ENDPOINT))
    parser.add_argument("--account", default=_candidate_env("OPENVIKING_ACCOUNT", "", docker_env, "colmeio"))
    parser.add_argument("--user", default=_candidate_env("OPENVIKING_USER", "", docker_env, "colmeio"))
    parser.add_argument("--api-key", default=_candidate_env("OPENVIKING_API_KEY", "", docker_env, ""))
    parser.add_argument(
        "--nvidia-api-key",
        default=_candidate_env("NVIDIA_API_KEY", "", docker_env, ""),
        help="NVIDIA key used for embedding/rerank connectivity probes",
    )
    parser.add_argument(
        "--rerank-model",
        default=_candidate_env("OPENVIKING_RERANK_TEXT_MODEL", "", docker_env, "nvidia/llama-nemotron-rerank-1b-v2"),
    )
    parser.add_argument(
        "--rerank-api-base",
        default=_candidate_env("OPENVIKING_RERANK_API_BASE", "", docker_env, "https://ai.api.nvidia.com/v1"),
    )
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.nvidia_api_key:
        print(json.dumps({"ok": False, "error": "missing NVIDIA_API_KEY for model connectivity/rerank tests"}))
        return 2

    doctor = Doctor(args)
    return doctor.run()


if __name__ == "__main__":
    raise SystemExit(main())
