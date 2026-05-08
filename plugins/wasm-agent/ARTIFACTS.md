# WASM Artifacts And Shareability

This is the working design note for componentizing `wasm-agent` without turning
the shipped core into a forked customization layer. The current implementation
only includes the first hooks: Home Artifacts inventory, storage export/import,
device sync installer manifests, Home-only Connected Devices, and client-local
layout policy.

## Product Direction

`wasm-agent` ships fixed foundation artifacts in every fresh client download:
`space-home`, `space-admin`, built-in app/widget definitions, the local account
shell, and embedded agent surfaces. Users then create their own spaces, apps,
widgets, and inner widget entities on top of that foundation.

User-created entities should become portable `wasm-artifacts` that can render
locally, export/import as backups, share directly, publish to a marketplace, and
run from a user's own device or premium server hosting.

Server usage is premium when it stores, hosts, synchronizes, or computes on a
user's behalf. Local client usage stays free and local-first.

## Artifact Model

Every shareable entity should eventually use a manifest envelope:

```json
{
  "schema": "hermes.wasm_agent.artifact.v1",
  "artifact_id": "artifact_x",
  "kind": "space | app-widget | widget-inner-entity | device-sync-installer",
  "title": "Human name",
  "version": "0.1.0",
  "runtime": {
    "component": "wasm-component",
    "entry": "main",
    "permissions": []
  },
  "dependencies": [],
  "storage": {
    "policy": "local-first",
    "cloud_backup": "premium"
  },
  "share": {
    "visibility": "private | direct | marketplace",
    "hosting": "self-device | premium-server"
  }
}
```

The artifact is the shareable unit. Device-specific presentation is not part of
the artifact.

## Device-Local Layout

App positions, widget positions, widget sizes, Space area, and Space distance are
client-local preferences. They should not synchronize across the account by
default because screen size and personal layout taste are device-specific.

The artifact contains semantic structure: which space exists, which apps are in
it, what a widget is, and what inner entities it owns. A device creates its own
layout projection the first time it renders that artifact. Current runtime
layout is browser-local by default under the PWA's local storage key
`wasmAgent.spaceWidgetLayouts.v2`; account-owned space metadata stays under
`state/users/<acc_id>/spaces/<space_id>/space.json`.

## Device Sync

Connected Devices is Home-only. The current Sync action mints and downloads a
device-specific installer manifest:

- schema: `hermes.wasm_agent.device_sync_package.v1`;
- target device id and label;
- current/main device id;
- planned capabilities for registering, reporting online, preparing a tunnel,
  and syncing device state;
- layout policy: `client-local`;
- artifact policy: `shareable-wasm-artifacts`.

This is a bootstrap contract, not a fake tunnel. Later iterations should turn
this package into an installable helper that can bring a device online, open or
request a tunnel, and report reachability back to the Home Devices widget. The
main device is the authority for interface evolution until the user switches it
or brings it back online. The current runtime records the main-device pointer
in account state and exposes a Connected Devices action to switch it quickly.
If the recorded main device is offline, artifact-evolution actions such as
creating spaces and importing storage route the user back to Connected Devices.

## Storage And Premium Boundary

Config exposes local account storage usage and local disk availability. Export
creates a portable JSON backup with account spaces plus the current browser's
local widget layouts. Import restores account space metadata on the server and
restores the layout payload into the current browser only. Server-retained
layout sync, backup, or automation state is a premium feature boundary because
it spends storage/compute and changes the privacy contract.

Future cloud storage should store artifacts and backups only when the user opts
into paid storage. The free path remains local export/import plus direct device
sync.

## Runtime And Plugin Interface

The core `wasm-agent` runtime should expose extension points rather than accept
direct patches for user artifacts:

- artifact registry: import/export/share metadata and dependency resolution;
- component runtime: spawn a wasm-componented runtime for each artifact entry;
- capability broker: grant scoped APIs for storage, network, devices, and UI;
- event bridge: route artifact events to the shell and embedded agent;
- renderer host: mount artifact UI into spaces/widgets without core mutation;
- marketplace adapter: publish, fetch, verify, and hydrate server-hosted
  artifacts.

The existing Hermes Space customware interface under
`/local/plugins/hermes-space-ui/plugin-interface` remains the reference shape:
bundle-owned source, documented seams, and no private runtime patching by
default. `wasm-agent` should mirror that philosophy with a WASM-first artifact
interface.

## Iteration Loop

1. Keep built-in artifacts fixed and boring.
2. Store user-created semantics as artifacts.
3. Store local layout as device preferences.
4. Export/import artifacts locally.
5. Sync devices with an installer/tunnel helper.
6. Add artifact runtime entry points.
7. Add direct sharing.
8. Add marketplace publishing.
9. Add premium server hosting/storage.
