# Space Agent Customware Bundles

`plugins/` contains Hermes-owned Space Agent Customware Bundle Interface source.

## Current Bundles

- `hermes-fleet/`: Hermes Fleet module and seeded `hermes-os` space/widgets.
- `hermes-performance-hud/`: Hermes runtime FPS/memory overlay synced into
  Space Agent as a plugin-owned diagnostics bundle.
- `space-agent-brand/`: Hermes browser/PWA branding override.
- `component-context-menu/`: upstreamable right-click widget context-menu
  bundle synced into Space Agent as `space/component-context-menu`.

## Change Rules

Bundle source changes belong here. Generated copies under
`/local/plugins/hermes-space-ui/state/space-customware` are runtime output and
must not become the canonical edit location.
