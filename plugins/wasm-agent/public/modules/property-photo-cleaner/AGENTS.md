# Property Photo Cleaner Agent Notes

This folder owns the complete installable Property Photo Cleaner bundle.

- Keep startup code in `property-photo-cleaner.launcher.js` descriptor-only.
- Keep the `ext/js` initializer adapter as a one-import launcher delegation;
  it must never import the entry module or runtime.
- Entry, UI, workers, fixtures, model runtime, and export code must load after
  an explicit user action.
- Photo bytes remain browser-local and must never enter logs, bundle actions,
  shared artifacts, or bridge state.
- A model is usable only after its manifest has an immutable URL, SHA-256,
  supported LiteRT.js version, and real browser inference proof.
- Closing releases decoded images, workers, model sessions, and GPU resources.
