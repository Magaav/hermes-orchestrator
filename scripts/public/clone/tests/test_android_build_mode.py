from __future__ import annotations

import os
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

    def make_bin(self, root: Path, docker_body: str | None = None) -> Path:
        bin_dir = root / "bin"
        bin_dir.mkdir(exist_ok=True)
        for name in ("java", "node"):
            path = bin_dir / name
            path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            os.chmod(path, 0o755)
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


if __name__ == "__main__":
    unittest.main()
