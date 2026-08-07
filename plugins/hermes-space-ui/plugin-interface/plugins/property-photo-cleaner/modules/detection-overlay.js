export function createDetectionOverlay({ layer, canvas, onRemoveIntent }) {
  let detections = [];
  let imageSize = { width: 1, height: 1 };
  let selectedIds = new Set();

  function render() {
    layer.replaceChildren();
    if (!detections.length) return;
    const canvasRect = canvas.getBoundingClientRect();
    const scale = Math.min(canvasRect.width / imageSize.width, canvasRect.height / imageSize.height);
    const renderedWidth = imageSize.width * scale;
    const renderedHeight = imageSize.height * scale;
    const offsetX = (canvasRect.width - renderedWidth) / 2;
    const offsetY = (canvasRect.height - renderedHeight) / 2;

    for (const detection of detections) {
      const box = document.createElement("div");
      box.className = "ppc-detection";
      box.dataset.detectionId = detection.id;
      box.toggleAttribute("data-selected", selectedIds.has(detection.id));
      box.style.left = `${offsetX + detection.box.x * scale}px`;
      box.style.top = `${offsetY + detection.box.y * scale}px`;
      box.style.width = `${detection.box.width * scale}px`;
      box.style.height = `${detection.box.height * scale}px`;

      const label = document.createElement("span");
      label.textContent = `${detection.label} ${Math.round(detection.score * 100)}%`;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "ppc-detection-remove";
      remove.setAttribute("aria-label", `${selectedIds.has(detection.id) ? "Keep" : "Select"} ${detection.label}`);
      remove.setAttribute("aria-pressed", String(selectedIds.has(detection.id)));
      remove.textContent = "×";
      remove.addEventListener("click", () => onRemoveIntent(detection));
      box.append(label, remove);
      layer.appendChild(box);
    }
  }

  const resizeObserver = new ResizeObserver(render);
  resizeObserver.observe(canvas);

  return {
    show(nextDetections, nextImageSize) {
      detections = nextDetections;
      imageSize = nextImageSize;
      render();
    },
    select(nextSelectedIds) {
      selectedIds = new Set(nextSelectedIds);
      render();
    },
    clear() {
      detections = [];
      layer.replaceChildren();
    },
    dispose() {
      resizeObserver.disconnect();
      layer.replaceChildren();
    }
  };
}
