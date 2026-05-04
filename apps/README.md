# Apps

`/local/apps` is retained as a historical top-level application surface, but
there are no active source-owned apps in this repo snapshot.

## Current Apps

None.

## Boundaries

New product UI work should live under `/local/plugins` unless there is a clear
reason to add a separate application root. The active Space UI direction is
`/local/plugins/hermes-space-ui`.

The retired browser UI demo is deprecated and must not be revived as the Space
OS path. Future WASM/browser-runtime work is tracked in
`/local/docs/roadmap/space-os/README.md` and should be implemented through
Hermes Space UI plugin/module surfaces first.
