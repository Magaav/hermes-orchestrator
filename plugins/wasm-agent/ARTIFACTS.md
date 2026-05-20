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

WIS adds a narrower first proof of this direction with
`hermes.wasm_agent.wis.space.v1`: a portable local document/app definition that
contains a DOM-like tree, initial state, sandbox permissions, and navigation
metadata. The current WIS export also includes runtime document state so a
small interactive surface can be shared or restored without a backend or iframe.
This is a substrate proof, not the final artifact envelope.

`hermes.wasm_agent.wis.patch.v1`: a validated userland mutation envelope for
changing WIS artifacts without granting source-file access. It can set artifact
title/state, edit node text/props/actions, add/remove/replace nodes, and add
documents inside account-owned or joined shared-space artifact storage. Embedded
agent patch blocks omit `space_id` for the current space; the adapter resolves
placeholder current-space ids to the active wasm-agent space. The adapter
accepts fenced blocks, `<wis-patch>` blocks, and raw JSON only when the object
parses as the exact WIS patch schema; `add_document` may carry a sanitized
document tree that renders immediately in the WIS widget.

`hermes.wasm_agent.wis.wasm_engine.v1`: the browser-local WIS WASM
microkernel embedded with the WIS engine. It does not grant network, file, or
iframe access; it provides deterministic artifact metrics, layout planning, and
media capability planning so generated artifacts can execute against a real
WASM runtime while the JS shell owns DOM events and safe browser integration.
`public/modules/wis/artifacts/camera.js` owns the portable camera artifact
factory and `hermes.wasm_agent.wis.camera_controller.v1` controller contract, so
focused camera artifacts can be generated or shared without copying host-shell
`app.js` code.
For camera artifacts, the current product shape is one WIS artifact per physical
camera. A focused camera artifact stores a single `state.cameras` entry plus a
`camera_focus` marker, and the widget renders that camera full-width without the
WIS inspector side panel, location bar, sandbox chip, or in-surface action row.
The focused shell stays one row on compact screens, the widget height follows
the camera frame aspect ratio, and camera setup lives in the WIS header config
button. The no-backend path supports local
`getUserMedia` cameras and browser-playable HTTP(S) media URLs. Client-local URL
secrets are kept out of the persisted artifact state; artifact-level RTMP push
sources take precedence over stale browser-local camera credentials from older
experiments.
RTSP is classified as needing a relay or publisher because browser WASM cannot
open raw RTSP sockets. Intelbras DVR/NVR
setup is a client-local helper with a credentials-first profile: the user enters
host, username, password, channel, and subtype once, the browser stores the
secret URL locally, and the default render path uses the true Intelbras RTSP
`/cam/realmonitor` feed. New RTSP configs default to subtype `0` (main stream)
and ask for the RTSP/tunnel port reachable from the wasm-agent server. The
browser posts the secret URL to `/camera/rtsp-frame`; the backend first checks
that the RTSP host/port is reachable from wasm-agent, then uses `ffmpeg` with
RTSP TCP transport and the RTSP demuxer's socket timeout to decode one current
RTSP frame into browser-playable JPEG bytes before the WIS image updates. The
recovery panel can also call `/camera/diagnostics`, a short server-side TCP
check plus route/source hint for the configured RTSP/HTTP/HTTPS DVR targets, to
verify that wasm-agent can reach the DVR/tunnel before retrying decode and
identify different-private-LAN/VPN routing blockers. Tunnel-style `host:port`
values are parsed into a real host and RTSP port before checks run. The same
route hint is attached to RTSP frame and stream preflight failures so the
artifact can surface the exact network/tunnel blocker inline. Snapshot fallbacks
that auto-promote back to the true RTSP feed preserve the saved RTSP/tunnel port
instead of silently returning to `554`, while direct HTTP snapshot/portal
recovery and portal-open actions strip RTSP tunnel ports and use HTTP recovery
ports. Stale saved portal URLs that point at RTSP tunnel ports are ignored and
regenerated as HTTP-safe portal origins. If the selected realmonitor subtype fails, the proxy checks the alternate subtype before
returning a diagnostic. If no frame arrives, the frame is all black, the
selected channel/subtype is unreachable, or the DVR/tunnel host cannot be
reached from wasm-agent, the artifact renders a diagnostic instead of a black
camera pane. The older
`/camera/rtsp-session` plus `/camera/rtsp-stream?token=...` multipart relay
remains available, but the WIS camera card favors verified frame polling for
cam1 because it can distinguish real pixels from an empty pipe. Recovery actions
can reuse the same local secrets for direct snapshot polling, portal capture,
HTTP(S) MJPEG, a reachability check plus immediate RTSP retry after a
tunnel/network change, or the standard RTSP relay. Secret URLs still live only in
browser-local camera config and are sent to the backend only for the explicit
stream or snapshot relay request. Direct Intelbras snapshot configs with local
credentials promote to the matching RTSP realmonitor source so a black still
frame is not treated as success; snapshot configs without local credentials
still auto-promote to the snapshot relay on HTTPS pages instead of asking the
user to downgrade wasm-agent to HTTP.
For DVRs that support outbound RTMP, WIS also supports a DVR-push source. The
browser asks wasm-agent to start an ffmpeg RTMP listener, stores the returned
`rtmp://<host>:<port>/live/<stream-key>` URL only in local camera config, and
renders the live view by preloading the latest server-side JPEG frame from
`/camera/push-frame?stream_id=<id>` before swapping it into the visible image.
That keeps the last good frame on screen through short ingest/browser hiccups.
The camera widget header exposes only zoom, snapshot copy, audio, and
principal/extra quality controls. Its full-width footer timeline defaults to the
last 10 minutes and can switch to a detected recorded-footage range from
`/camera/push-timeline`; selected points acquire recorded playback ownership,
freeze the last good media frame, and swap only after a decoded frame from the
latest `/camera/push-playback` generation is ready. `/camera/push-archive-frame`
remains the fallback when the playback stream cannot open. The recorded playback
path keeps one active reader/scheduler per stream generation, skips repeat
same-frame applies, and reports aggregate `camera.perf.sample` diagnostics
instead of noisy per-frame logs by default. Regression coverage now includes six
rapid recorded seeks settling to the latest generation and live return clearing
active playback loops/readers. The footer loads its timeline data when it renders
and on direct footer interaction, so the scrubber does not depend on a separate
widget focus click. It is scoped to the active WIS camera widget and keeps
pointer tracking across drag/release transitions so scrubbing can commit an
earlier retained frame instead of falling back to the live view. A click made
before the timeline frames finish loading is stored as a pending seek and
applied to the nearest retained frame when `/camera/push-timeline` returns.
Scrubber controls own their click/drag loading path, so the footer does not
start an eager parent reload that can replace the scrubber before release. The
client loads timeline metadata through JSON `POST /camera/push-timeline`, while
the GET endpoint remains for compatibility, to avoid stale service workers
serving the app shell HTML for timeline reads. The camera push endpoints also
tolerate app-route-prefixed paths so a shared-space URL cannot turn a timeline
request into a generic app-shell navigation.
This path uses the DVR itself as the always-on network bridge when wasm-agent
cannot route to the DVR's private LAN; it is intentionally separate from
Intelbras Cloud/P2P and does not attempt to reuse the vendor cloud tunnel.

`hermes.wasm_agent.shared_space.v1`: a server-side state record for a shareable
space. It tracks owner, members, join code, source/local space ids, configured
Space area, and collaborative capabilities such as chat, WIS patching,
automation, and component evolution. Shared-space records live under wasm-agent
state, while device-local widget/app layout still remains local to each browser.
The launcher share dialog exposes the join code as a `/home?join_space=...`
invite URL, and Space-home can join from either that URL or the raw code.

## Device-Local Layout

App positions, widget positions, widget sizes, and Space distance are
client-local preferences. They should not synchronize across the account by
default because screen size and personal layout taste are device-specific.
User-created Space area is per-space metadata: new spaces initialize it from the
creating viewport, and shared spaces reuse that same configured area on every
joined device.

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

The historical Hermes Space customware interface remains useful prior art:
bundle-owned source, documented seams, and no private runtime patching by
default. `wasm-agent` should carry that philosophy forward with a WASM-first
artifact interface.

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
