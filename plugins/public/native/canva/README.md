# Canva Native Plugin

This is the canonical Hermes-native Canva plugin for Hermes Orchestrator.
It is designed to make Hermes good at Canva itself, not just able to call Canva APIs.

## Env Contract

- `PLUGIN_CANVA=true|false`
- `CANVA_REFRESH_TOKEN`
- `CANVA_CLIENT_ID`
- `CANVA_CLIENT_SECRET`
- `CANVA_REDIRECT_URI` optional, recommended for full OAuth lifecycle tooling
- `CANVA_ACCESS_TOKEN` optional seed token only

`PLUGIN_CANVA` is the orchestrator/bootstrap intent flag.

## Runtime Layout

The orchestrator bootstrap syncs this plugin into the node runtime at `./.hermes/plugins/canva`.
Hermes then loads it through `HERMES_ENABLE_PROJECT_PLUGINS=true` plus `plugins.enabled: [canva]`.

## Tool Surface

- `canva_get_capabilities`
- `canva_create_design`
- `canva_list_designs`
- `canva_get_design`
- `canva_update_design`
- `canva_export_design`
- `canva_list_export_formats`
- `canva_upload_asset`
- `canva_upload_asset_from_url`
- `canva_list_local_assets`
- `canva_get_asset`
- `canva_update_asset`
- `canva_delete_asset`
- `canva_list_brand_templates`
- `canva_get_brand_template_dataset`
- `canva_autofill_design`
- `canva_normalize_design_brief`
- `canva_qa_design_brief`
- `canva_make_poster_from_asset`
- `canva_make_social_post`
- `canva_make_cover_from_image`
- `canva_create_comment_thread`
- `canva_get_comment_thread`
- `canva_create_comment_reply`
- `canva_list_comment_replies`

Local Canva outputs are organized as:

- `/workspace/canva/files/` for downloaded export artifacts
- `/workspace/canva/logs/` for structured operation records
- `/workspace/canva/files/inbox/` for staged local thread assets harvested from gateway turns

Every tool call now writes a structured JSON log under `/workspace/canva/logs/`, including failures.

The plugin also registers a `pre_llm_call` hook that can detect Hermes-cached local attachment paths, stage them into the Canva inbox, and inject a compact Canva-first workflow brief so the model prefers high-level playbooks and avoids wasteful tool usage.

That hook now also scans recent conversation history for previously staged local attachment paths, so a later Discord turn like "use the assets I attached in this thread" can keep working without depending on expired CDN URLs.

Uploaded local assets are cached in the plugin workspace logs so repeated runs can reuse existing Canva `asset_id` values instead of re-uploading the same file every turn.

Discord SVG handling is kept as a tiny generic ingress bridge so `.svg` files are treated as document assets instead of vision images. The Canva-specific staging, workspace routing, and prompt guidance live in the native plugin.

`canva_update_design` uses the Canva resize API to create a resized copy because the Connect API does not expose a general in-place content update endpoint.

## Agent Proficiency Workflow

To get high-quality Canva results without wasting requests or tokens, agents should follow this order:

1. Start with `canva_get_capabilities`.
2. Prefer `canva_list_brand_templates` plus `canva_get_brand_template_dataset` when polished visual output is needed.
3. Use `canva_autofill_design` to populate branded templates with structured content.
4. Use `canva_upload_asset` or `canva_upload_asset_from_url` when the design needs a real image or video.
5. Use `canva_list_local_assets` when the user references thread assets or prior uploads.
6. Use `canva_create_design` only for intentionally blank canvases or simple asset-backed layouts.

Important safeguards:

- `canva_make_social_post` and the other playbooks now fail closed when there is no reusable asset or `brand_template_id`.
- `canva_create_design` now blocks blank design creation by default unless `allow_blank=true`.
- Friendly labels like `instagram-post` are translated into custom dimensions (`1080x1080`) instead of being sent as invalid Canva preset names.
6. Export only after the design is ready.

That flow avoids the common failure mode of creating blank designs and exporting empty files.

## Scope Reality

With the currently available scopes, the plugin can already deliver strong value through:

- asset-led design creation
- design inspection
- export
- asset metadata management
- local brief normalization and design QA
- collaborative review comments when the live token truly carries comment scopes

However:

- listing or getting brand-template metadata still needs `brandtemplate:meta:read`
- comment APIs are still preview features in Canva's official docs, so they may be unsuitable for a public upstream Canva submission even if they are useful locally

Known official references:

- Canva scopes: https://www.canva.dev/docs/connect/appendix/scopes/
- Brand templates overview: https://www.canva.dev/docs/connect/api-reference/brand-templates/
- Get brand template dataset: https://www.canva.dev/docs/connect/api-reference/brand-templates/get-brand-template-dataset/
- Comments overview: https://www.canva.dev/docs/connect/api-reference/comments/

Inference from those docs:

- `brandtemplate:content:read` is enough to read a known template dataset
- `brandtemplate:meta:read` is required to list or inspect template metadata
- comments are powerful for local operator workflows, but are preview-only today

## CLI Surface

The plugin also exposes:

- `hermes canva status`
- `hermes canva auth`
- `hermes canva capabilities`
- `hermes canva list`
- `hermes canva templates`
- `hermes canva dataset <brand_template_id>`
- `hermes canva upload <file_path>`
- `hermes canva upload-url <url> <name>`
- `hermes canva export <design_id> <format_type>`
- `hermes canva smoke`

## High-Level Playbooks

The best new value surface is not only low-level CRUD, but high-level Canva planning helpers:

- `canva_make_poster_from_asset`
- `canva_make_social_post`
- `canva_make_cover_from_image`

These do not magically bypass Canva limitations. Instead, they:

- normalize the creative brief
- assess whether the brief is strong enough
- resolve or upload the primary asset
- produce the recommended Canva design request and export plan

That gives Hermes a more designer-like way to work from Discord prompts.

## Reliability Notes

- Refresh-token rotation is persisted in node-private state under `.hermes/auth/canva_oauth.json`.
- Token refresh is file-locked to reduce accidental single-use refresh-token waste across concurrent runs.
- API requests retry once on `401` by forcing a refresh before failing.

## Skill

If the runtime supports plugin skill registration, this plugin exposes `canva-designer`, a workflow guide that teaches Hermes how to:

- choose the right Canva path for the task
- avoid blank-design dead ends
- inspect template datasets before autofill
- delay exports until the final step

The plugin also ships a model-facing guide at [MODEL_GUIDE.md](/local/plugins/public/native/canva/MODEL_GUIDE.md:1) with recommended prompt patterns for strong Canva output.
