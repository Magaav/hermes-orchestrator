# Hermes Space UI Tests

`tests/` contains the local test surface for `/local/plugins/hermes-space-ui`.

## Current Coverage

- `test_routes.py`: route/schema behavior for the Python bridge.

Tests should exercise the bridge boundary and seeded-module assumptions without
patching generated Space Agent state. When server route behavior changes, update
tests and docs together.
