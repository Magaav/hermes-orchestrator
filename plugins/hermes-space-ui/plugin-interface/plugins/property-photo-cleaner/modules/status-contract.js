export function createStatus() {
  return {
    schema: "hermes.space_ui.property_photo_cleaner.status.v1",
    execution: "browser_local_detection_cloud_edit",
    networkUsedForPhoto: false,
    backend: "not-loaded",
    stage: "idle",
    model: { id: null, precision: null, cached: false, loaded: false },
    memoryMode: (navigator.deviceMemory || 4) <= 1 ? "low" : "standard",
    progress: { current: 0, total: 0 },
    error: null
  };
}

export const capabilities = Object.freeze({
  schema: "hermes.space_ui.property_photo_cleaner.capabilities.v1",
  widgetId: "property-photo-cleaner",
  artifactId: "hermes.property-photo-cleaner",
  launchMode: "lazy",
  actions: ["open", "close", "inspect_status", "open_import", "load_examples", "start_auto_correction", "find_objects", "clean_objects", "undo_clean", "cancel_processing", "approve_current", "export_approved", "share_artifact", "clear_project", "clear_model_cache"]
});
