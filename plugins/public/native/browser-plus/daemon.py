"""Persistent CDP relay daemon for browser-plus."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

try:
    from .cdp_client import CDPConnection
    from .runtime import (
        INTERNAL_URL_PREFIXES,
        configured_cdp_candidate,
        normalize_session_name,
        resolve_cdp_ws_endpoint,
        session_log_path,
        session_pid_path,
        session_socket_path,
    )
except ImportError:  # pragma: no cover - standalone daemon execution
    ROOT = Path(__file__).resolve().parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from cdp_client import CDPConnection  # type: ignore[no-redef]
    from runtime import (  # type: ignore[no-redef]
        INTERNAL_URL_PREFIXES,
        configured_cdp_candidate,
        normalize_session_name,
        resolve_cdp_ws_endpoint,
        session_log_path,
        session_pid_path,
        session_socket_path,
    )


NAME = normalize_session_name(os.environ.get("BU_NAME", "default"))
SOCK = session_socket_path(NAME)
LOG = session_log_path(NAME)
PID = session_pid_path(NAME)
BUF = 500
PROFILES = [
    Path.home() / "Library/Application Support/Google/Chrome",
    Path.home() / "Library/Application Support/Microsoft Edge",
    Path.home() / "Library/Application Support/Microsoft Edge Beta",
    Path.home() / "Library/Application Support/Microsoft Edge Dev",
    Path.home() / "Library/Application Support/Microsoft Edge Canary",
    Path.home() / ".config/google-chrome",
    Path.home() / ".config/chromium",
    Path.home() / ".config/chromium-browser",
    Path.home() / ".config/microsoft-edge",
    Path.home() / ".config/microsoft-edge-beta",
    Path.home() / ".config/microsoft-edge-dev",
    Path.home() / "AppData/Local/Google/Chrome/User Data",
    Path.home() / "AppData/Local/Chromium/User Data",
    Path.home() / "AppData/Local/Microsoft/Edge/User Data",
    Path.home() / "AppData/Local/Microsoft/Edge Beta/User Data",
    Path.home() / "AppData/Local/Microsoft/Edge Dev/User Data",
    Path.home() / "AppData/Local/Microsoft/Edge SxS/User Data",
]
BU_API = "https://api.browser-use.com/api/v3"
REMOTE_ID = str(os.environ.get("BU_BROWSER_ID", "") or "").strip()
API_KEY = str(os.environ.get("BROWSER_USE_API_KEY", "") or "").strip()
TRUTHY = {"1", "true", "yes", "on"}
MANAGED_BROWSER_PID = "/tmp/browser-plus-managed-browser.pid"
MANAGED_BROWSER_LOG = "/tmp/browser-plus-managed-browser.log"
DEFAULT_MANAGED_CDP = str(os.environ.get("BROWSER_PLUS_LOCAL_CDP_URL", "http://127.0.0.1:9233") or "").strip()


def log(message: str) -> None:
    Path(LOG).write_text("", encoding="utf-8") if not Path(LOG).exists() else None
    with Path(LOG).open("a", encoding="utf-8") as handle:
        handle.write(f"{message}\n")


def get_ws_url() -> str:
    if str(os.environ.get("BROWSER_PLUS_FORCE_MANAGED_LOCAL", "") or "").strip().lower() in TRUTHY:
        return _ensure_managed_browser_ws()

    configured = configured_cdp_candidate()
    if configured:
        raw_endpoint, source = configured
        try:
            return resolve_cdp_ws_endpoint(raw_endpoint)
        except Exception as exc:
            raise RuntimeError(f"{source} is set but browser-plus could not resolve it: {exc}") from exc

    for base in PROFILES:
        port_file = base / "DevToolsActivePort"
        try:
            port, path = port_file.read_text(encoding="utf-8").strip().split("\n", 1)
        except (FileNotFoundError, NotADirectoryError, ValueError):
            continue
        deadline = time.time() + 30
        while True:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.settimeout(1)
            try:
                probe.connect(("127.0.0.1", int(port.strip())))
                return f"ws://127.0.0.1:{port.strip()}{path.strip()}"
            except OSError:
                if time.time() >= deadline:
                    raise RuntimeError(
                        "Chrome remote debugging was detected but DevTools is not listening yet. "
                        "If Chrome opened a profile picker, choose the real profile first, then allow remote debugging."
                    )
                time.sleep(1)
            finally:
                probe.close()

    if str(os.environ.get("BROWSER_PLUS_DISABLE_MANAGED_BROWSER", "") or "").strip().lower() not in TRUTHY:
        return _ensure_managed_browser_ws()

    raise RuntimeError(
        "No browser-plus CDP endpoint was found. Use `/browser connect`, set `BROWSER_CDP_URL` or `browser.cdp_url`, "
        "enable Chrome remote debugging so `DevToolsActivePort` exists, or start a Browser Use cloud session."
    )


def _managed_browser_profile_dir() -> Path:
    hermes_home_raw = str(os.environ.get("HERMES_HOME", "") or "").strip()
    if hermes_home_raw:
        base = Path(hermes_home_raw).expanduser() / "browser-plus" / "managed-browser-profile"
    else:
        base = Path.home() / ".cache" / "browser-plus" / "managed-browser-profile"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _managed_browser_candidates() -> list[str]:
    explicit = str(os.environ.get("BROWSER_PLUS_BROWSER_BIN", "") or "").strip()
    names = [explicit] if explicit else []
    names.extend(
        [
            "google-chrome",
            "google-chrome-stable",
            "chromium-browser",
            "chromium",
            "microsoft-edge",
            "microsoft-edge-stable",
            "msedge",
        ]
    )
    found: list[str] = []
    seen: set[str] = set()
    for item in names:
        if not item:
            continue
        path = item if os.path.isabs(item) and os.path.exists(item) else shutil.which(item)
        if not path or path in seen:
            continue
        seen.add(path)
        found.append(path)
    return found


def _managed_browser_command(debug_url: str, browser_path: str) -> list[str]:
    parsed = urlparse(debug_url)
    if parsed.scheme not in {"http", "https"} or not parsed.port:
        raise RuntimeError(f"BROWSER_PLUS_LOCAL_CDP_URL must be an http(s) URL with a port, got {debug_url!r}")

    command = [
        browser_path,
        f"--remote-debugging-port={parsed.port}",
        f"--user-data-dir={_managed_browser_profile_dir()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-default-apps",
        "--disable-dev-shm-usage",
        "--disable-sync",
        "--metrics-recording-only",
        "--mute-audio",
    ]
    if str(os.environ.get("BROWSER_PLUS_MANAGED_HEADLESS", "true") or "").strip().lower() in TRUTHY:
        command.append("--headless=new")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        command.append("--no-sandbox")
    command.append(str(os.environ.get("BROWSER_PLUS_START_URL", "about:blank") or "about:blank"))
    return command


def _read_tail(path: str, lines: int = 20) -> str:
    try:
        data = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return ""
    return "\n".join(data[-lines:])


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _ensure_managed_browser_ws() -> str:
    debug_url = DEFAULT_MANAGED_CDP
    last_error = ""
    try:
        return resolve_cdp_ws_endpoint(debug_url, timeout=2.0)
    except Exception as exc:
        last_error = str(exc)

    try:
        existing_pid = int(Path(MANAGED_BROWSER_PID).read_text(encoding="utf-8").strip())
    except Exception:
        existing_pid = 0
    if existing_pid and _pid_is_alive(existing_pid):
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                return resolve_cdp_ws_endpoint(debug_url, timeout=2.0)
            except Exception as exc:
                last_error = str(exc)
                time.sleep(0.5)

    candidates = _managed_browser_candidates()
    if not candidates:
        raise RuntimeError(
            "No Chrome/Chromium/Edge binary was found for the managed browser fallback. "
            "Install Chromium or set BROWSER_PLUS_BROWSER_BIN."
        )

    browser_path = candidates[0]
    command = _managed_browser_command(debug_url, browser_path)
    log_handle = Path(MANAGED_BROWSER_LOG).open("a", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command,
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )
    finally:
        log_handle.close()
    Path(MANAGED_BROWSER_PID).write_text(str(process.pid), encoding="utf-8")
    deadline = time.time() + 30
    while time.time() < deadline:
        if process.poll() is not None:
            break
        try:
            return resolve_cdp_ws_endpoint(debug_url, timeout=2.0)
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.5)

    raise RuntimeError(
        "browser-plus could not start its managed local browser fallback. "
        f"Command: {' '.join(command)}. Last error: {last_error or 'unknown'}. "
        f"Browser log tail:\n{_read_tail(MANAGED_BROWSER_LOG)}"
    )


def stop_remote() -> None:
    if not REMOTE_ID or not API_KEY:
        return
    try:
        request = urllib.request.Request(
            f"{BU_API}/browsers/{REMOTE_ID}",
            data=json.dumps({"action": "stop"}).encode("utf-8"),
            method="PATCH",
            headers={
                "X-Browser-Use-API-Key": API_KEY,
                "Content-Type": "application/json",
            },
        )
        urllib.request.urlopen(request, timeout=15).read()
        log(f"stopped remote browser {REMOTE_ID}")
    except Exception as exc:
        log(f"stop_remote failed ({REMOTE_ID}): {exc}")


def is_real_page(target: dict) -> bool:
    return target.get("type") == "page" and not str(target.get("url", "")).startswith(INTERNAL_URL_PREFIXES)


class Daemon:
    def __init__(self) -> None:
        self.cdp: CDPConnection | None = None
        self.session: str | None = None
        self.current_target_id: str | None = None
        self.events: deque = deque(maxlen=BUF)
        self.dialog: dict | None = None
        self.stop: asyncio.Event | None = None
        self.ws_url = ""

    async def attach_first_page(self) -> dict | None:
        assert self.cdp is not None
        targets = (await self.cdp.send_raw("Target.getTargets"))["targetInfos"]
        pages = [target for target in targets if is_real_page(target)]
        if not pages:
            target_id = (await self.cdp.send_raw("Target.createTarget", {"url": "about:blank"}))["targetId"]
            pages = [{"targetId": target_id, "url": "about:blank", "type": "page"}]
            log(f"no real pages found, created about:blank ({target_id})")

        first = pages[0]
        self.current_target_id = first["targetId"]
        self.session = (
            await self.cdp.send_raw(
                "Target.attachToTarget",
                {"targetId": self.current_target_id, "flatten": True},
            )
        )["sessionId"]
        log(f"attached {self.current_target_id} ({first.get('url', '')[:80]}) session={self.session}")
        for domain in ("Page", "DOM", "Runtime", "Network"):
            try:
                await asyncio.wait_for(
                    self.cdp.send_raw(f"{domain}.enable", session_id=self.session),
                    timeout=5,
                )
            except Exception as exc:
                log(f"enable {domain}: {exc}")
        await self._mark_tab()
        return first

    async def start(self) -> None:
        self.stop = asyncio.Event()
        self.ws_url = get_ws_url()
        log(f"connecting to {self.ws_url}")
        self.cdp = CDPConnection(self.ws_url, event_handler=self._on_event)
        try:
            await self.cdp.start()
        except Exception as exc:
            raise RuntimeError(f"CDP websocket handshake failed: {exc}")
        await self.attach_first_page()

    async def _on_event(self, method: str, params: dict, session_id: str | None) -> None:
        self.events.append({"method": method, "params": params, "session_id": session_id})
        if method == "Page.javascriptDialogOpening":
            self.dialog = params
        elif method == "Page.javascriptDialogClosed":
            self.dialog = None
        elif method in {"Page.loadEventFired", "Page.domContentEventFired"}:
            await self._mark_tab()

    async def _mark_tab(self) -> None:
        if not self.cdp or not self.session:
            return
        try:
            await asyncio.wait_for(
                self.cdp.send_raw(
                    "Runtime.evaluate",
                    {"expression": "if(!document.title.startsWith('🟢 '))document.title='🟢 '+document.title"},
                    session_id=self.session,
                ),
                timeout=2,
            )
        except Exception:
            pass

    async def handle(self, request: dict) -> dict:
        assert self.cdp is not None
        meta = request.get("meta")
        if meta == "drain_events":
            events = list(self.events)
            self.events.clear()
            return {"events": events}
        if meta == "session":
            return {"session_id": self.session, "target_id": self.current_target_id}
        if meta == "set_session":
            self.session = request.get("session_id")
            self.current_target_id = request.get("target_id") or self.current_target_id
            if self.session:
                try:
                    await asyncio.wait_for(
                        self.cdp.send_raw("Page.enable", session_id=self.session),
                        timeout=3,
                    )
                except Exception:
                    pass
                await self._mark_tab()
            return {"session_id": self.session, "target_id": self.current_target_id}
        if meta == "pending_dialog":
            return {"dialog": self.dialog}
        if meta == "browser_status":
            return {
                "daemon_alive": True,
                "session_id": self.session,
                "target_id": self.current_target_id,
                "socket_path": SOCK,
                "pid_path": PID,
                "log_path": LOG,
                "ws_url": self.ws_url,
                "remote_browser_id": REMOTE_ID,
                "dialog": self.dialog,
            }
        if meta == "shutdown":
            assert self.stop is not None
            self.stop.set()
            return {"ok": True}

        method = str(request["method"])
        params = request.get("params") or {}
        session_id = None if method.startswith("Target.") else (request.get("session_id") or self.session)
        try:
            result = await self.cdp.send_raw(method, params, session_id=session_id)
            return {"result": result}
        except Exception as exc:
            message = str(exc)
            if "Session with given id not found" in message and session_id == self.session and session_id:
                log(f"stale session {session_id}, re-attaching")
                if await self.attach_first_page():
                    result = await self.cdp.send_raw(method, params, session_id=self.session if not method.startswith("Target.") else None)
                    return {"result": result}
            return {"error": message}


async def serve(daemon: Daemon) -> None:
    if os.path.exists(SOCK):
        os.unlink(SOCK)

    async def handler(reader, writer) -> None:
        try:
            line = await reader.readline()
            if not line:
                return
            response = await daemon.handle(json.loads(line))
            writer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
            await writer.drain()
        except Exception as exc:
            log(f"conn: {exc}")
            try:
                writer.write((json.dumps({"error": str(exc)}, ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()

    server = await asyncio.start_unix_server(handler, path=SOCK)
    os.chmod(SOCK, 0o600)
    log(f"listening on {SOCK} (name={NAME}, remote={REMOTE_ID or 'local'})")
    async with server:
        assert daemon.stop is not None
        await daemon.stop.wait()


async def main() -> None:
    daemon = Daemon()
    await daemon.start()
    await serve(daemon)


def already_running() -> bool:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(1)
    try:
        client.connect(SOCK)
        return True
    except (FileNotFoundError, ConnectionRefusedError, socket.timeout, OSError):
        return False
    finally:
        try:
            client.close()
        except Exception:
            pass


if __name__ == "__main__":
    if already_running():
        print(f"browser-plus daemon already running on {SOCK}", file=sys.stderr)
        raise SystemExit(0)

    Path(LOG).write_text("", encoding="utf-8")
    Path(PID).write_text(str(os.getpid()), encoding="utf-8")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        log(f"fatal: {exc}")
        raise SystemExit(1)
    finally:
        stop_remote()
        for stale_path in (PID, SOCK):
            try:
                os.unlink(stale_path)
            except FileNotFoundError:
                pass
