# Hermes Fleet Bundle

Hermes Fleet is the local source mirror for the Space Agent customware bundle that exposes Hermes Orchestrator fleet controls.

Install it by syncing this folder into a writable Space Agent module root such as:

```txt
L1/_all/mod/hermes/fleet/
L1/<team>/mod/hermes/fleet/
L2/<user>/mod/hermes/fleet/
```

The bundle should use Space Agent's native seams:

- `space.bundle.yaml` for metadata and declared actions
- `ext/html` for UI adapters
- `ext/js` and `space.extend(...)` for behavior hooks
- `ext/skills` for agent-facing skills
- `_core/framework/theme/end` for landing or background theme changes
- `space.bundles.actions` for removable browser commands
- `space.bundles.bridge` for Hermes bridge state sync

The minimized-widget app icon behavior is implemented entirely in
`hermes-fleet-ui.js` and `hermes-fleet-ui.css`. It relies on the stable Space
Agent widget card DOM contract plus public `space.spaces.readSpace()` and
`space.spaces.saveSpaceLayout()` calls to compact minimized widgets to a 1x1
button footprint and restore the remembered expanded size when opened. It does
not patch `_core/spaces/*` internals, so the bundle can be reapplied after Space
Agent updates. The browser observer batches card decoration into animation
frames, separates minimized app buttons and expanded widgets into distinct grid
layers, keeps app-button positions as a lightweight overlay preference so
expanded widgets can sit above them, reconciles the drawn app-icon cell back
through `space.spaces.saveSpaceLayout()` before click/drag outcomes depend on
it, adds small press/drag/settle affordances for a native-feeling app-icon
interaction, and removes Space Agent's per-widget reload button from widget
headers.

`space-seed/hermes-fleet/` carries the default `hermes-os` space widgets:

- `Resources Monitor`, which reads live host VM telemetry through `GET /resources`
- `Hermes Topology`, which reads real Hermes Orchestrator nodes through `GET /nodes`, persists node layout in Space Agent user storage, opens node statistics through `GET /nodes/{node_id}/stats`, creates then starts documented node profiles through `POST /nodes`, and opens live message sessions that submit async Runs API tasks, show per-run elapsed time, poll `GET /tasks/{task_id}` for reasoning/tool events copied by the bridge, and cancel active runs through `POST /tasks/{task_id}/stop` when the user presses Stop or closes the modal
- `Drop to Copy`, which submits repository-to-widget jobs through `POST /drop-to-copy/tasks` with an App Name and Instructions, polls `GET /tasks/{task_id}`, and installs generated widgets with the Space Agent widget API

`scripts/start_space_agent.sh` copies these seed files into the Space Agent L2
user space when the space is missing, when `HERMES_SPACE_SEED_FORCE=1`, or when
it detects the old static/fake widget versions. The widget source stays here so
the runtime space can be reapplied after Space Agent checkout updates without
patching Space Agent core files.

Direct runtime injection is intentionally out of scope. If a Hermes feature needs a missing Space Agent seam, add the generic seam upstream and keep the Hermes consumer here.
