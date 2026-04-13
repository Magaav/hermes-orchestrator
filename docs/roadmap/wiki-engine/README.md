# `wiki-engine` Track

Status: `Delivered`

## Purpose

Build a production-grade autonomous knowledge engine for Hermes Orchestrator that provides a shared, markdown-native wiki at `/local/agents/private/shared/wiki/`.

The wiki is the durable knowledge layer for the orchestrator fleet:

- markdown-first
- graph-aware
- proposal-governed
- multi-agent safe
- self-healing
- observable
- low-token to query

## Repository Grounding

### Existing Integration Points

The implementation is anchored to the current repository rather than a greenfield design:

1. Node lifecycle and mount topology are owned by `/local/scripts/clone/clone_manager.py` (compatibility alias to `/local/agents/public/scripts/clone/clone_manager.py`).
2. Shared orchestrator plugin code lives under `/local/agents/public/plugins/` (with `/local/plugins` as alias).
3. Hermes-core startup automation already runs through `/local/agents/public/plugins/hermes-core/scripts/prestart_reapply.sh`.
4. Node opt-in configuration is already expressed through `/local/agents/envs/<node>.env`.
5. Runtime node roots under `/local/agents/nodes/<node>/` are already treated as generated state.
6. Roadmap docs live under `/local/docs/roadmap/`, while feature docs belong under `/local/docs/features/`.
7. Existing plugin tests use Python `unittest`/`pytest` style and live beside plugin code.

### Existing Patterns To Preserve

- Keep shared operational logic in `/local/agents/public/scripts` and `/local/agents/public/plugins` (with `/local/scripts` and `/local/plugins` as compatibility aliases).
- Keep runtime state outside tracked framework code.
- Use deterministic filesystem contracts under `/local/agents/...`.
- Prefer bootstrap/reapply scripts over brittle edits to upstream Hermes files.
- Preserve disabled-by-default behavior through env gating.

### Gap Analysis

The repository currently has:

- no shared wiki runtime root
- no wiki bootstrap/self-heal subsystem
- no proposal registry/queue for durable knowledge changes
- no markdown graph compiler
- no query budgeting/compression layer
- no wiki observability pipeline
- no tracked feature docs for a knowledge engine

## Frozen Architecture

### Canonical vs Derived

Canonical, durable knowledge:

- markdown pages under `/local/agents/private/shared/wiki/`
- page history snapshots under `/local/agents/private/shared/wiki/meta/history/`
- proposal records under `/local/agents/private/shared/wiki/meta/proposals/`

Derived, rebuildable artifacts:

- graph manifests under `/local/agents/private/shared/wiki/meta/graph/`
- compression manifests under `/local/agents/private/shared/wiki/meta/compression/`
- health/lint/observability reports under `/local/agents/private/shared/wiki/meta/{health_reports,observability,self_heal}/`
- generated routing indexes under `/local/agents/private/shared/wiki/indexes/`

Tracked implementation assets stay outside the live wiki root:

- engine code under `/local/agents/public/plugins/hermes-core/`
- seed templates under `/local/agents/public/plugins/hermes-core/wiki_seed/`
- tests under `/local/agents/public/plugins/hermes-core/tests/`
- docs under `/local/docs/...`

The live wiki root is intentionally ignored by git because its evolving knowledge is deployment-specific.

### Runtime Topology

Canonical wiki root:

```text
/local/agents/private/shared/wiki/
├── index.md
├── indexes/
├── global/
├── projects/
├── agents/
├── templates/
├── archive/
└── meta/
    ├── compression/
    ├── doctrine_candidates/
    ├── emergence_reports/
    ├── graph/
    ├── health_reports/
    ├── history/
    ├── observability/
    ├── proposals/
    ├── queues/
    ├── refactor_reports/
    └── self_heal/
```

Node integration:

1. Workers mount the host wiki into the container at `/local/wiki` when `NODE_WIKI_ENABLED=true`.
2. The orchestrator node gets a clean symlink at `/local/agents/nodes/orchestrator/wiki -> /local/agents/private/shared/wiki`.
3. Enabled nodes may also get the same node-root symlink for ergonomic access, while `/local/agents/private/shared/wiki` remains canonical.

### Plugin Boundary

The wiki engine is implemented as a self-contained Hermes-core plugin extension:

```text
/local/agents/public/plugins/hermes-core/
├── README.md
├── scripts/
│   ├── prestart_reapply.sh
│   └── wiki_engine.py
├── hermes_wiki/
│   ├── __init__.py
│   ├── bootstrap.py
│   ├── compression.py
│   ├── coordination.py
│   ├── doctrine.py
│   ├── graph.py
│   ├── governance.py
│   ├── markdown.py
│   ├── observability.py
│   ├── query.py
│   ├── self_heal.py
│   └── ...
└── wiki_seed/
    └── ...
```

Integration stays explicit:

- `clone_manager.py` handles env gating, worker mount injection, and node workspace symlinks.
- `prestart_reapply.sh` invokes wiki bootstrap/self-heal for enabled nodes.
- wiki engine code does not patch Hermes-agent internals to function.

## Subsystems

### 1. Bootstrap and Topology

Responsibilities:

- create the shared wiki root and required directories
- seed starter markdown/index/template files from tracked plugin seed assets
- create meta directories and lock files
- restore missing generated directories safely

### 2. Moderation Layer

Responsibilities:

- accept write signals and proposed knowledge payloads
- enforce durable knowledge promotion rules
- reject scratch/debug/chat-like material
- funnel all canonical evolution through governance

### 3. Consolidation Gate

Responsibilities:

- classify each proposed write as `reject`, `update_existing`, `append_subsection`, or `create_new`
- bias toward updating existing pages
- keep page count compact
- recommend future split actions when pages grow too large

### 4. Proposal Governance

Pipeline:

1. detection
2. proposal generation
3. staging
4. evaluation
5. moderation
6. execution

Responsibilities:

- record proposals in `/meta/proposals/`
- persist execution logs and snapshots
- support rollback-aware canonical changes only through the coordinated writer path

### 5. Graph Compiler

Responsibilities:

- parse frontmatter and layered markdown sections
- parse wikilinks/internal links
- normalize aliases and titles
- build nodes, edges, adjacency, alias, and routing manifests
- detect broken references and graph health issues

### 6. Multi-Agent Coordination

Responsibilities:

- accept many proposals
- serialize canonical commits through a single lock-backed writer path
- deduplicate compatible proposals
- order competing proposals deterministically
- keep execution idempotent when retried

### 7. Operational Knowledge Distillation

Responsibilities:

- analyze repeated logs/task outputs/incidents
- emit conservative doctrine candidates only when frequency/evidence thresholds are met
- avoid promoting single-event noise

### 8. Adaptive Knowledge Refactoring

Responsibilities:

- analyze wiki structure for size, duplication, fragmentation, routing drift, and staleness
- emit refactor proposals only
- never directly rewrite canonical knowledge

### 9. Emergent Concept Discovery

Responsibilities:

- detect repeated durable terms/clusters that deserve first-class pages or aliases
- generate emergence reports and proposal candidates
- remain conservative and trust-aware

### 10. Self-Healing

Responsibilities:

- repair safe operational drift
- rebuild missing/corrupt derived artifacts
- restore missing directories/templates/symlinks
- quarantine malformed generated manifests
- fail closed on unsafe canonical write paths

### 11. Observability

Responsibilities:

- emit health metrics, history files, and a normalized health score
- record query efficiency and maintenance signals
- feed safe maintenance triggers without bypassing governance

### 12. Query Budgeting and Compression

Responsibilities:

- maintain summary/compression manifests
- route retrieval through aliases, indexes, summaries, then full pages
- prefer shallow context and 1-2 hop graph traversal
- stop early once the answer budget is satisfied

## Data Flow

### Canonical Write Lifecycle

```text
agent signal
  -> moderation intake
  -> consolidation classification
  -> proposal file
  -> arbitration / ordering / dedupe
  -> locked commit path
  -> page snapshot + atomic write
  -> graph/index/compression rebuild
  -> observability + health log update
```

### Query Lifecycle

```text
query
  -> alias map
  -> root/topical index
  -> one-line summary
  -> short summary
  -> graph neighbors
  -> full page or evidence only if escalation rules require it
```

## Governance and Safety Model

### Single Writer Rule

- Many agents may read and generate proposals.
- Only the coordinated commit path may modify canonical markdown or derived artifacts for a wiki instance.
- File locking plus proposal arbitration are both required.

### Atomicity and Recovery

- canonical writes use temp-file then rename
- modified pages are snapshotted before write
- proposal execution logs are append-only
- retries skip already-executed proposal IDs

### Prompt Injection Boundary

- wiki content is knowledge, not executable instruction
- retrieval must never automatically convert wiki content into trusted commands
- self-heal may rebuild derived artifacts but may not invent or rewrite canonical truth outside governance

## Page Contract

Allowed page types:

- `concept`
- `procedure`
- `decision`
- `incident`
- `entity`
- `source`
- `index`

Required metadata baseline:

- `type`
- `title`
- `aliases`
- `tags`
- `related`
- `parent`
- `children`
- `depends_on`
- `used_by`
- `sources`
- `trust_tier`
- `confidence`
- `validation_status`
- `last_validated_at`
- `updated`

Layered reading contract:

- `## One-Line Summary`
- `## Short Summary`
- `## Details`
- `## Related Pages`
- `## Evidence`
- `## Open Questions`

## Implementation Order (Locked)

1. plugin scaffold
2. wiki topology
3. moderation layer
4. consolidation gate
5. proposal pipeline
6. graph compiler
7. multi-agent coordination
8. doctrine extraction
9. adaptive knowledge refactoring
10. emergent concept discovery
11. self-healing subsystem
12. observability subsystem
13. query budgeting/compression

Spec amendments after this point must be explicit and documented rather than silently changing the design.

## Acceptance Criteria

Delivery is complete only when all of the following are true:

1. `/local/agents/private/shared/wiki/` exists and bootstraps itself safely.
2. `/local/agents/public/plugins/hermes-core/` contains the engine code and startup hook integration.
3. `NODE_WIKI_ENABLED=true` enables the feature and default behavior remains disabled.
4. Worker nodes receive the shared wiki as a read/write mount and orchestrator gets a clean symlinked view.
5. wiki content is excluded from git while engine code/docs/tests remain tracked.
6. canonical markdown remains the source of truth.
7. graph, index, compression, and observability artifacts rebuild deterministically.
8. proposal governance, moderation, consolidation, trust tiers, and serialized commits work.
9. self-healing restores safe operational state without silently rewriting canonical knowledge.
10. tests cover bootstrap, coordination, graph, self-heal, observability, and retrieval budgeting.

## Delivered

Implementation now ships in `/local/agents/public/plugins/hermes-core/` with:

- `hermes_wiki/` runtime modules for bootstrap, governance, graph compilation, maintenance, observability, and query routing
- `scripts/wiki_engine.py` for operational CLI access
- prestart integration in `plugins/hermes-core/scripts/prestart_reapply.sh`
- worker mount + orchestrator symlink integration in `scripts/clone/clone_manager.py`
- ignored live wiki runtime content under `/local/agents/private/shared/wiki/`
- tests under `plugins/hermes-core/tests/test_wiki_engine.py`

## Delivered Behavior

### Enablement

- Nodes opt in with `NODE_WIKI_ENABLED=true` in `/local/agents/envs/<node>.env`.
- Disabled nodes remain on the previous behavior and the engine no-ops safely.
- Workers mount `/local/wiki` read/write into the container only when enabled.
- The orchestrator node gets `/local/agents/nodes/orchestrator/wiki -> /local/agents/private/shared/wiki`.

### Canonical and Derived Layers

- Canonical knowledge remains markdown under `/local/agents/private/shared/wiki/`.
- Graph, compression, health, observability, proposals, and maintenance artifacts are rebuilt under `meta/`.
- Generated routing indexes are rebuilt under `indexes/`.

### Governance

- Writes go through proposal staging, moderation, arbitration, and a locked commit path.
- Existing pages are preferred over new page creation.
- Page snapshots are written before canonical updates.
- Rollback goes through the same governed path using stored snapshots.

### Maintenance

- `doctrine`, `akr`, and `ecd` produce conservative candidates and may optionally stage proposals.
- `self-heal` repairs derived artifacts, missing support directories, and workspace links without silently rewriting canonical knowledge.
- `observe` emits lint reports, time-series metrics, and a health score.

## Verification Notes

Validated with:

- `/local/hermes-agent/.venv/bin/python -m pytest /local/plugins/hermes-core/tests -q`
- real bootstrap of `/local/agents/private/shared/wiki`
- real rebuild of graph/compression/observability artifacts

## Remaining Limitations

- The engine does not hard-block a human with shell access from editing markdown directly; the safety model is mediated by the supported CLI and startup flow.
- Doctrine, AKR, and ECD are intentionally conservative heuristics, not semantic ML classifiers.
- Generated indexes are compact derived routers; they are not intended for hand editing.
