# OpenViking Scripts

`/local/scripts/public/openviking` contains source-owned helpers for the
experimental OpenViking memory/retrieval integration.

## Current Scripts

- `openviking_adapter.py`: stdlib HTTP adapter for health, recall, memory
  commit, and context block assembly. It logs to
  `/local/logs/openviking/adapter.log`.
- `openviking_doctor.py`: operational validation suite for a local OpenViking
  service, including health, ingestion, retrieval, reranking, and adapter smoke
  checks.

## Current State

This is an integration helper surface, not the canonical Hermes memory runtime.
`PLUGIN_OPENVIKING` is documented as a naming target while runtime paths may
still use older OpenViking-specific environment variables.
