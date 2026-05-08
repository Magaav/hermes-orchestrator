#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = PLUGIN_ROOT / "scripts" / "security_loop_run.py"

spec = importlib.util.spec_from_file_location("wasm_agent_security_loop_run", RUNNER_PATH)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


class SecurityLoopRunnerTest(unittest.TestCase):
    def test_attack_prompt_is_bounded_to_owned_defense(self) -> None:
        prompt = runner.task_prompt_attack(["auth", "bridge"], [{"route": "/health", "status": 200, "ok": True}])
        self.assertIn("bounded defensive audit", prompt)
        self.assertIn("owned Hermes/Colmeio surfaces only", prompt)
        self.assertIn("Authenticated platform context", prompt)
        self.assertIn("/health", prompt)
        self.assertIn("Do not scan third-party targets", prompt)
        self.assertIn("Do not", prompt)
        self.assertIn("DDoS", prompt)
        self.assertIn("hermes.security_loop.finding.v1", prompt)

    def test_failed_probe_becomes_dashboard_finding(self) -> None:
        probe = runner.ProbeResult(
            name="auth_failed",
            ok=False,
            status=200,
            surface="auth",
            category="auth-gate",
            summary="Protected route returned 200",
            evidence="GET /health -> 200",
            proposed_action="Require auth.",
        )
        finding = runner.finding_from_probe(probe, "run-1")
        self.assertEqual(finding["id"], "run-1-auth_failed")
        self.assertEqual(finding["source_node"], "wasm-agent-security-loop")
        self.assertEqual(finding["target_surface"], "auth")
        self.assertEqual(finding["proposed_action"], "Require auth.")

    def test_browser_disabled_satisfies_cross_origin_probe(self) -> None:
        calls: list[tuple[str, str, dict[str, str] | None]] = []

        def fake_read_http(method: str, url: str, body: dict | None = None, headers: dict[str, str] | None = None, timeout: float = 10.0):
            calls.append((method, url, headers))
            return 403, {"error": {"code": "browser_disabled"}}, '{"error":{"code":"browser_disabled"}}'

        old_read_http = runner.read_http
        old_cookie = runner.local_admin_cookie
        try:
            runner.read_http = fake_read_http
            runner.local_admin_cookie = lambda: "wa_session=test"
            probe = runner.browser_stream_origin_probe("https://wa.example.test")
        finally:
            runner.read_http = old_read_http
            runner.local_admin_cookie = old_cookie

        self.assertTrue(probe.ok)
        self.assertEqual(probe.status, 403)
        self.assertEqual(calls[0][2]["Origin"], "https://attacker.invalid")

    def test_run_record_writes_latest_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            payload = {
                "schema": "hermes.wasm_agent.security_loop.run.v1",
                "run_id": "security-run-test",
                "findings": [],
                "tasks": [],
                "errors": [],
            }
            runner.record_run(state_dir, payload)
            self.assertTrue((state_dir / "security-loop" / "runs" / "security-run-test.json").exists())
            self.assertTrue((state_dir / "security-loop" / "latest-run.json").exists())

    def test_task_response_json_findings_are_normalized(self) -> None:
        task = {
            "task_id": "task-1",
            "result": {
                "response": 'Audit complete.\n[{"target_surface":"auth","category":"gate","severity":"high","summary":"x"}]'
            },
        }
        findings = runner.findings_from_task(task, "run-1")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["id"], "run-1-hermes-attack-1")
        self.assertEqual(findings[0]["source_node"], "hermes-attack")
        self.assertEqual(findings[0]["task_id"], "task-1")

    def test_compact_task_keeps_prompt_out_of_run_summary(self) -> None:
        compact = runner.compact_task({"task_id": "task-1", "prompt": "x" * 300, "status": "running"})
        self.assertNotIn("prompt", compact)
        self.assertEqual(compact["prompt_length"], 300)
        self.assertLessEqual(len(compact["prompt_preview"]), 220)

    def test_node_runs_api_uses_explicit_wasm_agent_url_without_docker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_dir = Path(tmp) / "envs"
            env_dir.mkdir()
            (env_dir / "hermes-attack.env").write_text(
                "\n".join([
                    "API_SERVER_KEY=base-key",
                    "HERMES_WASM_AGENT_RUNS_API_HERMES_ATTACK_URL=http://10.0.0.2:8643",
                    "HERMES_WASM_AGENT_RUNS_API_HERMES_ATTACK_KEY=explicit-key",
                ]),
                encoding="utf-8",
            )

            config = runner.node_runs_api(Path(tmp), "hermes-attack")

            self.assertEqual(config["url"], "http://10.0.0.2:8643")
            self.assertEqual(config["key"], "explicit-key")

    def test_node_runs_api_defaults_orchestrator_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_dir = Path(tmp) / "envs"
            env_dir.mkdir()
            (env_dir / "orchestrator.env").write_text(
                "API_SERVER_HOST=127.0.0.1\nAPI_SERVER_KEY=orchestrator-key\n",
                encoding="utf-8",
            )

            config = runner.node_runs_api(Path(tmp), "orchestrator")

            self.assertEqual(config["url"], "http://127.0.0.1:8642")
            self.assertEqual(config["key"], "orchestrator-key")

    def test_running_task_statuses_include_native_queue_states(self) -> None:
        self.assertIn("queued", runner.RUNNING_TASK_STATUSES)
        self.assertIn("running", runner.RUNNING_TASK_STATUSES)
        self.assertNotIn("completed", runner.RUNNING_TASK_STATUSES)

    def test_value_summary_marks_clean_repeat_limit(self) -> None:
        summary = runner.value_summary(
            clean_streak_before=3,
            max_clean_repeat=3,
            token_delta=0,
            api_delta=0,
            finding_count=0,
            failed_probe_count=0,
            error_count=0,
            skipped=True,
        )
        self.assertEqual(summary["verdict"], "limit_reached")
        self.assertTrue(summary["launch_candidate"])

    def test_clean_repeat_streak_only_counts_matching_clean_runs(self) -> None:
        key = runner.run_key("all", "runs-api", ["auth", "bridge"])
        other_key = runner.run_key("all", "runs-api", ["auth"])
        runs = [
            {"run_key": key, "runner_status": "completed", "finding_count": 0, "failed_probe_count": 0, "error_count": 0},
            {"run_key": other_key, "runner_status": "completed", "finding_count": 0, "failed_probe_count": 0, "error_count": 0},
            {"run_key": key, "runner_status": "completed", "finding_count": 0, "failed_probe_count": 0, "error_count": 0},
        ]
        self.assertEqual(runner.clean_repeat_streak(runs, key), 2)


if __name__ == "__main__":
    unittest.main()
