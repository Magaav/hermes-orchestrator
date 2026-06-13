# Roadmap Context Contract

## Purpose

`docs/roadmap` owns durable plans for work larger than routine operational
changes. It keeps exploratory or multi-step strategy out of the root README
until behavior is real.

## Ownership

- Track documents own problem framing, current status, staged plans, risks,
  verification gates, and durable next actions for their domain.
- The root README owns current project-wide behavior and only the highest-level
  roadmap index.
- Product/runtime READMEs own implemented behavior once a roadmap item ships.

## Local Contracts

- Label future work, proposals, risks, open questions, and partial capability
  honestly. Do not present plans as current software.
- When implementation changes reality, sync the relevant product docs and
  reduce or retire roadmap text that no longer guides work.
- Keep track status compact enough for agents to choose which track to read.

## Work Guidance

- Before starting long evolution work, read `README.md`, then the relevant
  track file, then the owning product/plugin docs.
- Prefer one explicit `Durable Next Step` per active track.
- Avoid copying large logs into roadmap docs. Summarize evidence and point to
  source files or reports.

## Verification

- Roadmap-only edits need a docs consistency pass, not code tests.
- Implementation tied to a roadmap item must cite the focused verification in
  the owning product/plugin docs.

## Child Context Index

- `README.md`: track index, documentation truth invariant, and roadmap
  principles.
- `space-os/README.md`: Space OS and wasm-agent evolution track.
- `guard/README.md`: host doctor/guard remediation track.
- `wiki-engine/README.md`: durable wiki engine track.
- `hermes-plugin-extension-points/README.md`: upstream Hermes extension seam
  proposal.
