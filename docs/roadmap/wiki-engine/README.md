# `wiki-engine` Track

Status: `Delivered; implementation package path pruned`

## Purpose

Build a production-grade autonomous knowledge engine for Hermes Orchestrator that provides a shared, markdown-native wiki at `/local/wiki/`.

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

1. Node lifecycle and mount topology are owned by `/local/scripts/public/clone/clone_manager.py`.
2. Shared wiki runtime state lives under `/local/wiki/`.
3. Hermes runtime startup and mount behavior is coordinated by the orchestrator lifecycle code.
4. Node opt-in configuration is already expressed through `/local/agents/envs/<node>.env`.
5. Runtime node roots under `/local/agents/nodes/<node>/` are already treated as generated state.
6. Roadmap docs live under `/local/docs/roadmap/`, while feature docs belong under `/local/docs/features/`.
7. Existing plugin tests use Python `unittest`/`pytest` style and live beside plugin code.

### Existing Patterns To Preserve

- Keep shared operational logic in `/local/scripts/public` and standalone plugin roots.
- Keep runtime state outside tracked framework code.
- Use deterministic filesystem contracts under `/local/agents/...`.
- Prefer bootstrap/reapply scripts over brittle edits to upstream Hermes files.
- Preserve disabled-by-default behavior through env gating.

### Original Gap Analysis

At proposal time, the repository did not yet have:

- a shared wiki runtime root
- a wiki bootstrap/self-heal subsystem
- a proposal registry/queue for durable knowledge changes
- a markdown graph compiler
- a query budgeting/compression layer
- a wiki observability pipeline
- tracked feature docs for a knowledge engine

## Frozen Architecture

### Canonical vs Derived

Canonical, durable knowledge:

- markdown pages under `/local/wiki/`
- page history snapshots under `/local/wiki/meta/history/`
- proposal records under `/local/wiki/meta/proposals/`

Derived, rebuildable artifacts:

- graph manifests under `/local/wiki/meta/graph/`
- compression manifests under `/local/wiki/meta/compression/`
- health/lint/observability reports under `/local/wiki/meta/{health_reports,observability,self_heal}/`
- generated routing indexes under `/local/wiki/indexes/`

Reusable, versioned guidance belongs in `/local/docs/...` or a standalone
plugin root if the wiki engine is reintroduced as active source-owned code.

Tracked implementation assets must stay outside the live wiki root.

The live wiki root is intentionally ignored by git because its evolving knowledge is deployment-specific.

### Runtime Topology

Canonical wiki root:

```text
/local/wiki/
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
2. The orchestrator node gets a clean symlink at `/local/agents/nodes/orchestrator/wiki -> /local/wiki`.

### Implementation Boundary

The previous public-plugin package path has been pruned from the active project
tree. Future wiki-engine code should live in a standalone plugin root or another
explicit source-owned package, and this roadmap must be updated in the same
change.

Integration stays explicit:

- `clone_manager.py` handles env gating, worker mount injection, and node workspace symlinks.
- wiki engine code does not patch Hermes-agent internals to function.

## Subsystems

### 1. Bootstrap and Topology

Responsibilities:

- create the shared wiki root and required directories
- seed starter markdown/index/template files from tracked assets when available
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

1. `/local/wiki/` exists and bootstraps itself safely.
2. Active wiki engine code and startup integration live in a documented source-owned package.
3. `NODE_WIKI_ENABLED=true` enables the feature and default behavior remains disabled.
4. Worker nodes receive the shared wiki as a read/write mount and orchestrator gets a clean symlinked view.
5. wiki content is excluded from git while engine code/docs/tests remain tracked.
6. canonical markdown remains the source of truth.
7. graph, index, compression, and observability artifacts rebuild deterministically.
8. proposal governance, moderation, consolidation, trust tiers, and serialized commits work.
9. self-healing restores safe operational state without silently rewriting canonical knowledge.
10. tests cover bootstrap, coordination, graph, self-heal, observability, and retrieval budgeting.

## Delivered

The original delivered implementation shipped as a Hermes-core plugin package.
That package path has since been pruned from the active project tree. Current
durable runtime state remains under `/local/wiki/`.

- worker mount + orchestrator symlink integration is owned by orchestrator lifecycle code
- live wiki runtime content remains ignored under `/local/wiki/`
- any reintroduced engine package must document its active source path here

## Delivered Behavior

### Enablement

- Nodes opt in with `NODE_WIKI_ENABLED=true` in `/local/agents/envs/<node>.env`.
- Disabled nodes remain on the previous behavior and the engine no-ops safely.
- Workers mount `/local/wiki` read/write into the container only when enabled.
- The orchestrator node gets `/local/agents/nodes/orchestrator/wiki -> /local/wiki`.

### Canonical and Derived Layers

- Canonical knowledge remains markdown under `/local/wiki/`.
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

- real bootstrap of `/local/wiki`
- real rebuild of graph/compression/observability artifacts

## Remaining Limitations

- The engine does not hard-block a human with shell access from editing markdown directly; the safety model is mediated by the supported CLI and startup flow.
- Doctrine, AKR, and ECD are intentionally conservative heuristics, not semantic ML classifiers.
- Generated indexes are compact derived routers; they are not intended for hand editing.
