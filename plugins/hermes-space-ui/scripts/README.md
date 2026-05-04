# Hermes Space UI Scripts

`scripts/` contains local lifecycle helpers for Hermes Space UI.

## Current Scripts

- `start_space_agent.sh`: prepares/updates the Space Agent checkout, seeds
  Hermes customware/modules, starts Space Agent, and starts the bridge path used
  by `horc space start`.
- `stop_space_agent.sh`: stops the Space Agent side of the integration.
- `start_space_ui.sh`: starts the Python bridge directly.
- `stop_space_ui.sh`: stops the bridge directly.
- `doctor.sh`: checks local bridge files, Python compilation, and expected Space
  Agent/bridge health surfaces.

## Change Rules

Scripts may create or update generated state under
`/local/plugins/hermes-space-ui/state/`. They should not modify the upstream
Space Agent checkout as a product patch. Put Hermes UI behavior in Space Agent
modules/customware first, or document the smallest upstream seam if core changes
are unavoidable.
