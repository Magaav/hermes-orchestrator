# Canva Model Guide

This file teaches Hermes how to get strong output from the Canva plugin without wasting requests.

## Core Rule

Canva is best used as a structured design engine, not as a vague text-to-art engine.

Always prefer:

1. a clear format
2. a clear audience
3. short copy
4. a visual direction
5. existing assets or a known template
6. export only at the end

## What Canva Is Good At

- turning a good image into a polished poster, social post, or cover
- creating branded deliverables from precise copy
- producing multiple clean output formats
- supporting review loops through comments
- generating consistent asset-led layouts

## What Canva Is Bad At

- inventing a full visual concept from a vague sentence
- replacing an image generator
- producing great results from "surprise me" prompts with no assets or template
- magical in-place redesign through the Connect API alone

## Best Workflow

### Asset-led design

Use this when the user already has an image, screenshot, mockup, product shot, or illustration.

1. upload or reuse the asset
2. create a design with the asset
3. inspect the design metadata
4. if needed, leave comments for revision or handoff
5. export at the end

If the user says "use the assets I attached in this thread", first look for staged local assets in `/workspace/canva/files/inbox/` or use `canva_list_local_assets`.
Do not say the Discord CDN links expired unless you have already checked the staged local assets and found nothing reusable.

### Template-led design

Use this only when you already know the template ID and the template has autofill fields.

1. get the dataset for the template
2. map the user data carefully
3. autofill once
4. inspect before export

### Review-led workflow

Use comments when the design needs iteration.

1. get the design
2. identify concrete weak points
3. create a comment thread with specific change requests
4. reply in the same thread as work progresses
5. export only after the design is strong enough

## Prompt Pattern For Great Results

When the user wants Canva output, rewrite their request internally into this structure:

- objective: what the design is for
- format: poster, social post, slide cover, flyer, presentation, thumbnail
- audience: who should respond to it
- tone: premium, bold, friendly, retail, minimalist, corporate
- copy:
  - headline
  - support line
  - CTA
- assets: what image or visual source to use
- export: png, pdf, jpg, etc.

## Prompt Rewrites

Weak:

`make something beautiful in canva`

Better:

`Create a Canva sales poster using the provided hero image. Format: 1408x768. Audience: retail operators. Tone: premium and bold. Headline: "Colmeio acelera sua operacao". Support line: "Mais clareza, mais ritmo, menos retrabalho". CTA: "Fale com a equipe". Export as PNG.`

Weak:

`surprise me`

Better:

`Create three Canva variants from the same uploaded asset: premium corporate, energetic retail, and minimal clean. Keep copy short and export only the strongest candidate unless I ask for all three.`

## Review Comment Pattern

Good Canva comments are:

- specific
- visual
- actionable
- short

Examples:

- `Increase headline contrast and reduce the subtitle width so the message reads faster.`
- `The hero image feels too small. Scale it up and give the CTA more breathing room.`
- `Make the composition feel more premium: less clutter, stronger hierarchy, darker background.`

## Efficiency Rules

- do not create multiple blank designs unless explicitly asked
- do not create any blank design unless the user explicitly wants a blank canvas or manual edit shell
- do not export before checking the design exists and has real content
- do not use template APIs unless the account scopes support them
- reuse design IDs, asset IDs, and thread IDs instead of re-querying them repeatedly
- reuse staged local assets from `/workspace/canva/files/inbox/` before re-uploading or re-downloading anything
- prefer one strong design plus comments over five weak variants
- treat `/workspace/canva/files/` as the canonical export destination
- treat `/workspace/canva/logs/` as the canonical audit trail for every Canva operation
- social/Instagram posts should use custom `1080x1080` dimensions rather than the unsupported preset name `instagram-post`

## Reality Checks

- Canva Connect cannot add arbitrary text layers or style a social post from prose alone.
- If there is no reusable asset and no `brand_template_id`, stop and ask for one instead of pretending the playbook can finish.
- If the user explicitly wants a richer composed result and Hermes browser tooling is available, you may suggest the built-in browser workflow against the Canva `edit_url`. Do not frame that as native Connect API capability.
