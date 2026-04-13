---
type: index
title: Hermes Shared Wiki
node_id: hermes-shared-wiki
aliases: []
tags: []
related: []
parent: ""
children: []
depends_on: []
used_by: []
sources: []
trust_tier: validated
confidence: 1.0
validation_status: current
last_validated_at: ""
validated_by: []
source_count: 0
updated: 1970-01-01T00:00:00Z
---

## One-Line Summary

Use this root page to route into the canonical shared wiki without broad file scanning.

## Short Summary

The shared wiki keeps durable orchestrator knowledge in markdown, while derived graph and observability artifacts live under `meta/`.

## Details

This wiki is the durable markdown-native knowledge layer for the Hermes Orchestrator fleet.

### Routes

- [Overview Router](indexes/overview.md)
- [Page Template](templates/page.md)
- [Index Template](templates/index.md)

### Operating Rules

- Canonical knowledge lives in markdown under `global/`, `projects/`, and `agents/`.
- Structural changes flow through the wiki engine proposal pipeline.
- Derived artifacts and reports live under `meta/`.
- Runtime content in this wiki is deployment-local and intentionally not tracked by git.

## Related Pages

- [Overview Router](indexes/overview.md)

## Evidence

- Seeded by the Hermes wiki engine bootstrap process.

## Open Questions

- Which project or agent pages should become the highest-traffic routes?
