# Hermes Space UI Server

`server/` owns the Python bridge used by `/local/plugins/hermes-space-ui`.

## Current Responsibilities

- `bridge.py`: ASGI entrypoint for the local Hermes Space UI bridge.
- `routes.py`: HTTP routes for health, fleet/node state, logs, actions, prompt
  submission, browser-oriented helper prompts, and host resource summaries.
- `schemas.py`: JSON schema helpers for bridge responses.
- `auth.py`: bearer-token auth helpers used when token protection is enabled.

The bridge routes Hermes Space UI requests through the orchestrator CLI/API
boundary. It must not import Hermes Agent internals or patch Space Agent core.

## Documentation Sync

When routes, response shapes, auth behavior, or orchestrator command boundaries
change, update this README and the plugin root README in the same change.
