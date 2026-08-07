# User-Authorized Windows Browser Bridge

The user can intentionally expose Windows Chrome to the active development
environment by running the browser-sharing bridge and keeping its terminal
open.

## Available endpoints

- Cloud reverse tunnel: `http://127.0.0.1:9222`
- WSL direct endpoint: `http://172.18.16.1:9222`

An endpoint is available only when `GET /json/version` succeeds. Prefer the
endpoint reachable from the current environment; do not treat one unavailable
route as evidence that the other route is unavailable.

## Authorization

When the user starts the bridge and explicitly asks Codex to inspect, operate,
watch, or verify Chrome, Codex may use the available CDP endpoint freely for
that requested workflow. This includes inspecting and interacting with the
relevant existing product tab when that is necessary to fulfill the request.

Keep access bounded to the user-authorized task:

- use the relevant WASM Agent or product target;
- avoid unrelated tabs, accounts, messages, and browsing data;
- do not broaden read access beyond what the requested proof requires;
- do not submit, publish, purchase, delete, or perform another consequential
  action unless the user requested that action;
- close targets created solely for proof when the proof finishes;
- report whether automation completed, failed, or was interrupted.

The open sharing terminal is transport availability, not blanket authorization
for unrelated future tasks. Each browser task still requires user intent in the
conversation.

## Connection proof

Before browser automation:

1. Request `/json/version` from the selected endpoint.
2. Record the reported browser and protocol versions when runtime proof matters.
3. Connect through CDP and select only the target required by the authorized
   workflow.

Do not route production application behavior to the CDP endpoint. It is a
development and verification transport only.
