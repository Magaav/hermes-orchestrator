const ICON_PATHS = Object.freeze({
  resources: '<path d="M4 19V9m5 10V5m5 14v-7m5 7V3"/>',
  topology: '<circle cx="12" cy="5" r="2.5"/><circle cx="5" cy="18" r="2.5"/><circle cx="19" cy="18" r="2.5"/><path d="m10.8 7.2-4.6 8.6m7-8.6 4.6 8.6M7.5 18h9"/>',
  studio: '<path d="M4 4h16v12H4zM8 20h8m-4-4v4"/><path d="m8 8 2 2-2 2m5 0h3"/>',
  browser: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18"/>',
  wis: '<path d="M4 7.5 12 3l8 4.5v9L12 21l-8-4.5z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/>',
  drop: '<path d="M12 3v12m-4-4 4 4 4-4"/><path d="M4 18v2h16v-2"/>',
  security: '<path d="M12 3 5 6v5c0 4.7 2.8 8 7 10 4.2-2 7-5.3 7-10V6z"/><path d="m9 12 2 2 4-5"/>',
  analysis: '<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5M7 10h6m-3-3v6"/>',
  photo: '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m4 17 5-4 3 2 3-3 5 5"/>',
  batch: '<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>',
  asolaria: '<circle cx="12" cy="12" r="8"/><path d="M12 4v16M4 12h16m-2.3-5.7L6.3 17.7m0-11.4 11.4 11.4"/>',
  foundry: '<path d="M5 20h14M7 20v-6l5-3 5 3v6M9 9V4h6v5"/><path d="M10 16h4"/>',
  timeline: '<path d="M4 6h10m-6 6h12M4 18h10"/><circle cx="17" cy="6" r="2"/><circle cx="5" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
  app: '<rect x="3" y="3" width="18" height="18" rx="4"/><path d="M8 8h8v8H8z"/>',
});

export function widgetIconDataUri(iconName = "app") {
  const paths = ICON_PATHS[iconName] || ICON_PATHS.app;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#7ddcff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

export function applyWidgetIcon(element, app = {}, customImage = "") {
  if (!element) return;
  const image = String(customImage || "").startsWith("data:image/") ? customImage : widgetIconDataUri(app.icon || "app");
  element.textContent = "";
  element.style.backgroundImage = `url("${image}")`;
  element.classList.toggle("has-image", Boolean(customImage));
  element.classList.toggle("has-system-icon", !customImage);
}
