# Batch Cleaner Agent Notes

This folder owns the installable Batch Cleaner widget.

- Reuse Property Photo Cleaner model/runtime modules; do not duplicate model bytes.
- Accept at most 30 browser-local photos.
- Detection and cleaning queues are sequential and visibly stateful.
- Enhance Reality is an optional single worker pass after all object reconstruction; keep it bounded, deterministic, and free of extra model lifecycle.
- Excluding a photo must not delete its original blob.
- Closing releases thumbnail/object URLs and shared model sessions.
- Export contains cleaned included photos only and is generated in the browser.
