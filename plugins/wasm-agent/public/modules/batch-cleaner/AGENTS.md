# Batch Cleaner Agent Notes

This folder owns the installable Batch Cleaner widget.

- Do not load a client-side detection, mask, or reconstruction model.
- Accept at most 30 browser-local photos.
- Datacenter cleaning uses at most ten isolated concurrent Codex sessions and
  remains visibly stateful per photo.
- Reconstruction is owned by the authenticated Codex App Server datacenter
  adapter and `$property-photo-reconstructor`; never silently fall back to a
  weaker local reconstruction model.
- Excluding a photo must not delete its original blob.
- Closing releases thumbnail/object URLs and shared model sessions.
- Export contains cleaned included photos only and is generated in the browser.
