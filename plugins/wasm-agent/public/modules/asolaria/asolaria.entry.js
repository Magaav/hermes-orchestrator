import {
  inspectAsolaria,
  makeAsolariaReceipt,
  receiptProjection
} from "./runtime.js";
import {
  calibrationProjection,
  scoreBinaryCalibration
} from "./calibration.js";
import {
  inspectAsolariaLattice,
  latticeProjection
} from "./structure.js";

let active;

async function loadText(path) {
  const response = await fetch(new URL(path, import.meta.url));
  if (!response.ok) throw new Error(`ASOLARIA widget asset failed: ${path}`);
  return response.text();
}

function ensureStylesheet() {
  if (document.querySelector("link[data-asolaria]")) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = new URL("./asolaria.css", import.meta.url).href;
  link.dataset.asolaria = "";
  document.head.append(link);
}

function download(name, bytes, type) {
  const url = URL.createObjectURL(new Blob([bytes], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export async function mount(context = {}) {
  if (active) {
    active.root.hidden = false;
    return active.api;
  }
  ensureStylesheet();
  const root = document.createElement("section");
  const mountRoot = context.mountRoot || document.body;
  context.host?.classList.add("asolaria-widget");
  mountRoot.classList.add("asolaria-scroll-host");
  root.innerHTML = await loadText("./asolaria.html");
  mountRoot.append(root);

  const runtimeLine = root.querySelector("[data-runtime]");
  const statusLine = root.querySelector("[data-status]");
  const resultPanel = root.querySelector("[data-result]");
  const exportButton = root.querySelector('[data-action="export"]');
  const lattice = inspectAsolariaLattice();
  let current;
  let currentName = "asolaria-receipt";

  root.querySelector("[data-receipt-states]").textContent = lattice.states;
  root.querySelector("[data-ac-states]").textContent = lattice.thirds.ac.states;
  root.querySelector("[data-solid-cells]").textContent = lattice.thirds.solid.cells;
  root.querySelector("[data-translucent-cells]").textContent = lattice.thirds.translucent.cells;
  root.querySelector("[data-lattice-projection]").textContent = latticeProjection(lattice);
  root.querySelector("[data-lattice-detail]").textContent = JSON.stringify(lattice, null, 2);

  function setStatus(message, error = false) {
    statusLine.textContent = message;
    statusLine.toggleAttribute("data-error", error);
  }

  async function run(bytes, name) {
    setStatus(`Running ${name} locally…`);
    resultPanel.hidden = true;
    exportButton.disabled = true;
    try {
      current = await makeAsolariaReceipt(bytes, { name });
      currentName = name.replace(/[^A-Za-z0-9._-]+/g, "-") || "asolaria-receipt";
      const inspection = await inspectAsolaria();
      root.querySelector("[data-cells]").textContent = `${current.receipt.cellsReached}/27`;
      root.querySelector("[data-chain]").textContent = current.receipt.chainIntact ? "intact" : "broken";
      root.querySelector("[data-count]").textContent =
        `${current.receipt.count.produced}/${current.receipt.count.declared}/${current.receipt.count.withheld}`;
      root.querySelector("[data-prism]").textContent = current.receipt.prismRoundtripExact ? "exact" : "failed";
      root.querySelector("[data-projection]").textContent = receiptProjection(current);
      root.querySelector("[data-inspection]").textContent = JSON.stringify(inspection, null, 2);
      runtimeLine.textContent = "WASM ready";
      setStatus(`Measured ${bytes.byteLength.toLocaleString()} bytes without upload.`);
      resultPanel.hidden = false;
      exportButton.disabled = false;
      root.dispatchEvent(new CustomEvent("asolaria-receipt", {
        detail: {
          projection: receiptProjection(current),
          inspection
        }
      }));
    } catch (error) {
      runtimeLine.textContent = "Runtime error";
      setStatus(String(error?.message || error), true);
    }
  }

  root.querySelector('[data-action="run-text"]').addEventListener("click", () => {
    const text = root.querySelector("#asolaria-text").value;
    run(new TextEncoder().encode(text), "text-drill");
  });
  root.querySelector("[data-file]").addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (file) await run(new Uint8Array(await file.arrayBuffer()), file.name);
    event.target.value = "";
  });
  exportButton.addEventListener("click", () => {
    if (!current) return;
    download(`${currentName}.hbi`, current.bytes, "application/octet-stream");
  });
  root.querySelector("[data-calibration-file]").addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const payload = JSON.parse(await file.text());
      const rows = Array.isArray(payload) ? payload : payload.rows;
      const result = scoreBinaryCalibration(rows);
      const panel = root.querySelector("[data-calibration]");
      root.querySelector("[data-direct]").textContent =
        `${result.holdout.direct.correct}/${result.holdout.n}`;
      root.querySelector("[data-inverted]").textContent =
        `${result.holdout.inverted.correct}/${result.holdout.n}`;
      root.querySelector("[data-route]").textContent = result.decision.route;
      root.querySelector("[data-authority]").textContent = result.decision.authority;
      root.querySelector("[data-calibration-projection]").textContent = calibrationProjection(result);
      root.querySelector("[data-calibration-detail]").textContent = JSON.stringify({
        balance: result.holdoutBalance,
        topics: result.topics,
        decision: result.decision
      }, null, 2);
      panel.hidden = false;
      setStatus(`Scored ${result.sampleSize} labeled binary results.`);
      root.dispatchEvent(new CustomEvent("asolaria-calibration", {
        detail: {
          projection: calibrationProjection(result),
          decision: result.decision
        }
      }));
    } catch (error) {
      setStatus(`Calibration rejected: ${String(error?.message || error)}`, true);
    } finally {
      event.target.value = "";
    }
  });

  const api = {
    inspect: inspectAsolaria,
    inspectLattice: inspectAsolariaLattice,
    run,
    scoreBinaryCalibration,
    close() {
      root.hidden = true;
      context.onClose?.();
    }
  };
  active = { root, api };
  return api;
}
