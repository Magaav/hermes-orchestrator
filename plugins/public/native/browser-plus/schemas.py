"""Tool schemas for the browser-plus plugin."""


def _schema(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties or {},
            **({"required": required} if required else {}),
        },
    }


BROWSER_PLUS_STATUS = _schema(
    "browser_plus_status",
    "Inspect the browser-plus session, starting the daemon if needed. Use this first to confirm whether the live CDP browser is attached and which tab is active.",
    {
        "session_name": {"type": "string"},
        "ensure_daemon": {"type": "boolean"},
    },
)

BROWSER_PLUS_GOTO = _schema(
    "browser_plus_goto",
    "Navigate the currently controlled tab to a URL. Prefer browser_plus_new_tab for the first navigation so you do not clobber an existing user tab.",
    {
        "url": {"type": "string"},
        "session_name": {"type": "string"},
    },
    ["url"],
)

BROWSER_PLUS_PAGE_INFO = _schema(
    "browser_plus_page_info",
    "Return the current tab URL, title, viewport, and scroll metrics. If a native dialog is blocking the page, returns dialog details instead.",
    {
        "session_name": {"type": "string"},
    },
)

BROWSER_PLUS_CLICK = _schema(
    "browser_plus_click",
    "Dispatch a compositor-level mouse click at viewport coordinates. This works well across iframes and shadow DOM.",
    {
        "x": {"type": "number"},
        "y": {"type": "number"},
        "button": {"type": "string"},
        "clicks": {"type": "integer"},
        "session_name": {"type": "string"},
    },
    ["x", "y"],
)

BROWSER_PLUS_TYPE_TEXT = _schema(
    "browser_plus_type_text",
    "Insert literal text into the page using CDP input. Use this after focusing the right field.",
    {
        "text": {"type": "string"},
        "session_name": {"type": "string"},
    },
    ["text"],
)

BROWSER_PLUS_PRESS_KEY = _schema(
    "browser_plus_press_key",
    "Dispatch a keyboard key press, optionally with CDP modifier bits. Modifiers: 1=Alt, 2=Ctrl, 4=Meta, 8=Shift.",
    {
        "key": {"type": "string"},
        "modifiers": {"type": "integer"},
        "session_name": {"type": "string"},
    },
    ["key"],
)

BROWSER_PLUS_SCROLL = _schema(
    "browser_plus_scroll",
    "Dispatch a mouse-wheel scroll at viewport coordinates.",
    {
        "x": {"type": "number"},
        "y": {"type": "number"},
        "dy": {"type": "number"},
        "dx": {"type": "number"},
        "session_name": {"type": "string"},
    },
    ["x", "y"],
)

BROWSER_PLUS_SCREENSHOT = _schema(
    "browser_plus_screenshot",
    "Capture a PNG screenshot of the current tab. If no path is supplied, the file is written under /workspace/browser-plus/files/screenshots/.",
    {
        "path": {"type": "string"},
        "full": {"type": "boolean"},
        "session_name": {"type": "string"},
    },
)

BROWSER_PLUS_LIST_TABS = _schema(
    "browser_plus_list_tabs",
    "List browser page targets, including target IDs, titles, URLs, and whether each tab is the currently controlled one.",
    {
        "include_internal": {"type": "boolean"},
        "session_name": {"type": "string"},
    },
)

BROWSER_PLUS_CURRENT_TAB = _schema(
    "browser_plus_current_tab",
    "Return the currently controlled tab from browser-plus.",
    {
        "session_name": {"type": "string"},
    },
)

BROWSER_PLUS_SWITCH_TAB = _schema(
    "browser_plus_switch_tab",
    "Activate a browser tab by target ID and attach browser-plus to it.",
    {
        "target_id": {"type": "string"},
        "session_name": {"type": "string"},
    },
    ["target_id"],
)

BROWSER_PLUS_NEW_TAB = _schema(
    "browser_plus_new_tab",
    "Create a new tab, attach browser-plus to it, and optionally navigate to a URL.",
    {
        "url": {"type": "string"},
        "session_name": {"type": "string"},
    },
)

BROWSER_PLUS_ENSURE_REAL_TAB = _schema(
    "browser_plus_ensure_real_tab",
    "If browser-plus is attached to an internal or stale target, switch to a real browser tab.",
    {
        "session_name": {"type": "string"},
    },
)

BROWSER_PLUS_WAIT = _schema(
    "browser_plus_wait",
    "Sleep for a short number of seconds during a browser workflow.",
    {
        "seconds": {"type": "number"},
    },
)

BROWSER_PLUS_WAIT_FOR_LOAD = _schema(
    "browser_plus_wait_for_load",
    "Poll document.readyState until the current tab reports complete or the timeout expires.",
    {
        "timeout": {"type": "number"},
        "session_name": {"type": "string"},
    },
)

BROWSER_PLUS_EVAL_JS = _schema(
    "browser_plus_eval_js",
    "Evaluate JavaScript in the current tab, or inside a specific target ID after temporarily attaching to it.",
    {
        "expression": {"type": "string"},
        "target_id": {"type": "string"},
        "return_by_value": {"type": "boolean"},
        "await_promise": {"type": "boolean"},
        "session_name": {"type": "string"},
    },
    ["expression"],
)

BROWSER_PLUS_DISPATCH_KEY = _schema(
    "browser_plus_dispatch_key",
    "Dispatch a DOM KeyboardEvent on an element matched by querySelector. Use this when raw CDP key events are not enough.",
    {
        "selector": {"type": "string"},
        "key": {"type": "string"},
        "event": {"type": "string"},
        "session_name": {"type": "string"},
    },
    ["selector"],
)

BROWSER_PLUS_UPLOAD_FILE = _schema(
    "browser_plus_upload_file",
    "Attach one or more local files to a file input selected by querySelector using DOM.setFileInputFiles.",
    {
        "selector": {"type": "string"},
        "path": {
            "oneOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}},
            ]
        },
        "session_name": {"type": "string"},
    },
    ["selector", "path"],
)

BROWSER_PLUS_HTTP_GET = _schema(
    "browser_plus_http_get",
    "Fetch a page or API with plain HTTP instead of the live browser. Good for static pages and bulk requests.",
    {
        "url": {"type": "string"},
        "headers": {"type": "object", "additionalProperties": {"type": "string"}},
        "timeout": {"type": "number"},
    },
    ["url"],
)

BROWSER_PLUS_CDP = _schema(
    "browser_plus_cdp",
    "Send a raw Chrome DevTools Protocol command through the persistent browser-plus daemon.",
    {
        "method": {"type": "string"},
        "params": {"type": "object", "additionalProperties": True},
        "session_id": {"type": "string"},
        "session_name": {"type": "string"},
    },
    ["method"],
)

BROWSER_PLUS_DRAIN_EVENTS = _schema(
    "browser_plus_drain_events",
    "Return and clear the recent CDP event buffer collected by the browser-plus daemon.",
    {
        "session_name": {"type": "string"},
    },
)

BROWSER_PLUS_GET_DIALOG = _schema(
    "browser_plus_get_dialog",
    "Inspect whether a native JavaScript dialog is currently open in the controlled tab.",
    {
        "session_name": {"type": "string"},
    },
)

BROWSER_PLUS_HANDLE_DIALOG = _schema(
    "browser_plus_handle_dialog",
    "Accept or dismiss a native JavaScript dialog, optionally providing prompt text.",
    {
        "accept": {"type": "boolean"},
        "prompt_text": {"type": "string"},
        "session_name": {"type": "string"},
    },
)

BROWSER_PLUS_EXTRACT_TEXT = _schema(
    "browser_plus_extract_text",
    "Extract visible text from the whole page or from a specific element selected by querySelector.",
    {
        "selector": {"type": "string"},
        "max_chars": {"type": "integer"},
        "session_name": {"type": "string"},
    },
)

BROWSER_PLUS_LIST_CLOUD_PROFILES = _schema(
    "browser_plus_list_cloud_profiles",
    "List Browser Use cloud profiles available under the current BROWSER_USE_API_KEY.",
    {},
)

BROWSER_PLUS_LIST_LOCAL_PROFILES = _schema(
    "browser_plus_list_local_profiles",
    "List local browser profiles detected by the profile-use utility.",
    {},
)

BROWSER_PLUS_SYNC_LOCAL_PROFILE = _schema(
    "browser_plus_sync_local_profile",
    "Sync cookies from a local browser profile into Browser Use cloud so a remote browser session can start already logged in.",
    {
        "profile_name": {"type": "string"},
        "browser": {"type": "string"},
        "cloud_profile_id": {"type": "string"},
        "include_domains": {"type": "array", "items": {"type": "string"}},
        "exclude_domains": {"type": "array", "items": {"type": "string"}},
    },
    ["profile_name"],
)

BROWSER_PLUS_START_REMOTE_DAEMON = _schema(
    "browser_plus_start_remote_daemon",
    "Provision a Browser Use cloud browser, attach a browser-plus daemon to it, and return the live session metadata.",
    {
        "session_name": {"type": "string"},
        "profile_name": {"type": "string"},
        "profile_id": {"type": "string"},
        "proxy_country_code": {"type": "string"},
        "timeout_minutes": {"type": "integer"},
        "custom_proxy": {"type": "object", "additionalProperties": True},
        "browser_screen_width": {"type": "integer"},
        "browser_screen_height": {"type": "integer"},
        "allow_resizing": {"type": "boolean"},
        "enable_recording": {"type": "boolean"},
        "open_live_url": {"type": "boolean"},
    },
)

BROWSER_PLUS_STOP_REMOTE_DAEMON = _schema(
    "browser_plus_stop_remote_daemon",
    "Stop a browser-plus remote daemon and request Browser Use cloud to stop billing the backing browser session.",
    {
        "session_name": {"type": "string"},
    },
)

BROWSER_PLUS_RESTART_DAEMON = _schema(
    "browser_plus_restart_daemon",
    "Stop a browser-plus daemon and clean up its socket and pid files so the next tool call can start fresh.",
    {
        "session_name": {"type": "string"},
    },
)

BROWSER_PLUS_SEARCH_KNOWLEDGE = _schema(
    "browser_plus_search_knowledge",
    "Search the bundled browser-harness interaction skills, domain skills, and reference docs that ship with browser-plus.",
    {
        "query": {"type": "string"},
        "kind": {"type": "string"},
        "limit": {"type": "integer"},
    },
)

BROWSER_PLUS_READ_KNOWLEDGE = _schema(
    "browser_plus_read_knowledge",
    "Read one bundled browser-plus knowledge file by the relative path returned from browser_plus_search_knowledge.",
    {
        "path": {"type": "string"},
    },
    ["path"],
)
