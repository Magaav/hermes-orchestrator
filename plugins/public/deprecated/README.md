# Deprecated Public Plugins

This directory is reserved for public plugin trees that are no longer allowed to
own node startup/runtime behavior.

Current migration rule:

- active startup/runtime path: `/local/plugins/public/native/*`
- deprecated-runtime compatibility sources: `/local/plugins/public/discord`,
  `/local/plugins/public/hermes-core`

Those legacy trees should not be re-applied into `~/.hermes/hooks` during node
restart/update flows anymore.
