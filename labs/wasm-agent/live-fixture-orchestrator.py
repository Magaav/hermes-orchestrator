#!/usr/bin/env python3
"""Run one SQL fixture through one verified adapter using the private model broker."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from safe_lab_host import IMAGE, ROOT, SafeLabHost, run
from private_evaluator.semantic_score import score_answer
from efficiency_policy import warnings_for
from fixture_outcomes import fixture_outcome
from trusted_host_lane import execute as execute_trusted_host

LAB = Path(__file__).resolve().parent
REGISTRY = LAB / "harness-adapters.json"
SOURCE_VOLUME = "wasm-agent-safe-lab-local-v11"
FIXTURE_VOLUME = "wasm-agent-safe-lab-output-v1"
ADJUDICATION_VOLUME = "wasm-agent-safe-lab-adjudication-v3"
ADJUDICATION_PATH = LAB / "staging/avatar-chat-adjudication-v3.sqlite3"
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{2,80}$")


def adapter_for(slot: str) -> tuple[dict, dict]:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    matches = [item for item in registry.get("adapters", []) if item.get("slot") == slot]
    if len(matches) != 1:
        raise RuntimeError("adapter slot must resolve exactly once")
    return registry["modelContract"], matches[0]


def report_path_for(explicit: str | None, slot: str, adapter_id: str = "") -> Path:
    if explicit:
        return (ROOT / explicit).resolve()
    owner = adapter_id if SAFE_ID.fullmatch(adapter_id) else slot
    return ROOT / "reports/context/latest" / f"live-fixture-{owner}-result.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", default="harness-03")
    parser.add_argument("--fixture-id", default="fx_d3154de08df6150be9c9")
    parser.add_argument("--report")
    parser.add_argument("--candidate-adapter", help="Host-only exact candidate projection JSON; does not promote the registry.")
    args = parser.parse_args()
    if not SAFE_ID.fullmatch(args.fixture_id) or not SAFE_ID.fullmatch(args.slot):
        raise SystemExit("unsafe slot or fixture id")
    report_path = report_path_for(args.report, args.slot)
    host = SafeLabHost("live-fixture")
    errors: list[str] = []
    benchmark_errors: list[str] = []
    task: dict = {}
    lane: dict = {}
    receipts: list[dict] = []
    network_evidence: dict = {}
    adapter: dict = {}
    model_contract: dict = {}
    semantic_score: dict = {}
    warnings: list[dict] = []
    candidate_identity: dict = {}
    answer = ""
    started = time.monotonic()
    try:
        model_contract, adapter = adapter_for(args.slot)
        report_path = report_path_for(args.report, args.slot, str(adapter.get("id") or ""))
        if args.candidate_adapter:
            candidate_path = (ROOT / args.candidate_adapter).resolve()
            if ROOT not in candidate_path.parents or not candidate_path.is_file():
                raise RuntimeError("candidate adapter projection is outside the workspace or missing")
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            if candidate.get("slot") != args.slot or candidate.get("id") != adapter.get("id"):
                raise RuntimeError("candidate adapter identity does not match the registered slot")
            adapter = candidate
            if isinstance(candidate.get("modelContract"), dict):
                model_contract = candidate["modelContract"]
            candidate_identity = {
                "projectionPath": str(candidate_path.relative_to(ROOT)),
                "projectionSha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
                "artifactSha256": str(candidate.get("adapterArtifactSha256") or ""),
                "candidateDigest": str(candidate.get("candidateDigest") or ""),
                "adapterVolume": str(candidate.get("adapterVolume") or ""),
            }
            if not candidate_identity["artifactSha256"] or candidate_identity["artifactSha256"] != candidate_identity["candidateDigest"]:
                raise RuntimeError("candidate projection lacks one exact artifact digest")
        if adapter.get("modelContractStatus") != "verified" or adapter.get("toolAuthorityStatus") != "verified":
            raise RuntimeError("adapter model/tool contract is not verified")
        execution_boundary = str(adapter.get("executionBoundary") or "safe_lab_container")
        if not isinstance(adapter.get("liveCommand"), list):
            raise RuntimeError("generic live command missing")
        if execution_boundary == "safe_lab_container":
            if not adapter.get("adapterVolume"):
                raise RuntimeError("adapter package volume missing")
            inspected = run(["docker", "volume", "inspect", str(adapter["adapterVolume"])])
            if inspected.returncode != 0:
                raise RuntimeError("adapter package volume missing")
        elif execution_boundary != "trusted_host":
            raise RuntimeError("unsupported adapter execution boundary")
        adjudication_inspected = run(["docker", "volume", "inspect", ADJUDICATION_VOLUME])
        if adjudication_inspected.returncode != 0 or not ADJUDICATION_PATH.is_file():
            raise RuntimeError("private adjudication overlay is missing")
        task_volume = host.create_volume("task")
        materialized = run([
            "docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--user", "10000:10000", "--pids-limit", "64",
            "--memory", "256m", "--cpus", "0.25", "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=32m",
            "-v", f"{SOURCE_VOLUME}:/source:ro", "-v", f"{FIXTURE_VOLUME}:/fixtures:ro",
            "-v", f"{ADJUDICATION_VOLUME}:/adjudication:ro",
            "-v", f"{task_volume}:/task",
            "--entrypoint", "python3", IMAGE, "/usr/local/bin/materialize-fixture-task",
            "--fixture-id", args.fixture_id, "--output", "/task/task.json",
        ], timeout=30)
        if materialized.returncode != 0:
            detail = (materialized.stderr.strip() or materialized.stdout.strip())[-1200:]
            raise RuntimeError(detail or "fixture task materialization failed")
        task = json.loads(host.read_volume_file(task_volume, "task.json"))
        if not (task.get("adjudication") or {}).get("executionAllowed"):
            raise RuntimeError("fixture adjudication does not allow execution")
        maximum = int((task.get("budgets") or {}).get("maxOutputTokensPerCall") or 1024)
        if execution_boundary == "trusted_host":
            lane, answer = execute_trusted_host(
                ROOT, adapter, task,
                timeout=int((task.get("budgets") or {}).get("wallClockSeconds") or 180) + 30,
            )
            network_evidence = {
                "executionBoundary": "trusted_host",
                "authentication": "chatgpt_cached_codex_session",
                "credentialExported": False,
            }
        else:
            workspace_volume = host.create_volume("work")
            result_volume = host.create_volume("result")
            host.start_gateway(
                max_output_tokens=maximum,
                max_provider_calls=int((task.get("budgets") or {}).get("maxProviderCalls") or 4),
                benchmark_scenario=False,
            )
            network_evidence = host.network_evidence()
            lane_env = host.env_file("lane", {
                "OPENAI_API_KEY": host.broker_token,
                "FRONTIER_ENDPOINT": host.endpoint(),
                "FRONTIER_MODEL": str(model_contract["model"]),
                "MODEL_CONTRACT_JSON": json.dumps(model_contract, separators=(",", ":")),
                "ADAPTER_CONFIG_JSON": json.dumps(adapter, separators=(",", ":")),
            })
            completed = run([
                "docker", "run", "--rm", "--network", host.network, "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--user", "10000:10000", "--pids-limit", "128",
                "--memory", "2g", "--cpus", "1", "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=128m",
                "--env-file", str(lane_env),
                "-v", f"{adapter['adapterVolume']}:/adapter:ro", "-v", f"{SOURCE_VOLUME}:/source:ro",
                "-v", f"{FIXTURE_VOLUME}:/fixtures:ro", "-v", f"{task_volume}:/task:ro",
                "-v", f"{workspace_volume}:/workspace", "-v", f"{result_volume}:/result",
                "--workdir", "/workspace", "--entrypoint", "python3", IMAGE, "/usr/local/bin/lane-runner",
                "--slot", args.slot, "--mode", "benchmark", "--execution", "live-proof",
                "--strategy", "evidence-first", "--task", "/task/task.json",
            ], timeout=int((task.get("budgets") or {}).get("wallClockSeconds") or 180) + 30)
            if completed.returncode != 0:
                errors.append(f"lane exited {completed.returncode}: {completed.stderr[-1000:]}")
            try:
                lane = json.loads(host.read_volume_file(result_volume, "result.json"))
                answer = host.read_volume_file(result_volume, "answer.txt") if lane.get("readinessCandidatePassed") else ""
            except RuntimeError as exc:
                errors.append(str(exc))
        adjudication = task.get("adjudication") if isinstance(task.get("adjudication"), dict) else {}
        candidate_answer_available = lane.get("readinessCandidatePassed") is True
        if adjudication.get("semanticCorrectness") == "contract_adjudicated" and candidate_answer_available:
            local_overlay_sha = hashlib.sha256(ADJUDICATION_PATH.read_bytes()).hexdigest()
            if local_overlay_sha != adjudication.get("overlaySha256"):
                errors.append("trusted scorer overlay differs from materialized task overlay")
            else:
                try:
                    semantic_score = score_answer(
                        ADJUDICATION_PATH,
                        args.fixture_id,
                        answer,
                        baseline_model=str(task.get("model") or ""),
                        runtime_model=str(adapter.get("runtimeModel") or model_contract.get("model") or ""),
                    )
                    if semantic_score.get("contractSha256") != adjudication.get("expectedContractSha256"):
                        errors.append("semantic scorer contract differs from materialized task")
                    elif semantic_score.get("passed") is not True:
                        benchmark_errors.append("answer failed the private semantic contract")
                except RuntimeError as exc:
                    errors.append(str(exc))
        receipts = host.receipts()
        if not candidate_answer_available:
            errors.append("lane did not produce a bounded answer")
        if (lane.get("task") or {}).get("taskDigest") != task.get("taskDigest"):
            errors.append("lane task digest differs from materialized SQL fixture")
        successful = [item for item in receipts if item.get("upstreamCalled") is True]
        if execution_boundary == "safe_lab_container":
            if not successful or any(
                item.get("returnedModel") != "frank/GLM-5.2"
                or item.get("status") != 200
                or item.get("contractMatch") is not True
                for item in successful
            ):
                errors.append("gateway did not prove exact GLM-5.2 for every upstream call")
            if len(successful) > int((task.get("budgets") or {}).get("maxProviderCalls") or 0):
                errors.append("fixture provider-call budget exceeded")
        grounded_class = str((task.get("fixture") or {}).get("requestClass") or "") in {
            "source_investigation", "runtime_inspection",
        }
        fresh_tool_evidence = (
            int(lane.get("toolCallCount") or 0) > 0 if execution_boundary == "trusted_host"
            else any(int(item.get("toolCallCount") or 0) > 0 for item in successful)
        )
        if grounded_class and not fresh_tool_evidence:
            benchmark_errors.append("grounded fixture completed without fresh tool evidence")
        if any(int(item.get("duplicateOrdinal") or 0) > 2 for item in receipts):
            errors.append("identical request duplicate budget exceeded")
        if any(item.get("duplicateClass") == "waste_blocked" for item in receipts):
            errors.append("adapter attempted a third identical request")
        if any(item.get("duplicateClass") == "provider_budget_blocked" for item in receipts):
            errors.append("adapter exhausted the provider-call budget before completing")
        if execution_boundary == "safe_lab_container":
            warnings.extend(warnings_for(task, receipts))
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
    finally:
        host.cleanup()
        errors.extend(host.cleanup_errors)
    ranking_allowed = (
        bool((task.get("adjudication") or {}).get("rankingAllowed"))
        and bool(lane.get("comparable")) and semantic_score.get("passed") is True
    )
    semantics = fixture_outcome(errors, benchmark_errors, semantic_score, lane, ranking_allowed)
    result = {
        "schema": "wasm-agent.safe-lab.live-fixture-result.v1",
        **semantics,
        "checkedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "durationMs": round((time.monotonic() - started) * 1000),
        "slot": args.slot,
        "adapter": adapter.get("id"),
        "adapterVersion": adapter.get("adapterVersion"),
        "adapterArtifactSha256": adapter.get("adapterArtifactSha256"),
        "adapterVolume": adapter.get("adapterVolume"),
        "candidateIdentity": candidate_identity,
        "model": adapter.get("runtimeModel") or model_contract.get("model"),
        "task": {key: value for key, value in task.items() if key != "prompt"},
        "lane": lane,
        "gatewayReceipts": receipts,
        "networkEvidence": network_evidence,
        "providerCredentialInLane": False,
        "technicalReadinessPassed": not errors,
        "semanticScore": semantic_score,
        "semanticEvaluationPassed": semantic_score.get("passed") if semantic_score else None,
        "rankingAllowed": ranking_allowed,
        "cleanupComplete": not host.cleanup_errors,
        "errors": errors,
        "benchmarkErrors": benchmark_errors,
        "warnings": warnings,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
