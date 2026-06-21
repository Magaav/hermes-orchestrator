from __future__ import annotations

import os
import json
import subprocess
import tempfile
from pathlib import Path
import unittest


HORC = Path(__file__).resolve().parents[1] / "horc.sh"


class AndroidBuildModeTests(unittest.TestCase):
    def make_root(self, aapt2_body: str) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        tmp = tempfile.TemporaryDirectory(prefix="horc-android-build-mode-")
        root = Path(tmp.name)
        android = root / "native" / "android"
        (android / "app").mkdir(parents=True)
        (android / "scripts").mkdir()
        (android / "app" / "build.gradle").write_text("// test\n", encoding="utf-8")
        (android / "scripts" / "release-android.js").write_text("// test\n", encoding="utf-8")
        gradle = android / ".gradle-dist" / "gradle-8.9" / "bin" / "gradle"
        gradle.parent.mkdir(parents=True)
        gradle.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        os.chmod(gradle, 0o755)
        aapt2 = android / ".android-sdk" / "build-tools" / "35.0.0" / "aapt2"
        aapt2.parent.mkdir(parents=True)
        aapt2.write_text(aapt2_body, encoding="utf-8")
        os.chmod(aapt2, 0o755)
        return tmp, root, android

    def make_bin(self, root: Path, docker_body: str | None = None, node_body: str | None = None) -> Path:
        bin_dir = root / "bin"
        bin_dir.mkdir(exist_ok=True)
        java = bin_dir / "java"
        java.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        os.chmod(java, 0o755)
        node = bin_dir / "node"
        node.write_text(node_body or "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        os.chmod(node, 0o755)
        if docker_body is not None:
            docker = bin_dir / "docker"
            docker.write_text(docker_body, encoding="utf-8")
            os.chmod(docker, 0o755)
        return bin_dir

    def run_horc(self, root: Path, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        merged = os.environ.copy()
        merged.update(env)
        merged["HERMES_ORCHESTRATOR_ROOT"] = str(root)
        merged["HERMES_CLONE_MANAGER_SCRIPT"] = str(root / "clone_manager.py")
        (root / "clone_manager.py").write_text("# test stub\n", encoding="utf-8")
        return subprocess.run(
            ["bash", str(HORC), *args],
            cwd=str(root),
            env=merged,
            check=False,
            text=True,
            capture_output=True,
        )

    def test_arm_with_broken_aapt2_auto_selects_docker(self) -> None:
        aapt2 = "#!/usr/bin/env bash\necho \"qemu-x86_64: Could not open '/lib64/ld-linux-x86-64.so.2'\" >&2\nexit 255\n"
        made = self.make_root(aapt2)
        tmp, root, _android = made
        try:
            bin_dir = self.make_bin(root)
            result = self.run_horc(
                root,
                ["build", "doctor"],
                {
                    "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                    "HORC_TEST_HOST_KERNEL": "Linux",
                    "HORC_TEST_HOST_MACHINE": "aarch64",
                    "HORC_ANDROID_BUILD_MODE": "auto",
                },
            )
        finally:
            tmp.cleanup()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Android selected build mode: docker", result.stdout)
        self.assertIn("Android AAPT2 runnable: no", result.stdout)
        self.assertIn("/lib64/ld-linux-x86-64.so.2", result.stdout)

    def test_x86_with_runnable_aapt2_auto_selects_local(self) -> None:
        aapt2 = "#!/usr/bin/env bash\necho 'Android Asset Packaging Tool (aapt) 2.0'\n"
        made = self.make_root(aapt2)
        tmp, root, _android = made
        try:
            bin_dir = self.make_bin(root)
            result = self.run_horc(
                root,
                ["build", "doctor"],
                {
                    "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                    "HORC_TEST_HOST_KERNEL": "Linux",
                    "HORC_TEST_HOST_MACHINE": "x86_64",
                    "HORC_ANDROID_BUILD_MODE": "auto",
                },
            )
        finally:
            tmp.cleanup()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Android selected build mode: local", result.stdout)
        self.assertIn("Android AAPT2 runnable: yes", result.stdout)

    def test_forced_local_with_broken_aapt2_fails_clearly(self) -> None:
        aapt2 = "#!/usr/bin/env bash\necho 'Exec format error' >&2\nexit 126\n"
        made = self.make_root(aapt2)
        tmp, root, _android = made
        try:
            android = made[2]
            bin_dir = self.make_bin(root)
            result = self.run_horc(
                root,
                ["build", "android"],
                {
                    "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                    "HERMES_WASM_AGENT_ANDROID_ROOT": str(android),
                    "HORC_TEST_HOST_KERNEL": "Linux",
                    "HORC_TEST_HOST_MACHINE": "aarch64",
                    "HORC_ANDROID_BUILD_MODE": "local",
                },
            )
        finally:
            tmp.cleanup()

        self.assertEqual(result.returncode, 2)
        combined = result.stdout + result.stderr
        self.assertIn("selected mode local", combined)
        self.assertIn("AAPT2 cannot execute", combined)
        self.assertIn("Exec format error", combined)
        self.assertIn("HORC_ANDROID_BUILD_MODE=docker", combined)

    def test_forced_docker_with_missing_amd64_binfmt_prints_remediation(self) -> None:
        aapt2 = "#!/usr/bin/env bash\necho 'Android Asset Packaging Tool (aapt) 2.0'\n"
        docker = """#!/usr/bin/env bash
if [[ "$1" == "info" ]]; then exit 0; fi
if [[ "$1" == "run" ]]; then
  echo "exec /bin/uname: exec format error" >&2
  exit 1
fi
exit 0
"""
        made = self.make_root(aapt2)
        tmp, root, _android = made
        try:
            android = made[2]
            bin_dir = self.make_bin(root, docker)
            result = self.run_horc(
                root,
                ["build", "android"],
                {
                    "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                    "HERMES_WASM_AGENT_ANDROID_ROOT": str(android),
                    "HORC_TEST_HOST_KERNEL": "Linux",
                    "HORC_TEST_HOST_MACHINE": "aarch64",
                    "HORC_ANDROID_BUILD_MODE": "docker",
                    "HORC_NO_AUTO_INSTALL_BINFMT": "1",
                },
            )
        finally:
            tmp.cleanup()

        self.assertEqual(result.returncode, 2)
        combined = result.stdout + result.stderr
        self.assertIn("selected mode docker", combined)
        self.assertIn("linux/amd64 containers cannot execute", combined)
        self.assertIn("sudo docker run --privileged --rm tonistiigi/binfmt --install amd64", combined)

    def test_android_build_clears_stale_identity_by_default(self) -> None:
        aapt2 = "#!/usr/bin/env bash\necho 'Android Asset Packaging Tool (aapt) 2.0'\n"
        node = """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "scripts/release-android.js" ]]; then
  {
    echo "build_id=${WASM_AGENT_ANDROID_BUILD_ID-}"
    echo "version_code=${WASM_AGENT_ANDROID_VERSION_CODE-}"
    echo "generated_at=${WASM_AGENT_ANDROID_BUILD_GENERATED_AT-}"
  } > "${HORC_TEST_NODE_LOG}"
  mkdir -p release
  printf 'apk' > release/WASM-Agent-arm64.apk
  printf 'apk' > release/WASM-Agent-universal.apk
fi
"""
        made = self.make_root(aapt2)
        tmp, root, android = made
        try:
            log_path = root / "node-env.log"
            bin_dir = self.make_bin(root, node_body=node)
            result = self.run_horc(
                root,
                ["build", "android"],
                {
                    "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                    "HERMES_WASM_AGENT_ANDROID_ROOT": str(android),
                    "HORC_TEST_HOST_KERNEL": "Linux",
                    "HORC_TEST_HOST_MACHINE": "x86_64",
                    "HORC_ANDROID_BUILD_MODE": "local",
                    "HORC_GENERATE_NATIVE_RELEASE_FEED": "0",
                    "HORC_TEST_NODE_LOG": str(log_path),
                    "WASM_AGENT_ANDROID_BUILD_ID": "android-universal-stale",
                    "WASM_AGENT_ANDROID_VERSION_CODE": "123",
                    "WASM_AGENT_ANDROID_BUILD_GENERATED_AT": "stale",
                },
            )
            log = log_path.read_text(encoding="utf-8")
        finally:
            tmp.cleanup()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("forcing fresh Android build identity", result.stdout)
        self.assertIn("build_id=\n", log)
        self.assertIn("version_code=\n", log)
        self.assertIn("generated_at=\n", log)

    def test_android_fast_uses_gradle_without_release_promotion(self) -> None:
        aapt2 = "#!/usr/bin/env bash\necho 'Android Asset Packaging Tool (aapt) 2.0'\n"
        made = self.make_root(aapt2)
        tmp, root, android = made
        try:
            gradle = android / ".gradle-dist" / "gradle-8.9" / "bin" / "gradle"
            gradle.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$@\" > \"${HORC_TEST_GRADLE_LOG}\"\n"
                "mkdir -p app/build/outputs/apk/debug\n"
                "printf apk > app/build/outputs/apk/debug/app-debug.apk\n",
                encoding="utf-8",
            )
            os.chmod(gradle, 0o755)
            log_path = root / "gradle-args.log"
            node_log = root / "node-env.log"
            bin_dir = self.make_bin(root, node_body="#!/usr/bin/env bash\necho node-called > \"${HORC_TEST_NODE_LOG}\"\nexit 9\n")
            result = self.run_horc(
                root,
                ["build", "android-fast"],
                {
                    "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                    "HERMES_WASM_AGENT_ANDROID_ROOT": str(android),
                    "HORC_TEST_HOST_KERNEL": "Linux",
                    "HORC_TEST_HOST_MACHINE": "x86_64",
                    "HORC_ANDROID_BUILD_MODE": "local",
                    "HORC_TEST_GRADLE_LOG": str(log_path),
                    "HORC_TEST_NODE_LOG": str(node_log),
                },
            )
            log = log_path.read_text(encoding="utf-8")
            benchmark_log = root / "reports" / "build" / "android" / "build-benchmarks.jsonl"
            benchmark = json.loads(benchmark_log.read_text(encoding="utf-8").splitlines()[-1])
        finally:
            tmp.cleanup()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("selected mode local", result.stdout)
        self.assertIn(":app:assembleDebug", log)
        self.assertIn("--build-cache", log)
        self.assertIn("debug build only; no release feed", result.stdout)
        self.assertEqual(benchmark["lane"], "android-fast")
        self.assertTrue(benchmark["ok"])
        self.assertGreaterEqual(benchmark["durationMs"], 0)
        self.assertFalse(node_log.exists(), "android-fast must not invoke release-android.js through node")

    def test_windows_fast_runs_local_npm_tasks_without_installer_release(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="horc-windows-fast-")
        root = Path(tmp.name)
        windows_src = root / "native" / "windows" / "src"
        windows_src.mkdir(parents=True)
        (windows_src / "package.json").write_text('{"scripts":{}}\n', encoding="utf-8")
        (windows_src / "node_modules" / ".bin").mkdir(parents=True)
        for tool in ("electron-builder", "asar"):
            path = windows_src / "node_modules" / ".bin" / tool
            path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            os.chmod(path, 0o755)
        try:
            log_path = root / "npm-tasks.log"
            bin_dir = root / "bin"
            bin_dir.mkdir()
            npm = bin_dir / "npm"
            npm.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"${1:-}\" == \"run\" ]]; then\n"
                "  echo \"${2:-}\" >> \"${HORC_TEST_NPM_TASK_LOG}\"\n"
                "  if [[ \"${2:-}\" == \"pack:win:x64\" ]]; then\n"
                "    mkdir -p ../release/win-unpacked/resources\n"
                "    printf app > ../release/win-unpacked/WASM\\ Agent.exe\n"
                "  fi\n"
                "  exit 0\n"
                "fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            os.chmod(npm, 0o755)
            for tool in ("node", "npx"):
                stub = bin_dir / tool
                stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
                os.chmod(stub, 0o755)

            result = self.run_horc(
                root,
                ["build", "win-fast"],
                {
                    "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                    "HORC_TEST_HOST_KERNEL": "Linux",
                    "HORC_TEST_HOST_MACHINE": "aarch64",
                    "HORC_TEST_NPM_TASK_LOG": str(log_path),
                    "HORC_WIN_FAST_TASKS": "test:windows-hot-ops pack:win:x64",
                    "HORC_GENERATE_NATIVE_RELEASE_FEED": "1",
                },
            )
            tasks = log_path.read_text(encoding="utf-8").splitlines()
            benchmark_log = root / "reports" / "build" / "windows" / "build-benchmarks.jsonl"
            benchmark = json.loads(benchmark_log.read_text(encoding="utf-8").splitlines()[-1])
        finally:
            tmp.cleanup()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("selected mode local-node", result.stdout)
        self.assertIn("source/package checks only; no NSIS installer", result.stdout)
        self.assertIn("skipping Wine rcedit on Linux ARM64", result.stdout)
        self.assertNotIn("generating native release feed", result.stdout)
        self.assertEqual(tasks, ["test:windows-hot-ops", "pack:win:x64"])
        self.assertEqual(benchmark["lane"], "win-fast")
        self.assertTrue(benchmark["ok"])
        self.assertIn("pack:win:x64", benchmark["tasks"])

    def test_android_docker_lanes_share_common_setup(self) -> None:
        script = HORC.read_text(encoding="utf-8")
        self.assertEqual(script.count("android_docker_common_script()"), 1)
        self.assertIn("android_docker_build_script() {\n  android_docker_common_script", script)
        self.assertIn("android_fast_docker_script() {\n  android_docker_common_script", script)
        self.assertEqual(script.count('export ANDROID_HOME="${PWD}/.android-sdk"'), 1)
        self.assertEqual(script.count('export GRADLE_USER_HOME="${PWD}/.gradle-home"'), 1)


if __name__ == "__main__":
    unittest.main()
