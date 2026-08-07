import assert from "node:assert/strict";
import fs from "node:fs/promises";

const source = await fs.readFile(new URL("./widget-window-state.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { applyWidgetWindowState } = await import(moduleUrl);

function classList(initial = []) {
  const values = new Set(initial);
  return {
    contains: (value) => values.has(value),
    toggle(value, enabled) {
      if (enabled) values.add(value);
      else values.delete(value);
    },
  };
}

function fixture(classes = []) {
  const maximize = {
    classList: classList(),
    title: "",
    label: "",
    setAttribute(name, value) {
      if (name === "aria-label") this.label = value;
    },
  };
  return {
    widget: {
      dataset: { widgetId: "browser" },
      classList: classList(classes),
      hidden: false,
      querySelectorAll: () => [maximize],
    },
    maximize,
  };
}

{
  const { widget } = fixture(["module-disabled"]);
  applyWidgetWindowState(widget, { minimized: false });
  assert.equal(widget.hidden, true, "disabled modules must stay hidden even when layout says open");
}

{
  const { widget } = fixture(["external-app-unmounted"]);
  applyWidgetWindowState(widget, { minimized: false });
  assert.equal(widget.hidden, true, "lazy external hosts must stay hidden until their module mounts");
}

{
  const { widget } = fixture();
  applyWidgetWindowState(widget, { minimized: true });
  assert.equal(widget.hidden, true);
}

{
  const { widget, maximize } = fixture();
  applyWidgetWindowState(widget, { maximized: true });
  assert.equal(widget.hidden, false);
  assert.equal(maximize.title, "Restore");
  assert.equal(maximize.label, "Restore browser");
}

console.log("widget window state tests passed");
