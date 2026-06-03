#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import io
import json
import os
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
STATIC_SERVER = ROOT / "plugins" / "wasm-agent" / "server" / "static_server.py"


def load_static_server():
    spec = importlib.util.spec_from_file_location("wasm_agent_static_server", STATIC_SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeHandler:
    headers = {"Host": "127.0.0.1:8877"}


def main() -> None:
    os.environ.pop("HERMES_WASM_AGENT_PUBLIC_ORIGIN", None)
    module = load_static_server()
    module.create_native_companion_package = lambda _server, _user, request_body, _handler: {
        "package": {
            "target_label": "Desktop Dev",
            "target_os": request_body["target_os"],
            "target_device_id": request_body["target_device_id"],
            "install_channel": "native-companion-installer",
        }
    }
    body = {"target_os": "linux", "target_device_id": "desktop-dev"}
    filename, data, metadata = module.create_native_download_bundle(None, None, body, FakeHandler())

    assert filename.startswith("wasm-agent-native-linux-")
    assert metadata["app_url"] == "http://127.0.0.1:8877/home"
    assert metadata["package"]["app_url"] == "http://127.0.0.1:8877/home"

    with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
        package = json.loads(archive.read("metadata/package.json"))
        linux_install = archive.read("linux/install.sh").decode("utf-8")
        macos_launcher = archive.read("macos/WASM Agent.app/Contents/MacOS/wasm-agent").decode("utf-8")
        windows_install = archive.read("windows/install.ps1").decode("utf-8")
        windows_main = archive.read("windows/electron-app/main.js").decode("utf-8")
        windows_preload = archive.read("windows/electron-app/preload.js").decode("utf-8")

    assert package["app_url"] == "http://127.0.0.1:8877/home"
    assert "APP_URL='http://127.0.0.1:8877/home'" in linux_install
    assert "APP_URL='http://127.0.0.1:8877/home'" in macos_launcher
    assert "$AppUrl = 'http://127.0.0.1:8877/home'" in windows_install
    assert "validateWasmAgentOrigin" in windows_main
    assert "unresolved-backend" in windows_main
    assert "GOOGLE_AUTH_ORIGINS" in windows_main
    assert "wasm-agent:native-dev-hmr-reload" in windows_main
    assert "__wasmAgentDevHmr" in windows_preload

    assert module.native_pwa_app_url("https://wa.example.test/root?x=1#frag") == "https://wa.example.test/home"
    assert module.native_pwa_app_url("/") == "/home"
    print("native download bundle ok")


if __name__ == "__main__":
    main()
