# Property Photo Cleaner

Install this folder at `L1/_all/mod/hermes/property-photo-cleaner/`. Space Agent
loads the `ext/js` initializer adapter and
`property-photo-cleaner.launcher.js` during initialization. The entry,
styles, HTML, workers, fixtures, model manifest, and processing modules are
requested after `hermes.property_photo_cleaner.open`.

The current MVP provides browser-local multi-file import, deterministic
brightness/contrast correction, object discovery, box-selected generative
removal, original/cleaned comparison, review/approval, single approved-image
export, visual quality examples, a watermark authorization gate, compact
status/loading contracts, and disposal. Object-removed results are identified
as digitally altered during review so the user can compare them with the
original before approval.

`Find objects` lazy-loads the self-hosted YOLOE property vocabulary and draws
2 px neon boxes with stable IDs, labels, confidence scores, and source-image
coordinates. Clicking a box's top-right × selects that footprint for removal.

`Clean objects now` lazy-loads ONNX Runtime Web and the immutable 256px FP32
LaMa model declared in `models/model-manifest.json`. Each selected box is
expanded, reconstructed sequentially, and composited back into the full photo.
The session is reused until the widget closes. Imported and generated photo
bytes never enter a bridge, server edit endpoint, or artifact.

## Lifecycle

Install/enable is managed by the normal Customware bundle layer. Disable or
uninstall removes the initializer/action registration. Closing the widget
releases decoded bitmaps, mask listeners, model sessions, and runtime
references while retaining original compressed blobs only for the open
project.

## Model benchmark status

| Field | Result |
| --- | --- |
| model ID / file / transfer size | `big-lama-256-places2` / `lama-256-places2.onnx` / 208,039,369 bytes |
| precision / input | FP32 / image `[1,3,256,256]` + mask `[1,1,256,256]` |
| backend | ONNX Runtime Web 1.27.0 in a dedicated WASM worker |
| cold compile | 11.9 seconds in VM Chromium |
| reused-session inference | about 9.6 seconds per selected region |
| browser proof | responsive real widget cleaned `object-11` and `object-13` in 31.3 seconds |
| privacy proof | zero photo writes; model fetched once from the proof origin |

The compact proof record is
`/tmp/property-photo-cleaner-browser-cleaning-evidence.json`; its visual
artifact is `/tmp/property-photo-cleaner-browser-entry-cleaned.png`.

## Missing generic seam

Space Agent currently has removable bundle actions but no generic declarative
application-icon/window registry. The launcher therefore publishes a compact
descriptor and `open` action without patching runtime internals. A native icon
should be wired by a future generic registry consuming that descriptor.
