# Browser Plus Native Plugin

`browser-plus` is the Hermes-native port of [`browser-use/browser-harness`](./references/browser-harness-README.md).

It keeps the upstream harness's core capability set:

- persistent CDP control of a real Chrome/Edge session
- Browser Use cloud browser provisioning and profile sync
- compositor-level clicks, keyboard input, uploads, screenshots, JS eval, raw CDP
- bundled interaction/domain knowledge from the upstream repository

But it packages that surface as a first-class Hermes plugin so it survives Hermes updates and can be enabled with the normal project-plugin flow.

## Env Contract

- `PLUGIN_BROWSER_PLUS=true|false`
- `BROWSER_USE_API_KEY` optional, only needed for Browser Use cloud/profile tools
- `BROWSER_CDP_URL` optional, shared with Hermes core live-browser support
- `BROWSER_PLUS_LOCAL_CDP_URL` optional, defaults to `http://127.0.0.1:9233` for the managed local browser fallback
- `BROWSER_PLUS_PREFER_GENERIC_BROWSING=true|false` optional, defaults to `true` and biases generic browsing tasks toward `browser-plus`

`PLUGIN_BROWSER_PLUS=true` is the bootstrap intent flag. The prestart bootstrap syncs this plugin into the node runtime at `./.hermes/plugins/browser-plus`, sets `HERMES_ENABLE_PROJECT_PLUGINS=true`, and ensures `browser-plus` is present in `config.yaml` `plugins.enabled`.

No extra secret is required for local real-browser mode.

## Attach Order

`browser-plus` connects to a browser in this order:

1. Hermes live-browser overrides from `/browser connect`, `BROWSER_CDP_URL`, `BU_CDP_URL`, or `BU_CDP_WS`
2. persistent Hermes config at `browser.cdp_url`
3. a locally running Chrome/Edge profile exposing `DevToolsActivePort`
4. a managed local Chromium instance started automatically on `BROWSER_PLUS_LOCAL_CDP_URL`

That means the plugin works out of the box on headless nodes, but it will immediately prefer a user-connected real browser when you provide one.

## Default Routing Bias

At the plugin level, `browser-plus` now biases generic browsing requests toward the `browser_plus_*` toolset by default.

- `BROWSER_PLUS_PREFER_GENERIC_BROWSING=true`:
  generic prompts like "browse this site", "open this URL", or "navigate the internet" should prefer Browser Plus first
- `BROWSER_PLUS_PREFER_GENERIC_BROWSING=false`:
  Browser Plus remains available, but Hermes will be less strongly nudged away from the legacy browser tool path

This is a plugin-level routing preference, not a hard removal of Hermes core browser tools.

## Tool Surface

- `browser_plus_status`
- `browser_plus_goto`
- `browser_plus_page_info`
- `browser_plus_click`
- `browser_plus_type_text`
- `browser_plus_press_key`
- `browser_plus_scroll`
- `browser_plus_screenshot`
- `browser_plus_list_tabs`
- `browser_plus_current_tab`
- `browser_plus_switch_tab`
- `browser_plus_new_tab`
- `browser_plus_ensure_real_tab`
- `browser_plus_wait`
- `browser_plus_wait_for_load`
- `browser_plus_eval_js`
- `browser_plus_dispatch_key`
- `browser_plus_upload_file`
- `browser_plus_http_get`
- `browser_plus_cdp`
- `browser_plus_drain_events`
- `browser_plus_get_dialog`
- `browser_plus_handle_dialog`
- `browser_plus_extract_text`
- `browser_plus_list_cloud_profiles`
- `browser_plus_list_local_profiles`
- `browser_plus_sync_local_profile`
- `browser_plus_start_remote_daemon`
- `browser_plus_stop_remote_daemon`
- `browser_plus_restart_daemon`
- `browser_plus_search_knowledge`
- `browser_plus_read_knowledge`

## Workspace Layout

- `/workspace/browser-plus/files/screenshots/` for generated screenshots
- `/workspace/browser-plus/logs/` for structured JSON operation logs

Daemon runtime state is kept in `/tmp/bp-<session>.sock`, `/tmp/bp-<session>.pid`, and `/tmp/bp-<session>.log`.

## CLI Surface

- `hermes browser-plus status`
- `hermes browser-plus restart`
- `hermes browser-plus tabs`
- `hermes browser-plus new-tab <url>`
- `hermes browser-plus search-knowledge <query>`
- `hermes browser-plus read-knowledge <path>`
- `hermes browser-plus start-remote`
- `hermes browser-plus stop-remote`

## Recommended Flow

1. `browser_plus_status`
2. `browser_plus_new_tab`
3. `browser_plus_wait_for_load`
4. `browser_plus_screenshot` and/or `browser_plus_extract_text`
5. `browser_plus_click`, `browser_plus_type_text`, `browser_plus_press_key`, or `browser_plus_eval_js`
6. `browser_plus_search_knowledge` when the site or interaction gets tricky
7. `browser_plus_cdp` only when the higher-level tools are insufficient

## Hermes Usage

In normal Hermes chats, you do not need to manually call the tool names. Ask Hermes naturally, for example:

- `Open https://example.com in browser-plus, wait for it to load, and tell me what is on the page.`
- `Use browser-plus to log into the site, upload /workspace/file.pdf, and stop before submitting.`
- `Use my live browser tabs with browser-plus and continue from the page that is already open.`

If you want Browser Plus to operate your own desktop Chrome instead of the managed local Chromium fallback, connect Hermes first with `/browser connect http://127.0.0.1:9222` or set `browser.cdp_url`.

## Browser Modes

Browser Plus exposes these plugin-native operator flows:

- `hermes browser-plus connect-live http://127.0.0.1:9222`
  points Browser Plus at your live desktop Chrome and refreshes Browser Plus daemons immediately so the new connection is used on the next step
- `hermes browser-plus connect-local`
  switches Browser Plus back to the agent VM's managed local Chromium browser
- `hermes browser-plus pair-live-to-local [http://127.0.0.1:9222]`
  copies browser state from the specified live browser, or from `BROWSER_CDP_URL` when omitted, into the agent VM browser so you can later use `connect-local` and continue with many cookie-backed sessions already present

The same flows are also exposed as plugin commands:

- `browser-plus-connect-live`
- `browser-plus-connect-local`
- `browser-plus-pair-live-to-local`

Pairing is intentionally limited to web session state:

- copied: cookies, `localStorage`, `sessionStorage` for reachable open-site origins
- not copied: passwords, extensions, history, browser flags, OS keychain state, and some hardware/device-bound auth sessions

## Bundled Knowledge

The plugin ships the upstream `domain-skills/` and `interaction-skills/` trees unchanged under this plugin root. Use:

- `browser_plus_search_knowledge`
- `browser_plus_read_knowledge`

to surface them inside Hermes turns.

Reference copies of the upstream repository docs are kept under [`references/`](./references/).
