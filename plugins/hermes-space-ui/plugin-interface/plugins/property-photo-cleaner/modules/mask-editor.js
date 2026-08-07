export function createMaskEditor(canvas, { enabled = false, onChange = () => {} } = {}) {
  const context = canvas.getContext("2d");
  const source = context.getImageData(0, 0, canvas.width, canvas.height);
  const mask = document.createElement("canvas");
  mask.width = canvas.width;
  mask.height = canvas.height;
  const maskContext = mask.getContext("2d");
  let drawing = false;
  let marked = false;
  let points = [];

  const strokeStyle = "rgba(255,70,100,.8)";

  function paintPreview() {
    context.putImageData(source, 0, 0);
    context.drawImage(mask, 0, 0);
  }

  function point(event) {
    const rect = canvas.getBoundingClientRect();
    return { x: (event.clientX - rect.left) * canvas.width / rect.width, y: (event.clientY - rect.top) * canvas.height / rect.height };
  }
  function down(event) {
    if (!enabled) return;
    drawing = true;
    points = [];
    maskContext.beginPath();
    const p = point(event);
    points.push(p);
    maskContext.moveTo(p.x, p.y);
    canvas.setPointerCapture?.(event.pointerId);
  }
  function move(event) {
    if (!drawing) return;
    const p = point(event);
    points.push(p);
    maskContext.strokeStyle = strokeStyle;
    maskContext.lineWidth = Math.max(8, canvas.width / 80);
    maskContext.lineCap = "round";
    maskContext.lineJoin = "round";
    maskContext.lineTo(p.x, p.y);
    maskContext.stroke();
    marked = true;
    paintPreview();
  }
  function up() {
    if (!drawing) return;
    drawing = false;
    if (points.length >= 3) {
      maskContext.closePath();
      maskContext.fillStyle = strokeStyle;
      maskContext.fill();
      marked = true;
      paintPreview();
      onChange();
    }
    points = [];
  }
  canvas.addEventListener("pointerdown", down);
  canvas.addEventListener("pointermove", move);
  canvas.addEventListener("pointerup", up);
  return {
    hasMask: () => marked,
    setEnabled(value) {
      enabled = Boolean(value);
      canvas.dataset.maskEnabled = String(enabled);
    },
    frame: () => ({
      source,
      mask: maskContext.getImageData(0, 0, mask.width, mask.height)
    }),
    dispose() {
      canvas.removeEventListener("pointerdown", down);
      canvas.removeEventListener("pointermove", move);
      canvas.removeEventListener("pointerup", up);
    }
  };
}
