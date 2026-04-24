"""Daemon/bootstrap helpers for the browser-plus plugin."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

try:
    from .cdp_client import CDPConnection
    from .runtime import (
        normalize_session_name,
        resolve_cdp_ws_endpoint,
        session_log_path,
        session_pid_path,
        session_socket_path,
    )
except ImportError:  # pragma: no cover - standalone daemon/admin execution
    ROOT = Path(__file__).resolve().parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from cdp_client import CDPConnection  # type: ignore[no-redef]
    from runtime import (  # type: ignore[no-redef]
        normalize_session_name,
        resolve_cdp_ws_endpoint,
        session_log_path,
        session_pid_path,
        session_socket_path,
    )


BU_API = "https://api.browser-use.com/api/v3"
TRUTHY = {"1", "true", "yes", "on"}
_DAEMON_PID_RE = re.compile(r"^bp-(?P<name>.+)\.pid$")


def _log_tail(name: str) -> str | None:
    try:
        path = Path(session_log_path(name))
        return path.read_text(encoding="utf-8").strip().splitlines()[-1]
    except (FileNotFoundError, IndexError):
        return None


def daemon_alive(name: str | None = None) -> bool:
    target = normalize_session_name(name or "default")
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(1)
    try:
        client.connect(session_socket_path(target))
        return True
    except (FileNotFoundError, ConnectionRefusedError, socket.timeout, OSError):
        return False
    finally:
        try:
            client.close()
        except Exception:
            pass


def ensure_daemon(wait: float = 60.0, name: str | None = None, env: dict | None = None) -> dict:
    """Idempotently start the daemon for a logical browser-plus session."""

    target = normalize_session_name(name or "default")
    if daemon_alive(target):
        return {"ok": True, "started": False, "session_name": target}

    for stale_path in (session_socket_path(target), session_pid_path(target)):
        try:
            os.unlink(stale_path)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    plugin_dir = Path(__file__).resolve().parent
    child_env = {
        **os.environ,
        "BU_NAME": target,
        **(env or {}),
    }
    proc = subprocess.Popen(
        [sys.executable, str(plugin_dir / "daemon.py")],
        cwd=str(plugin_dir),
        env=child_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.time() + max(1.0, float(wait or 60.0))
    while time.time() < deadline:
        if daemon_alive(target):
            return {"ok": True, "started": True, "session_name": target}
        if proc.poll() is not None:
            break
        time.sleep(0.2)
    raise RuntimeError(_log_tail(target) or f"browser-plus daemon {target!r} did not come up")


def restart_daemon(name: str | None = None) -> dict:
    """Best-effort daemon shutdown plus socket/pid cleanup."""

    target = normalize_session_name(name or "default")
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(5)
    try:
        client.connect(session_socket_path(target))
        client.sendall(b'{"meta":"shutdown"}\n')
        client.recv(1024)
    except Exception:
        pass
    finally:
        try:
            client.close()
        except Exception:
            pass

    pid = None
    try:
        pid = int(Path(session_pid_path(target)).read_text(encoding="utf-8").strip())
    except Exception:
        pid = None

    if pid:
        for _ in range(75):
            try:
                os.kill(pid, 0)
                time.sleep(0.2)
            except ProcessLookupError:
                break
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    removed = []
    for stale_path in (session_socket_path(target), session_pid_path(target)):
        try:
            os.unlink(stale_path)
            removed.append(stale_path)
        except FileNotFoundError:
            pass
        except OSError:
            pass
    return {"ok": True, "session_name": target, "removed": removed}


def list_daemon_sessions() -> list[str]:
    sessions: set[str] = set()
    for path in Path("/tmp").glob("bp-*.pid"):
        match = _DAEMON_PID_RE.match(path.name)
        if not match:
            continue
        sessions.add(normalize_session_name(match.group("name")))
    for path in Path("/tmp").glob("bp-*.sock"):
        name = path.name[3:-5] if path.name.endswith(".sock") else ""
        if name:
            sessions.add(normalize_session_name(name))
    return sorted(sessions)


def restart_all_daemons() -> dict:
    sessions = list_daemon_sessions()
    results = []
    for session in sessions:
        try:
            results.append(restart_daemon(session))
        except Exception as exc:
            results.append({"ok": False, "session_name": session, "error": str(exc)})
    return {"ok": True, "sessions": results}


def ensure_local_daemon(name: str = "default") -> dict:
    return ensure_daemon(
        name=name,
        env={
            "BROWSER_PLUS_FORCE_MANAGED_LOCAL": "true",
            "BROWSER_CDP_URL": "",
            "BU_CDP_URL": "",
            "BU_CDP_WS": "",
        },
    )


def stop_remote_daemon(name: str = "remote") -> dict:
    return restart_daemon(name)


def _truthy_env(key: str, default: str = "") -> bool:
    return str(os.environ.get(key, default) or "").strip().lower() in TRUTHY


async def _attach_target(conn: CDPConnection, target_id: str) -> str:
    attached = await conn.send_raw("Target.attachToTarget", {"targetId": target_id, "flatten": True})
    session_id = str(attached["sessionId"])
    for domain in ("Page", "Runtime", "DOM"):
        try:
            await conn.send_raw(f"{domain}.enable", session_id=session_id)
        except Exception:
            pass
    return session_id


async def _wait_ready(conn: CDPConnection, session_id: str, timeout: float = 10.0) -> None:
    deadline = time.time() + max(0.5, timeout)
    while time.time() < deadline:
        try:
            payload = await conn.send_raw(
                "Runtime.evaluate",
                {"expression": "document.readyState", "returnByValue": True},
                session_id=session_id,
                timeout=5.0,
            )
            if payload.get("result", {}).get("value") in {"interactive", "complete"}:
                return
        except Exception:
            pass
        await asyncio.sleep(0.2)


async def _collect_page_storage(conn: CDPConnection, target_id: str) -> dict | None:
    session_id = await _attach_target(conn, target_id)
    try:
        payload = await conn.send_raw(
            "Runtime.evaluate",
            {
                "expression": (
                    "JSON.stringify({"
                    "href:location.href,"
                    "origin:location.origin,"
                    "localStorage:Object.fromEntries(Object.entries(localStorage)),"
                    "sessionStorage:Object.fromEntries(Object.entries(sessionStorage))"
                    "})"
                ),
                "returnByValue": True,
                "awaitPromise": True,
            },
            session_id=session_id,
            timeout=10.0,
        )
        value = payload.get("result", {}).get("value")
        if not value:
            return None
        state = json.loads(value)
    except Exception:
        return None
    finally:
        try:
            await conn.send_raw("Target.detachFromTarget", {"sessionId": session_id})
        except Exception:
            pass

    origin = str(state.get("origin", "") or "")
    if not origin.startswith(("http://", "https://")):
        return None
    return {
        "href": str(state.get("href", "") or origin),
        "origin": origin,
        "localStorage": state.get("localStorage") or {},
        "sessionStorage": state.get("sessionStorage") or {},
    }


async def _export_browser_state_async(cdp_url: str) -> dict:
    ws_url = resolve_cdp_ws_endpoint(cdp_url, timeout=15.0)
    conn = CDPConnection(ws_url)
    await conn.start()
    try:
        try:
            cookies = (await conn.send_raw("Storage.getCookies", timeout=15.0)).get("cookies", [])
        except Exception:
            cookies = (await conn.send_raw("Network.getAllCookies", timeout=15.0)).get("cookies", [])
        targets = (await conn.send_raw("Target.getTargets", timeout=15.0)).get("targetInfos", [])
        storage = []
        seen_origins: set[str] = set()
        for item in targets:
            if item.get("type") != "page":
                continue
            url = str(item.get("url", "") or "")
            if not url.startswith(("http://", "https://")):
                continue
            exported = await _collect_page_storage(conn, str(item["targetId"]))
            if not exported:
                continue
            origin = exported["origin"]
            if origin in seen_origins:
                continue
            seen_origins.add(origin)
            storage.append(exported)
        return {
            "source_cdp_url": cdp_url,
            "source_ws_url": ws_url,
            "cookies": cookies,
            "storage": storage,
        }
    finally:
        await conn.close()


def export_browser_state(cdp_url: str) -> dict:
    return asyncio.run(_export_browser_state_async(cdp_url))


async def _import_browser_state_async(state: dict) -> dict:
    ensure_local_daemon("pair-local")
    local_cdp_url = str(os.environ.get("BROWSER_PLUS_LOCAL_CDP_URL", "http://127.0.0.1:9233") or "").strip()
    local_ws = resolve_cdp_ws_endpoint(local_cdp_url, timeout=15.0)
    conn = CDPConnection(local_ws)
    await conn.start()
    try:
        cookies = list(state.get("cookies") or [])
        storage_items = list(state.get("storage") or [])
        cookie_result = {"count": 0, "method": ""}
        if cookies:
            try:
                await conn.send_raw("Storage.setCookies", {"cookies": cookies}, timeout=20.0)
                cookie_result = {"count": len(cookies), "method": "Storage.setCookies"}
            except Exception:
                await conn.send_raw("Network.setCookies", {"cookies": cookies}, timeout=20.0)
                cookie_result = {"count": len(cookies), "method": "Network.setCookies"}

        storage_synced = 0
        for item in storage_items:
            target = await conn.send_raw("Target.createTarget", {"url": item.get("href") or item.get("origin")}, timeout=10.0)
            session_id = await _attach_target(conn, str(target["targetId"]))
            await _wait_ready(conn, session_id)
            expression = (
                "(()=>{"
                f"const localData={json.dumps(item.get('localStorage') or {}, ensure_ascii=False)};"
                f"const sessionData={json.dumps(item.get('sessionStorage') or {}, ensure_ascii=False)};"
                "for (const [k,v] of Object.entries(localData)) localStorage.setItem(k, String(v));"
                "for (const [k,v] of Object.entries(sessionData)) sessionStorage.setItem(k, String(v));"
                "return {localCount:Object.keys(localData).length,sessionCount:Object.keys(sessionData).length};"
                "})()"
            )
            try:
                await conn.send_raw(
                    "Runtime.evaluate",
                    {"expression": expression, "returnByValue": True, "awaitPromise": True},
                    session_id=session_id,
                    timeout=15.0,
                )
                storage_synced += 1
            finally:
                try:
                    await conn.send_raw("Target.closeTarget", {"targetId": str(target["targetId"])}, timeout=5.0)
                except Exception:
                    pass
        return {
            "ok": True,
            "local_ws_url": local_ws,
            "cookies_imported": cookie_result["count"],
            "cookie_import_method": cookie_result["method"],
            "storage_origins_imported": storage_synced,
            "limitations": [
                "Passwords, extensions, history, and full browser settings are not copied.",
                "Cookie and storage sync works best for sites whose login state lives in cookies/local storage.",
                "Some advanced auth flows tied to OS keychains or hardware-bound sessions may still require re-login.",
            ],
        }
    finally:
        await conn.close()


def import_browser_state_to_local(state: dict) -> dict:
    return asyncio.run(_import_browser_state_async(state))


def pair_live_browser_to_local(cdp_url: str) -> dict:
    exported = export_browser_state(cdp_url)
    imported = import_browser_state_to_local(exported)
    return {
        "ok": True,
        "source_cdp_url": exported.get("source_cdp_url"),
        "cookies_exported": len(exported.get("cookies") or []),
        "storage_origins_exported": len(exported.get("storage") or []),
        **imported,
    }


def _browser_use(path: str, method: str, body: dict | None = None) -> dict:
    key = str(os.environ.get("BROWSER_USE_API_KEY", "") or "").strip()
    if not key:
        raise RuntimeError("BROWSER_USE_API_KEY missing")
    request = urllib.request.Request(
        f"{BU_API}{path}",
        method=method,
        data=(json.dumps(body).encode("utf-8") if body is not None else None),
        headers={
            "X-Browser-Use-API-Key": key,
            "Content-Type": "application/json",
        },
    )
    return json.loads(urllib.request.urlopen(request, timeout=60).read() or b"{}")


def _cdp_ws_from_url(cdp_url: str) -> str:
    return resolve_cdp_ws_endpoint(cdp_url, timeout=15.0)


def _has_local_gui() -> bool:
    if sys.platform == "darwin" or os.name == "nt":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _open_live_url(url: str) -> bool:
    if not url or not _has_local_gui():
        return False
    try:
        import webbrowser

        return bool(webbrowser.open(url, new=2))
    except Exception:
        return False


def list_cloud_profiles() -> list[dict]:
    out, page = [], 1
    while True:
        listing = _browser_use(f"/profiles?pageSize=100&pageNumber={page}", "GET")
        items = listing.get("items") if isinstance(listing, dict) else listing
        if not items:
            break
        for profile in items:
            detail = _browser_use(f"/profiles/{profile['id']}", "GET")
            out.append(
                {
                    "id": detail["id"],
                    "name": detail.get("name"),
                    "userId": detail.get("userId"),
                    "cookieDomains": detail.get("cookieDomains") or [],
                    "lastUsedAt": detail.get("lastUsedAt"),
                }
            )
        if isinstance(listing, dict) and len(out) >= listing.get("totalItems", len(out)):
            break
        page += 1
    return out


def _resolve_profile_name(profile_name: str) -> str:
    matches = [item for item in list_cloud_profiles() if item.get("name") == profile_name]
    if not matches:
        raise RuntimeError(f"No cloud profile named {profile_name!r}")
    if len(matches) > 1:
        raise RuntimeError(f"Multiple cloud profiles named {profile_name!r}; use profile_id")
    return str(matches[0]["id"])


def start_remote_daemon(
    name: str = "remote",
    profile_name: str | None = None,
    *,
    open_live_url: bool = False,
    **create_kwargs,
) -> dict:
    target = normalize_session_name(name or "remote")
    if daemon_alive(target):
        raise RuntimeError(f"Daemon {target!r} is already alive; restart it first")
    if profile_name:
        if create_kwargs.get("profileId"):
            raise RuntimeError("Pass profile_name or profileId, not both")
        create_kwargs["profileId"] = _resolve_profile_name(profile_name)
    browser = _browser_use("/browsers", "POST", create_kwargs)
    ws_url = _cdp_ws_from_url(str(browser["cdpUrl"]))
    ensure_daemon(
        name=target,
        env={
            "BU_CDP_WS": ws_url,
            "BU_BROWSER_ID": str(browser["id"]),
        },
    )
    live_url = str(browser.get("liveUrl") or "")
    opened = _open_live_url(live_url) if open_live_url else False
    return {
        **browser,
        "session_name": target,
        "liveUrl": live_url,
        "openedLiveUrl": opened,
    }


def list_local_profiles() -> list[dict]:
    if not shutil.which("profile-use"):
        raise RuntimeError("profile-use not installed; run curl -fsSL https://browser-use.com/profile.sh | sh")
    output = subprocess.check_output(["profile-use", "list", "--json"], text=True)
    return json.loads(output)


def sync_local_profile(
    profile_name: str,
    *,
    browser: str | None = None,
    cloud_profile_id: str | None = None,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> dict:
    if not shutil.which("profile-use"):
        raise RuntimeError("profile-use not installed; run curl -fsSL https://browser-use.com/profile.sh | sh")
    if not os.environ.get("BROWSER_USE_API_KEY"):
        raise RuntimeError("BROWSER_USE_API_KEY missing")

    cmd = ["profile-use", "sync", "--profile", profile_name]
    if browser:
        cmd += ["--browser", browser]
    if cloud_profile_id:
        cmd += ["--cloud-profile-id", cloud_profile_id]
    for domain in include_domains or []:
        cmd += ["--domain", domain]
    for domain in exclude_domains or []:
        cmd += ["--exclude-domain", domain]

    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"profile-use sync failed (exit {result.returncode}): {result.stderr.strip() or result.stdout.strip()}"
        )

    resolved_profile_id = cloud_profile_id
    if not resolved_profile_id:
        import re

        match = re.search(r"Profile created:\s+([0-9a-f-]{36})", result.stdout)
        if not match:
            raise RuntimeError("profile-use did not report a cloud profile UUID")
        resolved_profile_id = match.group(1)

    return {
        "profile_id": resolved_profile_id,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
