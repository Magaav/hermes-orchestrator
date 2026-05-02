# Hermes Space Agent Brand Bundle

This bundle overrides Space Agent's browser, favicon, touch, and PWA icon
metadata with the Hermes `nous` astronaut artwork.

Install or sync it as a normal customware module:

```txt
L1/_all/mod/hermes/space-agent-brand/
```

The bundle uses the documented `_core/framework/head/end` HTML seam. It does
not edit Space Agent core files, page shells, or packaged desktop assets. A
small `_core/framework/initializer.js/initialize/end` hook also swaps
late-mounted overlay/avatar images to the source artwork so the floating agent
icon keeps the largest readable version.

`scripts/start_space_agent.sh` syncs this bundle into the local
`SPACE_AGENT_CUSTOMWARE_PATH` so the icon customization is reapplied after
Space Agent checkout updates.
