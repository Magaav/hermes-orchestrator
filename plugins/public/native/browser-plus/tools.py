"""Tool handlers for the browser-plus plugin."""

from __future__ import annotations

import base64
import gzip
import json
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict

from tools.registry import tool_error, tool_result

from . import admin
from .runtime import (
    INTERNAL_URL_PREFIXES,
    current_tab_payload,
    default_screenshot_path,
    read_knowledge,
    resolve_session_name,
    search_knowledge,
    send_request,
    suggest_knowledge_for_url,
    write_operation_log,
)


_KEYS = {
    "Enter": (13, "Enter", "\r"),
    "Tab": (9, "Tab", "\t"),
    "Backspace": (8, "Backspace", ""),
    "Escape": (27, "Escape", ""),
    "Delete": (46, "Delete", ""),
    " ": (32, "Space", " "),
    "ArrowLeft": (37, "ArrowLeft", ""),
    "ArrowUp": (38, "ArrowUp", ""),
    "ArrowRight": (39, "ArrowRight", ""),
    "ArrowDown": (40, "ArrowDown", ""),
    "Home": (36, "Home", ""),
    "End": (35, "End", ""),
    "PageUp": (33, "PageUp", ""),
    "PageDown": (34, "PageDown", ""),
}
_KEYCODES = {
    "Enter": 13,
    "Tab": 9,
    "Escape": 27,
    "Backspace": 8,
    " ": 32,
    "ArrowLeft": 37,
    "ArrowUp": 38,
    "ArrowRight": 39,
    "ArrowDown": 40,
}


def _session_name(args: dict | None = None, **kwargs) -> str:
    return resolve_session_name(args=args, **kwargs)


def _log_and_return(action: str, payload: dict, **kwargs) -> str:
    result = dict(payload)
    result.setdefault("action", action)
    result.setdefault("ok", "error" not in result)
    log_payload = dict(result)
    log_path = write_operation_log(action, log_payload, **kwargs)
    result["log_path"] = log_path
    return tool_result(result)


def _wrap_errors(action: str, fn, *args, **kwargs) -> str:
    try:
        payload = fn(*args, **kwargs)
        return _log_and_return(action, payload, **kwargs)
    except Exception as exc:
        return _log_and_return(action, {"ok": False, "error": str(exc)}, **kwargs)


def _send(session_name: str, request: dict, *, ensure: bool = True) -> dict:
    return send_request(session_name, request, auto_start=ensure)


def _cdp(session_name: str, method: str, *, session_id: str | None = None, **params) -> dict:
    return _send(
        session_name,
        {
            "method": method,
            "params": params,
            **({"session_id": session_id} if session_id else {}),
        },
    ).get("result", {})


def _status(session_name: str, *, ensure_daemon: bool = True) -> dict:
    if not ensure_daemon and not admin.daemon_alive(session_name):
        return {
            "daemon_alive": False,
            "session_name": session_name,
            "current_tab": None,
            "tabs": [],
        }
    if ensure_daemon:
        admin.ensure_daemon(name=session_name)
    payload = _send(session_name, {"meta": "browser_status"}, ensure=ensure_daemon)
    tabs = _list_tabs_payload(session_name, include_internal=True)
    current_tab = current_tab_payload(tabs, payload.get("target_id"))
    return {
        "daemon_alive": True,
        "session_name": session_name,
        "session_id": payload.get("session_id"),
        "target_id": payload.get("target_id"),
        "socket_path": payload.get("socket_path"),
        "pid_path": payload.get("pid_path"),
        "daemon_log_path": payload.get("log_path"),
        "ws_url": payload.get("ws_url"),
        "remote_browser_id": payload.get("remote_browser_id"),
        "dialog": payload.get("dialog"),
        "current_tab": current_tab,
        "tabs": tabs,
    }


def _list_tabs_payload(session_name: str, *, include_internal: bool) -> list[dict]:
    status = _send(session_name, {"meta": "browser_status"})
    current_target_id = status.get("target_id")
    tabs = []
    for item in _cdp(session_name, "Target.getTargets").get("targetInfos", []):
        if item.get("type") != "page":
            continue
        url = str(item.get("url", "") or "")
        if not include_internal and url.startswith(INTERNAL_URL_PREFIXES):
            continue
        tabs.append(
            {
                "targetId": item.get("targetId"),
                "title": item.get("title", ""),
                "url": url,
                "active": item.get("targetId") == current_target_id,
            }
        )
    return tabs


def _mark_title_cleanup(session_name: str) -> None:
    try:
        _cdp(
            session_name,
            "Runtime.evaluate",
            expression="if(document.title.startsWith('🟢 '))document.title=document.title.slice(2)",
        )
    except Exception:
        pass


def _switch_tab_payload(session_name: str, target_id: str) -> dict:
    _mark_title_cleanup(session_name)
    _cdp(session_name, "Target.activateTarget", targetId=target_id)
    attached = _cdp(session_name, "Target.attachToTarget", targetId=target_id, flatten=True)
    session_id = attached["sessionId"]
    _send(
        session_name,
        {
            "meta": "set_session",
            "session_id": session_id,
            "target_id": target_id,
        },
    )
    status = _status(session_name, ensure_daemon=True)
    return {
        "session_name": session_name,
        "session_id": session_id,
        "target_id": target_id,
        "current_tab": status.get("current_tab"),
    }


def _resolve_local_path(path_value: str, **kwargs) -> Path:
    candidate = Path(str(path_value or "")).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    cwd = Path(
        str(kwargs.get("current_working_directory") or kwargs.get("cwd") or "").strip() or "."
    ).expanduser()
    return (cwd / candidate).resolve()


def browser_plus_status(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)
    ensure_daemon = bool(args.get("ensure_daemon", True))

    def _impl(**_ignored):
        return _status(session_name, ensure_daemon=ensure_daemon)

    return _wrap_errors("browser_plus_status", _impl, **kwargs)


def browser_plus_goto(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)
    url = str(args.get("url", "") or "").strip()

    def _impl(**_ignored):
        result = _cdp(session_name, "Page.navigate", url=url)
        return {
            "session_name": session_name,
            "url": url,
            "result": result,
            "knowledge_hits": suggest_knowledge_for_url(url),
        }

    if not url:
        return tool_error("url is required")
    return _wrap_errors("browser_plus_goto", _impl, **kwargs)


def browser_plus_page_info(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)

    def _impl(**_ignored):
        dialog = _send(session_name, {"meta": "pending_dialog"}).get("dialog")
        if dialog:
            return {"session_name": session_name, "dialog": dialog}
        result = _cdp(
            session_name,
            "Runtime.evaluate",
            expression=(
                "JSON.stringify({url:location.href,title:document.title,w:innerWidth,h:innerHeight,"
                "sx:scrollX,sy:scrollY,pw:document.documentElement.scrollWidth,"
                "ph:document.documentElement.scrollHeight})"
            ),
            returnByValue=True,
        )
        value = json.loads(result["result"]["value"])
        return {"session_name": session_name, "page": value}

    return _wrap_errors("browser_plus_page_info", _impl, **kwargs)


def browser_plus_click(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)

    def _impl(**_ignored):
        x = float(args["x"])
        y = float(args["y"])
        button = str(args.get("button", "left") or "left")
        clicks = int(args.get("clicks", 1) or 1)
        for event_type in ("mousePressed", "mouseReleased"):
            _cdp(
                session_name,
                "Input.dispatchMouseEvent",
                type=event_type,
                x=x,
                y=y,
                button=button,
                clickCount=clicks,
            )
        return {"session_name": session_name, "x": x, "y": y, "button": button, "clicks": clicks}

    if "x" not in args or "y" not in args:
        return tool_error("x and y are required")
    return _wrap_errors("browser_plus_click", _impl, **kwargs)


def browser_plus_type_text(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)
    text = str(args.get("text", "") or "")
    if not text:
        return tool_error("text is required")

    def _impl(**_ignored):
        _cdp(session_name, "Input.insertText", text=text)
        return {"session_name": session_name, "text": text}

    return _wrap_errors("browser_plus_type_text", _impl, **kwargs)


def browser_plus_press_key(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)
    key = str(args.get("key", "") or "")
    if not key:
        return tool_error("key is required")

    def _impl(**_ignored):
        modifiers = int(args.get("modifiers", 0) or 0)
        vk, code, text = _KEYS.get(
            key,
            (ord(key[0]) if len(key) == 1 else 0, key, key if len(key) == 1 else ""),
        )
        base = {
            "key": key,
            "code": code,
            "modifiers": modifiers,
            "windowsVirtualKeyCode": vk,
            "nativeVirtualKeyCode": vk,
        }
        _cdp(session_name, "Input.dispatchKeyEvent", type="keyDown", **base, **({"text": text} if text else {}))
        if text and len(text) == 1:
            _cdp(
                session_name,
                "Input.dispatchKeyEvent",
                type="char",
                text=text,
                **{k: v for k, v in base.items() if k != "text"},
            )
        _cdp(session_name, "Input.dispatchKeyEvent", type="keyUp", **base)
        return {"session_name": session_name, "key": key, "modifiers": modifiers}

    return _wrap_errors("browser_plus_press_key", _impl, **kwargs)


def browser_plus_scroll(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)
    if "x" not in args or "y" not in args:
        return tool_error("x and y are required")

    def _impl(**_ignored):
        x = float(args["x"])
        y = float(args["y"])
        dy = float(args.get("dy", -300) or -300)
        dx = float(args.get("dx", 0) or 0)
        _cdp(session_name, "Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=dx, deltaY=dy)
        return {"session_name": session_name, "x": x, "y": y, "dx": dx, "dy": dy}

    return _wrap_errors("browser_plus_scroll", _impl, **kwargs)


def browser_plus_screenshot(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)

    def _impl(**_ignored):
        full = bool(args.get("full", False))
        requested_path = str(args.get("path", "") or "").strip()
        path = _resolve_local_path(requested_path, **kwargs) if requested_path else default_screenshot_path(session_name, **kwargs)
        path.parent.mkdir(parents=True, exist_ok=True)
        result = _cdp(session_name, "Page.captureScreenshot", format="png", captureBeyondViewport=full)
        path.write_bytes(base64.b64decode(result["data"]))
        return {
            "session_name": session_name,
            "path": str(path),
            "full": full,
        }

    return _wrap_errors("browser_plus_screenshot", _impl, **kwargs)


def browser_plus_list_tabs(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)
    include_internal = bool(args.get("include_internal", True))

    def _impl(**_ignored):
        return {
            "session_name": session_name,
            "tabs": _list_tabs_payload(session_name, include_internal=include_internal),
        }

    return _wrap_errors("browser_plus_list_tabs", _impl, **kwargs)


def browser_plus_current_tab(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)

    def _impl(**_ignored):
        status = _status(session_name, ensure_daemon=True)
        return {
            "session_name": session_name,
            "current_tab": status.get("current_tab"),
        }

    return _wrap_errors("browser_plus_current_tab", _impl, **kwargs)


def browser_plus_switch_tab(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    target_id = str(args.get("target_id", "") or "").strip()
    if not target_id:
        return tool_error("target_id is required")
    session_name = _session_name(args, **kwargs)
    return _wrap_errors(
        "browser_plus_switch_tab",
        _switch_tab_payload,
        session_name,
        target_id,
        **kwargs,
    )


def browser_plus_new_tab(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)

    def _impl(**_ignored):
        url = str(args.get("url", "about:blank") or "about:blank").strip() or "about:blank"
        target_id = _cdp(session_name, "Target.createTarget", url="about:blank")["targetId"]
        switched = _switch_tab_payload(session_name, target_id)
        if url != "about:blank":
            _cdp(session_name, "Page.navigate", url=url)
        return {
            "session_name": session_name,
            "target_id": target_id,
            "url": url,
            "switched": switched,
            "knowledge_hits": suggest_knowledge_for_url(url),
        }

    return _wrap_errors("browser_plus_new_tab", _impl, **kwargs)


def browser_plus_ensure_real_tab(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)

    def _impl(**_ignored):
        status = _status(session_name, ensure_daemon=True)
        current_tab = status.get("current_tab") or {}
        current_url = str(current_tab.get("url", "") or "")
        if current_url and not current_url.startswith(INTERNAL_URL_PREFIXES):
            return {"session_name": session_name, "current_tab": current_tab, "changed": False}
        tabs = _list_tabs_payload(session_name, include_internal=False)
        if not tabs:
            return {"session_name": session_name, "current_tab": None, "changed": False}
        switched = _switch_tab_payload(session_name, str(tabs[0]["targetId"]))
        return {"session_name": session_name, "current_tab": switched.get("current_tab"), "changed": True}

    return _wrap_errors("browser_plus_ensure_real_tab", _impl, **kwargs)


def browser_plus_wait(args: dict | None = None, **kwargs) -> str:
    args = args or {}

    def _impl(**_ignored):
        seconds = max(0.0, min(float(args.get("seconds", 1.0) or 1.0), 60.0))
        time.sleep(seconds)
        return {"seconds": seconds}

    return _wrap_errors("browser_plus_wait", _impl, **kwargs)


def browser_plus_wait_for_load(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)

    def _impl(**_ignored):
        timeout = max(1.0, min(float(args.get("timeout", 15.0) or 15.0), 120.0))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                result = _cdp(
                    session_name,
                    "Runtime.evaluate",
                    expression="document.readyState",
                    returnByValue=True,
                    awaitPromise=True,
                )
                if result.get("result", {}).get("value") == "complete":
                    return {"session_name": session_name, "loaded": True, "timeout": timeout}
            except Exception:
                pass
            time.sleep(0.3)
        return {"session_name": session_name, "loaded": False, "timeout": timeout}

    return _wrap_errors("browser_plus_wait_for_load", _impl, **kwargs)


def browser_plus_eval_js(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    expression = str(args.get("expression", "") or "")
    if not expression:
        return tool_error("expression is required")
    session_name = _session_name(args, **kwargs)

    def _impl(**_ignored):
        target_id = str(args.get("target_id", "") or "").strip()
        session_id = None
        if target_id:
            session_id = _cdp(session_name, "Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
        result = _cdp(
            session_name,
            "Runtime.evaluate",
            session_id=session_id,
            expression=expression,
            returnByValue=bool(args.get("return_by_value", True)),
            awaitPromise=bool(args.get("await_promise", True)),
        )
        return {
            "session_name": session_name,
            "target_id": target_id or None,
            "result": result,
            "value": result.get("result", {}).get("value"),
        }

    return _wrap_errors("browser_plus_eval_js", _impl, **kwargs)


def browser_plus_dispatch_key(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    selector = str(args.get("selector", "") or "")
    if not selector:
        return tool_error("selector is required")
    session_name = _session_name(args, **kwargs)

    def _impl(**_ignored):
        key = str(args.get("key", "Enter") or "Enter")
        event = str(args.get("event", "keypress") or "keypress")
        key_code = _KEYCODES.get(key, ord(key) if len(key) == 1 else 0)
        expression = (
            "(()=>{"
            f"const e=document.querySelector({json.dumps(selector)});"
            "if(!e)return false;"
            "e.focus();"
            f"e.dispatchEvent(new KeyboardEvent({json.dumps(event)},{{key:{json.dumps(key)},code:{json.dumps(key)},keyCode:{key_code},which:{key_code},bubbles:true}}));"
            "return true;"
            "})()"
        )
        result = _cdp(
            session_name,
            "Runtime.evaluate",
            expression=expression,
            returnByValue=True,
            awaitPromise=True,
        )
        return {
            "session_name": session_name,
            "selector": selector,
            "key": key,
            "event": event,
            "dispatched": bool(result.get("result", {}).get("value")),
        }

    return _wrap_errors("browser_plus_dispatch_key", _impl, **kwargs)


def browser_plus_upload_file(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    selector = str(args.get("selector", "") or "")
    if not selector:
        return tool_error("selector is required")
    session_name = _session_name(args, **kwargs)

    def _impl(**_ignored):
        path_value = args.get("path")
        if isinstance(path_value, list):
            files = [str(_resolve_local_path(item, **kwargs)) for item in path_value]
        else:
            files = [str(_resolve_local_path(str(path_value or ""), **kwargs))]
        for file_path in files:
            if not Path(file_path).exists():
                raise FileNotFoundError(f"upload path not found: {file_path}")
        document = _cdp(session_name, "DOM.getDocument", depth=-1)
        node = _cdp(
            session_name,
            "DOM.querySelector",
            nodeId=document["root"]["nodeId"],
            selector=selector,
        )
        node_id = int(node.get("nodeId") or 0)
        if not node_id:
            raise RuntimeError(f"No element matched selector {selector!r}")
        _cdp(session_name, "DOM.setFileInputFiles", files=files, nodeId=node_id)
        return {"session_name": session_name, "selector": selector, "files": files}

    return _wrap_errors("browser_plus_upload_file", _impl, **kwargs)


def browser_plus_http_get(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    url = str(args.get("url", "") or "")
    if not url:
        return tool_error("url is required")

    def _impl(**_ignored):
        headers = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"}
        extra_headers = args.get("headers")
        if isinstance(extra_headers, dict):
            headers.update({str(k): str(v) for k, v in extra_headers.items()})
        timeout = max(1.0, min(float(args.get("timeout", 20.0) or 20.0), 120.0))
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
            data = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                data = gzip.decompress(data)
            text = data.decode("utf-8", errors="replace")
            return {
                "url": url,
                "status": getattr(response, "status", None),
                "content": text,
                "content_length": len(text),
            }

    return _wrap_errors("browser_plus_http_get", _impl, **kwargs)


def browser_plus_cdp(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    method = str(args.get("method", "") or "")
    if not method:
        return tool_error("method is required")
    session_name = _session_name(args, **kwargs)

    def _impl(**_ignored):
        params = args.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise ValueError("params must be an object")
        result = _cdp(session_name, method, session_id=str(args.get("session_id", "") or "") or None, **params)
        return {"session_name": session_name, "method": method, "result": result}

    return _wrap_errors("browser_plus_cdp", _impl, **kwargs)


def browser_plus_drain_events(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)

    def _impl(**_ignored):
        events = _send(session_name, {"meta": "drain_events"}).get("events", [])
        return {"session_name": session_name, "events": events}

    return _wrap_errors("browser_plus_drain_events", _impl, **kwargs)


def browser_plus_get_dialog(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)

    def _impl(**_ignored):
        dialog = _send(session_name, {"meta": "pending_dialog"}).get("dialog")
        return {"session_name": session_name, "dialog": dialog}

    return _wrap_errors("browser_plus_get_dialog", _impl, **kwargs)


def browser_plus_handle_dialog(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)

    def _impl(**_ignored):
        accept = bool(args.get("accept", True))
        prompt_text = str(args.get("prompt_text", "") or "")
        result = _cdp(session_name, "Page.handleJavaScriptDialog", accept=accept, promptText=prompt_text)
        return {"session_name": session_name, "accept": accept, "prompt_text": prompt_text, "result": result}

    return _wrap_errors("browser_plus_handle_dialog", _impl, **kwargs)


def browser_plus_extract_text(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)

    def _impl(**_ignored):
        selector = str(args.get("selector", "") or "").strip()
        max_chars = max(256, min(int(args.get("max_chars", 12000) or 12000), 50000))
        if selector:
            expression = (
                "(()=>{"
                f"const el=document.querySelector({json.dumps(selector)});"
                "return el ? (el.innerText || el.textContent || '') : '';"
                "})()"
            )
        else:
            expression = "(document.body && (document.body.innerText || document.body.textContent)) || ''"
        result = _cdp(
            session_name,
            "Runtime.evaluate",
            expression=expression,
            returnByValue=True,
            awaitPromise=True,
        )
        text = str(result.get("result", {}).get("value") or "")
        return {
            "session_name": session_name,
            "selector": selector or None,
            "content": text[:max_chars],
            "truncated": len(text) > max_chars,
            "content_length": len(text),
        }

    return _wrap_errors("browser_plus_extract_text", _impl, **kwargs)


def browser_plus_list_cloud_profiles(args: dict | None = None, **kwargs) -> str:
    def _impl(**_ignored):
        return {"profiles": admin.list_cloud_profiles()}

    return _wrap_errors("browser_plus_list_cloud_profiles", _impl, **kwargs)


def browser_plus_list_local_profiles(args: dict | None = None, **kwargs) -> str:
    def _impl(**_ignored):
        return {"profiles": admin.list_local_profiles()}

    return _wrap_errors("browser_plus_list_local_profiles", _impl, **kwargs)


def browser_plus_sync_local_profile(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    profile_name = str(args.get("profile_name", "") or "")
    if not profile_name:
        return tool_error("profile_name is required")

    def _impl(**_ignored):
        return admin.sync_local_profile(
            profile_name,
            browser=str(args.get("browser", "") or "") or None,
            cloud_profile_id=str(args.get("cloud_profile_id", "") or "") or None,
            include_domains=args.get("include_domains") if isinstance(args.get("include_domains"), list) else None,
            exclude_domains=args.get("exclude_domains") if isinstance(args.get("exclude_domains"), list) else None,
        )

    return _wrap_errors("browser_plus_sync_local_profile", _impl, **kwargs)


def browser_plus_start_remote_daemon(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)

    def _impl(**_ignored):
        create_kwargs: Dict[str, Any] = {}
        if str(args.get("profile_id", "") or "").strip():
            create_kwargs["profileId"] = str(args["profile_id"]).strip()
        if str(args.get("proxy_country_code", "") or "").strip():
            create_kwargs["proxyCountryCode"] = str(args["proxy_country_code"]).strip()
        if args.get("timeout_minutes") is not None:
            create_kwargs["timeout"] = int(args["timeout_minutes"])
        if isinstance(args.get("custom_proxy"), dict):
            create_kwargs["customProxy"] = args["custom_proxy"]
        if args.get("browser_screen_width") is not None:
            create_kwargs["browserScreenWidth"] = int(args["browser_screen_width"])
        if args.get("browser_screen_height") is not None:
            create_kwargs["browserScreenHeight"] = int(args["browser_screen_height"])
        if args.get("allow_resizing") is not None:
            create_kwargs["allowResizing"] = bool(args["allow_resizing"])
        if args.get("enable_recording") is not None:
            create_kwargs["enableRecording"] = bool(args["enable_recording"])
        browser = admin.start_remote_daemon(
            name=session_name,
            profile_name=str(args.get("profile_name", "") or "").strip() or None,
            open_live_url=bool(args.get("open_live_url", False)),
            **create_kwargs,
        )
        return {"session_name": session_name, "browser": browser}

    return _wrap_errors("browser_plus_start_remote_daemon", _impl, **kwargs)


def browser_plus_stop_remote_daemon(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)

    def _impl(**_ignored):
        return admin.stop_remote_daemon(session_name)

    return _wrap_errors("browser_plus_stop_remote_daemon", _impl, **kwargs)


def browser_plus_restart_daemon(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    session_name = _session_name(args, **kwargs)

    def _impl(**_ignored):
        return admin.restart_daemon(session_name)

    return _wrap_errors("browser_plus_restart_daemon", _impl, **kwargs)


def browser_plus_search_knowledge(args: dict | None = None, **kwargs) -> str:
    args = args or {}

    def _impl(**_ignored):
        query = str(args.get("query", "") or "")
        kind = str(args.get("kind", "all") or "all")
        limit = max(1, min(int(args.get("limit", 8) or 8), 25))
        return {
            "query": query,
            "kind": kind,
            "matches": search_knowledge(query, kind=kind, limit=limit),
        }

    return _wrap_errors("browser_plus_search_knowledge", _impl, **kwargs)


def browser_plus_read_knowledge(args: dict | None = None, **kwargs) -> str:
    args = args or {}
    path = str(args.get("path", "") or "").strip()
    if not path:
        return tool_error("path is required")

    def _impl(**_ignored):
        payload = read_knowledge(path)
        content = str(payload.get("content", ""))
        max_chars = 20000
        return {
            "path": payload["path"],
            "title": payload["title"],
            "content": content[:max_chars],
            "truncated": len(content) > max_chars,
        }

    return _wrap_errors("browser_plus_read_knowledge", _impl, **kwargs)
