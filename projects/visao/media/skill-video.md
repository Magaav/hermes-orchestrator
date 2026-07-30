---
name: verify-marketing-video
description: Create or revise branded marketing videos with stable motion, verified identity, and continuous-playback acceptance. Use for every video in this project.
---

# Video guard

Before rendering:

1. Resolve every company name, spelling, logo, symbol, and tagline from authoritative project assets. Never infer branding. For this project: **Visão + Colmeio** and **Powered by Colmeio**—never “Colmeia.” Use the official Colmeio symbol at `/local/projects/zaiaecainelli/media/hex-c-color-reverse.svg` (`hex`, not `hext`), with its original orange `#F89521`, brown `#8E451F`, geometry, and transparency. Never redraw, approximate, recolor, or replace it with generated imagery; stop if the source is unavailable.
2. Separate current software from short-term and long-term proposals. Never present roadmap capabilities as implemented.
3. Convert each still image into exactly one continuous timed video segment. Never combine a looped still input with multi-frame `zoompan`; it resets motion state and can flicker. Prefer a single-frame source with continuous interpolation, then concatenate stable segments.

Before delivery:

1. Decode the complete output without errors.
2. Watch the entire video continuously at normal speed with audio. Sampled frames are insufficient for detecting flicker, timing, pronunciation, or transition defects.
3. Verify every proper noun in visible text, narration, captions, and metadata.
4. Inspect the opening, every transition, and the closing at full resolution; reject clipped text, flicker, repeated frames, abrupt motion, or missing brand symbols.
5. Deliver only after temporal, audio, visual, and brand checks all pass.
