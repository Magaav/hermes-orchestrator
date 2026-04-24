# Browser Plus Model Guide

Use `browser-plus` when the task needs a live CDP browser, real logged-in tabs, uploads, raw DevTools control, or Browser Use cloud browsers.

Recommended sequence:

1. `browser_plus_status`
2. `browser_plus_new_tab`
3. `browser_plus_wait_for_load`
4. `browser_plus_screenshot` and/or `browser_plus_extract_text`
5. `browser_plus_click`, `browser_plus_type_text`, `browser_plus_press_key`, `browser_plus_eval_js`
6. `browser_plus_search_knowledge` when the site or interaction is unfamiliar
7. `browser_plus_cdp` only as the escape hatch

Notes:

- Browser Plus first honors `/browser connect`, `BROWSER_CDP_URL`, and `browser.cdp_url`; if none are set, it can fall back to a managed local Chromium session automatically.
- First navigation should usually be `browser_plus_new_tab`, not `browser_plus_goto`.
- `browser_plus_click` is coordinate-based and works well across iframes/shadow DOM.
- `browser_plus_upload_file` expects local absolute or cwd-relative paths.
- `browser_plus_handle_dialog` is the right fix when `browser_plus_page_info` reports a dialog.
- `browser_plus_start_remote_daemon` is the path for Browser Use cloud sessions.
