---
name: canva-designer
description: Use when the goal is to create strong Canva output efficiently. Chooses between capabilities, templates, autofill, assets, blank designs, and export while minimizing wasted API calls.
version: 1.0.0
author: Hermes Orchestrator
metadata:
  hermes:
    tags: [canva, design, branding, creative, export, workflow]
    related_skills: []
---

# Canva Designer

## Overview

Use this skill when the user wants polished Canva output, not just raw design CRUD.

The key rule is simple:

- do not create blank designs unless blank is explicitly desired
- if the user references thread attachments, inspect staged local assets before saying anything is missing
- inspect what Canva can support first
- prefer template autofill for professional layouts
- export only after the content is ready

## Decision Order

Follow this order every time:

1. Call `canva_get_capabilities`.
2. If the user referenced assets from the thread or previous turns, call `canva_list_local_assets`.
3. Decide which path fits the request:
   - `brand template + autofill` for polished marketing, branded content, flyers, decks, social posts
   - `asset upload + create design` for image-led compositions
   - `blank create design` only for intentional empty canvases or very manual follow-up editing
4. If using templates:
   - call `canva_list_brand_templates`
   - choose the best-matching template
   - call `canva_get_brand_template_dataset`
   - build a tight data payload that fills every required field cleanly
   - call `canva_autofill_design`
5. If using assets:
   - prepare or obtain the image/video first
   - prefer staged local assets from `/workspace/canva/files/inbox/`
   - upload with `canva_upload_asset` or `canva_upload_asset_from_url`
   - then call `canva_create_design` with `asset_id`
6. Inspect the resulting design with `canva_get_design` before exporting.
7. Export once at the end with `canva_export_design`.

## Output Strategy

When writing copy for Canva, optimize for compact, visual language:

- headline: 3-8 words
- support text: 1-3 short lines
- CTA: 2-5 words
- avoid dense paragraphs unless the format is a document or presentation

For image-led designs:

- use one dominant visual idea
- keep overlays short and high-contrast
- avoid asking Canva to solve layout from vague prose

## Prompt Efficiency Rules

To reduce wasted calls:

- never jump straight to export after creating a design
- never create a social/Instagram post as a blank design when there is no asset or brand template
- never call `canva_create_design` when the user asked for a polished poster and templates exist
- never guess autofill fields without first checking the template dataset
- avoid repeated list calls with large limits unless discovery is actually needed
- reuse the chosen `brand_template_id`, `design_id`, and `asset_id` instead of re-querying them

## Suggested Workflow Patterns

### Poster / Flyer / Social Post

1. `canva_get_capabilities`
2. `canva_list_local_assets`
3. If a usable `brand_template_id` exists, use template autofill.
4. `canva_get_brand_template_dataset`
5. `canva_autofill_design`
6. `canva_get_design`
7. `canva_export_design`
8. Otherwise use an asset-led playbook and do not proceed unless a reusable asset exists.

### Art Built Around an Existing Image

1. create or obtain the image
2. `canva_upload_asset` or `canva_upload_asset_from_url`
3. `canva_create_design` with `asset_id`
4. `canva_get_design`
5. `canva_export_design`

### Blank Workspace for Human Editing

1. `canva_create_design`
2. return the design metadata or edit link if available
3. export only after the user or agent has added real content

## Failure Recovery

If the result looks empty or too generic:

- check whether the design was created blank
- check whether the template dataset was filled incompletely
- check whether the uploaded asset actually imported successfully
- check whether the request should have stopped earlier because there was no reusable asset or brand template
- only then retry, using the smallest corrective step possible
