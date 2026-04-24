---
name: browser-plus-operator
description: Use the browser-plus toolset for live CDP browser automation, Browser Use cloud sessions, and bundled browser-harness knowledge.
---

# browser-plus-operator

Use this skill when the task needs a real browser with CDP, not just a text snapshot.

## Default flow

1. Call `browser_plus_status`.
2. For first navigation, prefer `browser_plus_new_tab`.
3. After navigation, call `browser_plus_wait_for_load`.
4. Use `browser_plus_screenshot` or `browser_plus_extract_text` to re-ground.
5. Interact with `browser_plus_click`, `browser_plus_type_text`, `browser_plus_press_key`, or `browser_plus_eval_js`.
6. If the interaction is tricky, use `browser_plus_search_knowledge` before improvising.
7. Use `browser_plus_cdp` only when a higher-level tool does not cover the needed CDP method.

## Good heuristics

- Browser Plus should first inherit Hermes live-browser settings from `/browser connect`, `BROWSER_CDP_URL`, or `browser.cdp_url`; if none exist, it can use its managed local Chromium fallback.
- Use `browser_plus_new_tab` instead of `browser_plus_goto` when you do not want to overwrite an existing tab.
- If `browser_plus_page_info` reports a dialog, resolve it with `browser_plus_handle_dialog`.
- For upload flows, prefer `browser_plus_upload_file` over synthetic DOM hacks.
- For Browser Use cloud, start with `browser_plus_start_remote_daemon`, and use `browser_plus_sync_local_profile` if login state must be carried over.
