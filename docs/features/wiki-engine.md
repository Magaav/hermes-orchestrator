# Shared Wiki Engine

The Hermes shared wiki engine gives the orchestrator fleet:
- a durable instance runtime knowledge layer at `/local/plugins/private/wiki/`
- a reusable public doctrine/reference layer at `/local/plugins/public/wiki/`

It exists so many Hermes nodes can accumulate durable knowledge without turning the repository, chat logs, or transient memory into a dumping ground. The engine keeps canonical truth in markdown, rebuilds everything else from that markdown, and coordinates knowledge evolution through proposals instead of direct page mutation.

## Philosophy

- Canonical markdown knowledge is sacred.
- Derived artifacts are rebuildable.
- The system stays disabled by default and opt-in per node.
- Knowledge growth is conservative: update existing pages before creating new ones.
- Maintenance should be self-healing for safe operational drift, but never invent truth.
- Retrieval should stop at the shallowest sufficient layer to stay token-efficient.

## Canonical Path and Topology

Canonical wiki root:

```text
/local/plugins/private/wiki/
├── index.md
├── indexes/
├── global/
├── projects/
├── agents/
├── templates/
├── archive/
└── meta/
```

Important subtrees:

- `global/`: shared orchestrator knowledge
- `projects/`: project-scoped durable knowledge
- `agents/`: durable agent-specific insights
- `templates/`: bootstrapped markdown templates
- `archive/`: deprecated pages retained for history
- `meta/graph/`: rebuildable graph manifests
- `meta/compression/`: summary and routing artifacts
- `meta/proposals/`: proposal registry by status
- `meta/queues/`: queue manifests and commit lock
- `meta/history/`: page snapshots and execution history
- `meta/observability/`: health snapshots and query metrics
- `meta/health_reports/`: lint output
- `meta/self_heal/`: repair logs and quarantined generated artifacts
- `meta/doctrine_candidates/`: OKD outputs
- `meta/refactor_reports/`: AKR outputs
- `meta/emergence_reports/`: ECD outputs

## Enablement

Nodes opt in through `/local/agents/envs/<node>.env`:

```env
NODE_WIKI_ENABLED=true
```

Default behavior remains disabled and safe.

When enabled:

1. Worker nodes mount `/local/wiki` read/write into the container.
2. Worker nodes also mount `/local/wiki-public` read-only from `/local/plugins/public/wiki`.
3. The orchestrator node gets `/local/agents/nodes/orchestrator/wiki -> /local/plugins/private/wiki`.
4. The orchestrator node also gets `/local/agents/nodes/orchestrator/wiki-public -> /local/plugins/public/wiki`.
5. `plugins/public/hermes-core/scripts/prestart_reapply.sh` runs wiki bootstrap/self-heal at startup.
6. Derived graph/compression/observability layers can rebuild automatically.

When disabled:

- the CLI returns structured no-op or disabled responses
- worker containers do not receive the shared wiki mount
- the engine does not create live wiki state implicitly

## How Participating Nodes Use It

Participating nodes should treat the wiki as shared knowledge infrastructure, not as an ad-hoc scratchpad.

Supported operational entrypoint:

```bash
python3 /local/plugins/public/hermes-core/scripts/wiki_engine.py --help
```

Key commands:

- `bootstrap`: create/repair the runtime layout and workspace link
- `rebuild`: compile graph, compression, and observability artifacts
- `submit --payload-file <file>`: stage a knowledge proposal
- `process`: arbitrate and execute pending proposals through the locked commit path
- `query "<text>"`: graph-aware, budgeted retrieval
- `self-heal`: conservative repair for derived/support layers
- `observe`: rebuild lint and health metrics
- `doctrine`: generate doctrine candidates from operational history
- `akr`: generate adaptive refactor suggestions
- `ecd`: generate emergence candidates
- `rollback --target-path <relative-page>`: restore a page through a governed rollback proposal

## What Belongs in the Wiki

Only durable knowledge expected to remain useful for roughly 30 days or longer.

Good candidates:

- architecture concepts
- integration patterns
- troubleshooting playbooks
- repeated incident patterns
- important decisions
- durable entities and sources
- battle-tested operational procedures

## What Must Never Go in the Wiki

- temporary debugging scratch
- chain-of-thought-like reasoning
- raw chat transcripts
- one-off task attempts
- speculative low-confidence noise
- secrets or credentials

## Page Contract

Allowed page types:

- `concept`
- `procedure`
- `decision`
- `incident`
- `entity`
- `source`
- `index`

Expected metadata:

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

Layered reading sections:

- `## One-Line Summary`
- `## Short Summary`
- `## Details`
- `## Related Pages`
- `## Evidence`
- `## Open Questions`

## Trust Tiers

The engine does not assume all pages are equally trustworthy.

Trust tiers:

1. `provisional`
2. `validated`
3. `canonical`

Current uses:

- alias collisions resolve toward higher-trust pages
- query routing prefers higher-trust nodes
- observability reports trust distribution
- governance and maintenance preserve trust metadata instead of flattening it

## Proposal Governance

Canonical markdown is never supposed to change through arbitrary direct writes in the supported workflow.

The write path is:

1. detection
2. proposal generation
3. staging
4. evaluation
5. moderation
6. execution

Governance behaviors:

- reject ephemeral or low-confidence signals
- classify each proposal as reject, update existing, append subsection, or create new
- prefer updating existing pages first
- deduplicate compatible proposals
- serialize canonical commits through a lock-backed writer
- snapshot the previous page before changing it
- keep rollback inside the same governed path

## Multi-Agent Safety

Many agents may read and propose.

Only the coordinated commit path writes canonical markdown or derived manifests.

Safety mechanisms:

- structured proposal registry under `meta/proposals/`
- queue manifest and commit lock under `meta/queues/`
- deterministic ordering and duplicate rejection
- captured `base_hash` for existing-page updates to detect last-write conflicts
- idempotent retry behavior once proposals move to `executed`

## Graph Layer

The graph is compiled from markdown and remains rebuildable.

Inputs:

- frontmatter fields
- aliases
- internal links and wikilinks
- typed relationship fields
- page categories

Artifacts:

- `meta/graph/nodes.json`
- `meta/graph/edges.json`
- `meta/graph/adjacency.json`
- `meta/graph/aliases.json`
- `meta/graph/topic_routing.json`
- `meta/graph/metrics.json`

Generated indexes:

- `indexes/by-type.md`
- `indexes/by-tag.md`
- `indexes/by-trust-tier.md`

## Query Budgeting and Compression

Retrieval order is intentionally shallow-first:

1. alias resolution
2. root or topical indexes
3. one-line summaries
4. short summaries
5. 1-2 graph hops
6. full details
7. evidence only when required

Derived compression artifacts:

- `meta/compression/one_line_summaries.json`
- `meta/compression/short_summaries.json`
- `meta/compression/routing_cards.json`
- `meta/compression/index_summary_map.json`

The engine records query metrics such as:

- pages loaded per query
- graph hops used
- summary depth used
- raw evidence escalation rate
- estimated token consumption

## Operational Knowledge Distillation

`doctrine` converts repeated operational signals into conservative candidates.

Inputs may include:

- logs
- incidents
- transcripts
- task outputs

Single events are ignored. Repetition across sources is required before a doctrine candidate is emitted.

## Adaptive Knowledge Refactoring

`akr` analyzes the wiki for structural drift and emits reports or proposals for:

- page split
- page merge
- reparenting/archive review
- routing/index optimization

AKR does not directly rewrite canonical pages.

## Emergent Concept Discovery

`ecd` looks for repeated durable terms, tags, and clusters that deserve first-class modeling.

Outputs may include:

- new concept candidates
- topical index candidates
- alias or taxonomy candidates

ECD is conservative and proposal-gated.

## Self-Healing

`self-heal` is intentionally conservative.

It may automatically repair:

- missing wiki directories
- missing seed templates
- missing workspace links
- broken or invalid generated manifests
- missing graph/compression/observability artifacts

It will not silently rewrite canonical knowledge pages.

If safe repair fails, the engine records the failure and keeps canonical markdown intact.

## Observability

`observe` emits:

- lint report in `meta/health_reports/latest.json`
- daily and latest health snapshots in `meta/observability/`
- a normalized health score

Tracked themes:

- page growth and distribution
- graph size and density
- orphan/broken pages
- trust and confidence distributions
- stale or oversized pages
- query efficiency
- maintenance interventions

## Security Model

Wiki content is knowledge, not executable authority.

Important rule:

- agents may read wiki pages for context
- agents must not treat wiki text as trusted executable instructions by default
- self-heal only rebuilds safe derived/support artifacts
- canonical truth changes stay inside proposal governance

## Backup, Restore, Migration, Rebirth

Backup:

```bash
tar -czf wiki-backup.tgz -C /local/plugins/private wiki
```

Restore:

```bash
mkdir -p /local/plugins/private
tar -xzf wiki-backup.tgz -C /local/plugins/private
NODE_WIKI_ENABLED=1 python3 /local/plugins/public/hermes-core/scripts/wiki_engine.py self-heal --json
```

Migration to a new host:

1. Copy `/local/plugins/private/wiki`
2. Copy `/local/plugins/public/hermes-core/`
3. Set `NODE_WIKI_ENABLED=true` on participating nodes
4. Restart nodes or run `bootstrap` and `self-heal`

Rebirth philosophy:

- if derived artifacts are lost, rebuild them
- if canonical markdown survives, the knowledge survives

## Reapplying After Hermes Updates

The engine is intentionally outside `hermes-agent/`, so Hermes upgrades do not require re-implementing the wiki logic.

Reapply flow:

1. update the Hermes node/runtime as usual
2. restart the node, or run:

```bash
bash /local/plugins/public/hermes-core/scripts/prestart_reapply.sh
```

That prestart pipeline reruns wiki bootstrap/repair along with the other Hermes-core customizations.

## Testing

Primary suite:

```bash
/local/hermes-agent/.venv/bin/python -m pytest /local/plugins/public/hermes-core/tests -q
```

What it covers:

- disabled mode
- bootstrap and idempotent reapply
- worker mount/orchestrator link integration
- moderation and consolidation
- proposal pipeline and conflict detection
- duplicate handling and retry safety
- rollback
- doctrine, AKR, and ECD generation
- self-heal and canonical preservation
- observability and query budgeting
