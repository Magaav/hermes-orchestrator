export function applyWidgetWindowState(widget, layout = {}) {
  const id = widget?.dataset?.widgetId || "";
  const minimized = Boolean(layout.minimized);
  const maximized = Boolean(layout.maximized);
  const unavailable = widget?.classList?.contains("module-disabled")
    || widget?.classList?.contains("external-app-unmounted")
    || false;

  widget.classList.toggle("is-minimized", minimized);
  widget.classList.toggle("is-maximized", maximized);
  widget.hidden = unavailable || minimized;
  widget.querySelectorAll("[data-widget-control='maximize']").forEach((button) => {
    button.classList.toggle("active", maximized);
    button.title = maximized ? "Restore" : "Maximize";
    button.setAttribute("aria-label", maximized ? `Restore ${id}` : `Maximize ${id}`);
  });
}
