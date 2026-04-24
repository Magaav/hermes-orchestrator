"""CLI and slash commands for the browser-plus plugin."""

from __future__ import annotations

import json
import os

from . import admin, tools


def _cleanup_legacy_browser_sessions() -> None:
    try:
        from tools.browser_tool import cleanup_all_browsers

        cleanup_all_browsers()
    except Exception:
        pass


def _connect_live(url: str) -> dict:
    cdp_url = str(url or "").strip() or "http://127.0.0.1:9222"
    os.environ.pop("BROWSER_PLUS_FORCE_MANAGED_LOCAL", None)
    os.environ["BROWSER_CDP_URL"] = cdp_url
    _cleanup_legacy_browser_sessions()
    restarted = admin.restart_all_daemons()
    return {
        "ok": True,
        "mode": "live",
        "cdp_url": cdp_url,
        "restarted_daemons": restarted.get("sessions", []),
    }


def _connect_local() -> dict:
    os.environ.pop("BROWSER_CDP_URL", None)
    os.environ["BROWSER_PLUS_FORCE_MANAGED_LOCAL"] = "true"
    _cleanup_legacy_browser_sessions()
    restarted = admin.restart_all_daemons()
    started = admin.ensure_local_daemon()
    return {
        "ok": True,
        "mode": "local",
        "restarted_daemons": restarted.get("sessions", []),
        "started_local": started,
    }


def _pair_live_to_local(url: str) -> dict:
    cdp_url = str(url or os.environ.get("BROWSER_CDP_URL", "") or "").strip()
    if not cdp_url:
        raise RuntimeError("A live CDP URL is required. Pass one explicitly or set BROWSER_CDP_URL first.")
    return admin.pair_live_browser_to_local(cdp_url)


def handle_browser_plus_status(raw_args: str) -> str:
    parts = [part for part in (raw_args or "").split() if part]
    args = {"ensure_daemon": True}
    if parts:
        args["session_name"] = parts[0]
    return tools.browser_plus_status(args)


def handle_browser_plus_restart(raw_args: str) -> str:
    parts = [part for part in (raw_args or "").split() if part]
    args = {}
    if parts:
        args["session_name"] = parts[0]
    return tools.browser_plus_restart_daemon(args)


def handle_browser_plus_connect_live(raw_args: str) -> str:
    parts = [part for part in (raw_args or "").split() if part]
    payload = _connect_live(parts[0] if parts else "http://127.0.0.1:9222")
    return json.dumps(payload, ensure_ascii=False)


def handle_browser_plus_connect_local(_raw_args: str) -> str:
    payload = _connect_local()
    return json.dumps(payload, ensure_ascii=False)


def handle_browser_plus_pair_live_to_local(raw_args: str) -> str:
    parts = [part for part in (raw_args or "").split() if part]
    payload = _pair_live_to_local(parts[0] if parts else "")
    return json.dumps(payload, ensure_ascii=False)


def setup_cli(subparser):
    sub = subparser.add_subparsers(dest="browser_plus_command")

    status = sub.add_parser("status", help="Show browser-plus daemon and tab status")
    status.add_argument("--session-name", default="")
    status.add_argument("--no-ensure", action="store_true")

    restart = sub.add_parser("restart", help="Restart a browser-plus daemon")
    restart.add_argument("--session-name", default="")

    tabs = sub.add_parser("tabs", help="List browser-plus tabs")
    tabs.add_argument("--session-name", default="")
    tabs.add_argument("--hide-internal", action="store_true")

    new_tab = sub.add_parser("new-tab", help="Open a new browser-plus tab")
    new_tab.add_argument("url", nargs="?", default="about:blank")
    new_tab.add_argument("--session-name", default="")

    connect_live = sub.add_parser("connect-live", help="Point browser-plus at a live browser CDP endpoint")
    connect_live.add_argument("url", nargs="?", default="http://127.0.0.1:9222")

    connect_local = sub.add_parser("connect-local", help="Use the agent VM's managed local browser")

    pair = sub.add_parser("pair-live-to-local", help="Copy live browser cookies/storage into the managed local browser")
    pair.add_argument("url", nargs="?", default="")

    search = sub.add_parser("search-knowledge", help="Search bundled browser-plus knowledge")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--kind", default="all")
    search.add_argument("--limit", type=int, default=8)

    read = sub.add_parser("read-knowledge", help="Read a bundled browser-plus knowledge file")
    read.add_argument("path")

    start_remote = sub.add_parser("start-remote", help="Start a Browser Use cloud browser plus daemon")
    start_remote.add_argument("--session-name", default="remote")
    start_remote.add_argument("--profile-name", default="")
    start_remote.add_argument("--profile-id", default="")
    start_remote.add_argument("--proxy-country-code", default="")
    start_remote.add_argument("--timeout-minutes", type=int, default=0)
    start_remote.add_argument("--open-live-url", action="store_true")

    stop_remote = sub.add_parser("stop-remote", help="Stop a remote browser-plus daemon")
    stop_remote.add_argument("--session-name", default="remote")

    subparser.set_defaults(func=handle_cli)


def handle_cli(args):
    command = getattr(args, "browser_plus_command", "") or "status"
    if command == "status":
        payload = tools.browser_plus_status(
            {
                "session_name": getattr(args, "session_name", ""),
                "ensure_daemon": not getattr(args, "no_ensure", False),
            }
        )
    elif command == "restart":
        payload = tools.browser_plus_restart_daemon({"session_name": getattr(args, "session_name", "")})
    elif command == "tabs":
        payload = tools.browser_plus_list_tabs(
            {
                "session_name": getattr(args, "session_name", ""),
                "include_internal": not getattr(args, "hide_internal", False),
            }
        )
    elif command == "new-tab":
        payload = tools.browser_plus_new_tab(
            {
                "session_name": getattr(args, "session_name", ""),
                "url": getattr(args, "url", "about:blank"),
            }
        )
    elif command == "connect-live":
        payload = json.dumps(_connect_live(getattr(args, "url", "http://127.0.0.1:9222")), ensure_ascii=False)
    elif command == "connect-local":
        payload = json.dumps(_connect_local(), ensure_ascii=False)
    elif command == "pair-live-to-local":
        payload = json.dumps(_pair_live_to_local(getattr(args, "url", "")), ensure_ascii=False)
    elif command == "search-knowledge":
        payload = tools.browser_plus_search_knowledge(
            {
                "query": getattr(args, "query", ""),
                "kind": getattr(args, "kind", "all"),
                "limit": getattr(args, "limit", 8),
            }
        )
    elif command == "read-knowledge":
        payload = tools.browser_plus_read_knowledge({"path": getattr(args, "path", "")})
    elif command == "start-remote":
        tool_args = {
            "session_name": getattr(args, "session_name", "remote"),
            "profile_name": getattr(args, "profile_name", ""),
            "profile_id": getattr(args, "profile_id", ""),
            "proxy_country_code": getattr(args, "proxy_country_code", ""),
            "open_live_url": bool(getattr(args, "open_live_url", False)),
        }
        timeout = getattr(args, "timeout_minutes", 0)
        if timeout:
            tool_args["timeout_minutes"] = timeout
        payload = tools.browser_plus_start_remote_daemon(tool_args)
    elif command == "stop-remote":
        payload = tools.browser_plus_stop_remote_daemon({"session_name": getattr(args, "session_name", "remote")})
    else:
        payload = json.dumps({"ok": False, "error": f"Unknown browser-plus command: {command}"}, ensure_ascii=False)
    print(payload)
