# Hermes Performance HUD Agent Notes

`hermes-performance-hud/` owns the Space Agent customware bundle that displays
Hermes runtime FPS and memory telemetry.

Keep all source changes in this folder. Generated copies under
`/local/plugins/hermes-space-ui/state/space-customware` are runtime output and
must not become the canonical edit location.

The Admin > Modules toggle is a compatibility adapter because Space Agent has
module list/info/install/remove APIs but no module-settings UI seam yet. The
real Admin page currently runs with `maxLayer=0`, so this L1 bundle cannot load
there. If that upstream seam is added later, migrate the toggle to the formal
seam and remove selector-based DOM attachment.
