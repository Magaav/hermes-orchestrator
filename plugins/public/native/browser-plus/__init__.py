"""Hermes-native browser-plus plugin."""

from __future__ import annotations

from pathlib import Path

from . import cli, hooks, schemas, tools


def register(ctx):
    ctx.register_hook("pre_llm_call", hooks.inject_browser_plus_turn_context)

    registrations = [
        (
            "browser_plus_status",
            schemas.BROWSER_PLUS_STATUS,
            tools.browser_plus_status,
            "Inspect the active browser-plus daemon and current tab state.",
        ),
        (
            "browser_plus_goto",
            schemas.BROWSER_PLUS_GOTO,
            tools.browser_plus_goto,
            "Navigate the currently attached tab to a URL.",
        ),
        (
            "browser_plus_page_info",
            schemas.BROWSER_PLUS_PAGE_INFO,
            tools.browser_plus_page_info,
            "Get page URL, title, viewport, and scroll information.",
        ),
        (
            "browser_plus_click",
            schemas.BROWSER_PLUS_CLICK,
            tools.browser_plus_click,
            "Click viewport coordinates using compositor-level CDP mouse events.",
        ),
        (
            "browser_plus_type_text",
            schemas.BROWSER_PLUS_TYPE_TEXT,
            tools.browser_plus_type_text,
            "Insert literal text into the currently focused element.",
        ),
        (
            "browser_plus_press_key",
            schemas.BROWSER_PLUS_PRESS_KEY,
            tools.browser_plus_press_key,
            "Dispatch a keyboard key press with optional modifiers.",
        ),
        (
            "browser_plus_scroll",
            schemas.BROWSER_PLUS_SCROLL,
            tools.browser_plus_scroll,
            "Scroll the page using a wheel event at viewport coordinates.",
        ),
        (
            "browser_plus_screenshot",
            schemas.BROWSER_PLUS_SCREENSHOT,
            tools.browser_plus_screenshot,
            "Capture a PNG screenshot of the current tab.",
        ),
        (
            "browser_plus_list_tabs",
            schemas.BROWSER_PLUS_LIST_TABS,
            tools.browser_plus_list_tabs,
            "List browser page targets and the current active tab.",
        ),
        (
            "browser_plus_current_tab",
            schemas.BROWSER_PLUS_CURRENT_TAB,
            tools.browser_plus_current_tab,
            "Get the currently controlled tab.",
        ),
        (
            "browser_plus_switch_tab",
            schemas.BROWSER_PLUS_SWITCH_TAB,
            tools.browser_plus_switch_tab,
            "Activate a tab and attach browser-plus to it.",
        ),
        (
            "browser_plus_new_tab",
            schemas.BROWSER_PLUS_NEW_TAB,
            tools.browser_plus_new_tab,
            "Create a new tab, attach browser-plus to it, and optionally navigate.",
        ),
        (
            "browser_plus_ensure_real_tab",
            schemas.BROWSER_PLUS_ENSURE_REAL_TAB,
            tools.browser_plus_ensure_real_tab,
            "Recover from stale/internal targets by switching to a real page tab.",
        ),
        (
            "browser_plus_wait",
            schemas.BROWSER_PLUS_WAIT,
            tools.browser_plus_wait,
            "Sleep for a short time during a browser workflow.",
        ),
        (
            "browser_plus_wait_for_load",
            schemas.BROWSER_PLUS_WAIT_FOR_LOAD,
            tools.browser_plus_wait_for_load,
            "Wait until document.readyState becomes complete.",
        ),
        (
            "browser_plus_eval_js",
            schemas.BROWSER_PLUS_EVAL_JS,
            tools.browser_plus_eval_js,
            "Evaluate JavaScript in the current page or a specific target.",
        ),
        (
            "browser_plus_dispatch_key",
            schemas.BROWSER_PLUS_DISPATCH_KEY,
            tools.browser_plus_dispatch_key,
            "Dispatch a DOM KeyboardEvent to a selected element.",
        ),
        (
            "browser_plus_upload_file",
            schemas.BROWSER_PLUS_UPLOAD_FILE,
            tools.browser_plus_upload_file,
            "Attach local files to a file input selected by querySelector.",
        ),
        (
            "browser_plus_http_get",
            schemas.BROWSER_PLUS_HTTP_GET,
            tools.browser_plus_http_get,
            "Fetch a page with plain HTTP instead of the live browser.",
        ),
        (
            "browser_plus_cdp",
            schemas.BROWSER_PLUS_CDP,
            tools.browser_plus_cdp,
            "Send a raw CDP command through the persistent browser-plus daemon.",
        ),
        (
            "browser_plus_drain_events",
            schemas.BROWSER_PLUS_DRAIN_EVENTS,
            tools.browser_plus_drain_events,
            "Read and clear the recent daemon event buffer.",
        ),
        (
            "browser_plus_get_dialog",
            schemas.BROWSER_PLUS_GET_DIALOG,
            tools.browser_plus_get_dialog,
            "Inspect a pending native JavaScript dialog.",
        ),
        (
            "browser_plus_handle_dialog",
            schemas.BROWSER_PLUS_HANDLE_DIALOG,
            tools.browser_plus_handle_dialog,
            "Accept or dismiss a native JavaScript dialog.",
        ),
        (
            "browser_plus_extract_text",
            schemas.BROWSER_PLUS_EXTRACT_TEXT,
            tools.browser_plus_extract_text,
            "Extract visible text from the whole page or a selected element.",
        ),
        (
            "browser_plus_list_cloud_profiles",
            schemas.BROWSER_PLUS_LIST_CLOUD_PROFILES,
            tools.browser_plus_list_cloud_profiles,
            "List Browser Use cloud profiles under the current API key.",
        ),
        (
            "browser_plus_list_local_profiles",
            schemas.BROWSER_PLUS_LIST_LOCAL_PROFILES,
            tools.browser_plus_list_local_profiles,
            "List local browser profiles via profile-use.",
        ),
        (
            "browser_plus_sync_local_profile",
            schemas.BROWSER_PLUS_SYNC_LOCAL_PROFILE,
            tools.browser_plus_sync_local_profile,
            "Sync a local browser profile into Browser Use cloud.",
        ),
        (
            "browser_plus_start_remote_daemon",
            schemas.BROWSER_PLUS_START_REMOTE_DAEMON,
            tools.browser_plus_start_remote_daemon,
            "Provision a Browser Use cloud browser and attach browser-plus to it.",
        ),
        (
            "browser_plus_stop_remote_daemon",
            schemas.BROWSER_PLUS_STOP_REMOTE_DAEMON,
            tools.browser_plus_stop_remote_daemon,
            "Stop a browser-plus remote daemon and its backing Browser Use session.",
        ),
        (
            "browser_plus_restart_daemon",
            schemas.BROWSER_PLUS_RESTART_DAEMON,
            tools.browser_plus_restart_daemon,
            "Stop a daemon and clean up socket state so the next call starts fresh.",
        ),
        (
            "browser_plus_search_knowledge",
            schemas.BROWSER_PLUS_SEARCH_KNOWLEDGE,
            tools.browser_plus_search_knowledge,
            "Search bundled browser-harness interaction and domain knowledge.",
        ),
        (
            "browser_plus_read_knowledge",
            schemas.BROWSER_PLUS_READ_KNOWLEDGE,
            tools.browser_plus_read_knowledge,
            "Read one bundled browser-plus knowledge file by relative path.",
        ),
    ]

    for name, schema, handler, description in registrations:
        ctx.register_tool(
            name=name,
            toolset="browser-plus",
            schema=schema,
            handler=handler,
            description=description,
        )

    ctx.register_command(
        "browser-plus-status",
        handler=cli.handle_browser_plus_status,
        description="Show browser-plus status for the current or named session.",
    )
    ctx.register_command(
        "browser-plus-restart",
        handler=cli.handle_browser_plus_restart,
        description="Restart a browser-plus daemon for the current or named session.",
    )
    ctx.register_command(
        "browser-plus-connect-live",
        handler=cli.handle_browser_plus_connect_live,
        description="Refresh browser-plus onto a live browser CDP endpoint.",
    )
    ctx.register_command(
        "browser-plus-connect-local",
        handler=cli.handle_browser_plus_connect_local,
        description="Switch browser-plus to the agent VM's managed local browser.",
    )
    ctx.register_command(
        "browser-plus-pair-live-to-local",
        handler=cli.handle_browser_plus_pair_live_to_local,
        description="Copy cookies and web storage from a live browser into the managed local browser.",
    )
    ctx.register_cli_command(
        name="browser-plus",
        help="Manage the browser-plus native plugin",
        setup_fn=cli.setup_cli,
        handler_fn=cli.handle_cli,
        description="Browser Use browser-harness port for Hermes.",
    )

    skills_dir = Path(__file__).parent / "skills"
    skill_md = skills_dir / "browser-plus-operator" / "SKILL.md"
    if skill_md.exists():
        ctx.register_skill(
            "browser-plus-operator",
            skill_md,
            description="Workflow guidance for the browser-plus toolset.",
        )
