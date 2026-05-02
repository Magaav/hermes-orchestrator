# Final Response Changed Files Native Plugin

`final-response-changed-files` is the Hermes-native packaging for the final
response footer that reports file changes.

It now uses Hermes' official native plugin hooks for deterministic file-change
tracking:

- `pre_tool_call` snapshots write targets before file-edit tools run
- `post_tool_call` records created, updated, and deleted files with cumulative
  line deltas for the current turn
- `pre_llm_call` resets per-turn state before the assistant starts its next turn

Current Hermes on this node does not expose the final-response transform hook,
so this package only maintains the deterministic file-change state needed for
that footer.

## Env Contract

- `PLUGIN_FINAL_RESPONSE_FILES_CHANGED=true|false`

`PLUGIN_FINAL_RESPONSE_FILES_CHANGED=true` is the intended enable flag for this
package.

For migration compatibility with the older gateway patch path, the runtime also
honors `NODE_AGENT_FINALRESPONSE_ENFORCE_FILES_CHANGED` when present.

## Required Behavior

The footer must continue to report:

- created files
- deleted files
- updated files whose contents changed

## Notes

This implementation stays inside the supported Hermes plugin surface. It does
not monkey-patch Hermes behavior ad hoc inside the plugin. Deterministic footer
delivery remains blocked until Hermes exposes a supported final-response
transform hook in the shipped runtime again.
