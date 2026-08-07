import {
  ARTIFACT_RECIPE_SCHEMA,
  STARS_SHELLS_GENERATOR,
  estimateRecipe
} from "./recipe.js";

let active;

async function loadText(path) {
  const response = await fetch(new URL(path, import.meta.url));
  if (!response.ok) throw new Error(`Artifact Foundry asset failed: ${path}`);
  return response.text();
}

function ensureStylesheet() {
  if (document.querySelector("link[data-artifact-foundry]")) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = new URL("./artifact-foundry.css", import.meta.url).href;
  link.dataset.artifactFoundry = "";
  document.head.append(link);
}

function download(name, value, type) {
  const url = URL.createObjectURL(new Blob([value], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function base64(bytes) {
  let result = "";
  const chunk = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunk) {
    result += String.fromCharCode(...bytes.subarray(offset, offset + chunk));
  }
  return btoa(result);
}

export async function mount(context = {}) {
  if (active) {
    active.root.hidden = false;
    return active.api;
  }
  ensureStylesheet();
  const root = document.createElement("section");
  const mountRoot = context.mountRoot || document.body;
  context.host?.classList.add("artifact-foundry-widget");
  mountRoot.classList.add("artifact-foundry-scroll-host");
  root.innerHTML = await loadText("./artifact-foundry.html");
  mountRoot.append(root);

  const worker = new Worker(new URL("./artifact-foundry.worker.js", import.meta.url), { type: "module" });
  const status = root.querySelector("[data-status]");
  const estimatePanel = root.querySelector("[data-estimate]");
  const resultPanel = root.querySelector("[data-result]");
  const generateButton = root.querySelector('[data-action="generate"]');
  let seed = new Uint8Array(await fetch(new URL("./stars-shells.seed.txt", import.meta.url)).then((response) => response.arrayBuffer()));
  let seedName = "stars-shells.seed.txt";
  let generated;
  let requestId = 0;

  function setStatus(message, error = false) {
    status.textContent = message;
    status.toggleAttribute("data-error", error);
  }

  function renderSeed() {
    root.querySelector("[data-seed-name]").textContent = seedName;
    root.querySelector("[data-seed-size]").textContent = `${seed.byteLength.toLocaleString()} bytes`;
    setStatus("Recipe ready. Estimate or generate locally.");
  }

  function currentRecipe() {
    return {
      generator: STARS_SHELLS_GENERATOR,
      seed,
      parameters: { maxRounds: Number(root.querySelector("[data-rounds]").value) }
    };
  }

  function renderEstimate() {
    const estimate = estimateRecipe(currentRecipe());
    root.querySelector("[data-estimate-seed]").textContent = `${estimate.seedBytes.toLocaleString()} B`;
    root.querySelector("[data-estimate-output]").textContent = estimate.expectedBytes
      ? `${estimate.expectedBytes.toLocaleString()} B`
      : "generator-dependent";
    estimatePanel.hidden = false;
    root.dispatchEvent(new CustomEvent("artifact-foundry-estimate", { detail: estimate }));
    return estimate;
  }

  function generate() {
    renderEstimate();
    requestId += 1;
    generateButton.disabled = true;
    resultPanel.hidden = true;
    setStatus("Generating and hashing in the browser worker…");
    worker.postMessage({
      type: "generate",
      requestId,
      generator: STARS_SHELLS_GENERATOR,
      parameters: currentRecipe().parameters,
      seed: seed.slice().buffer
    });
  }

  worker.addEventListener("message", (event) => {
    const message = event.data || {};
    if (message.requestId !== requestId) return;
    generateButton.disabled = false;
    if (message.type === "error") {
      setStatus(`Generation failed: ${message.error}`, true);
      return;
    }
    if (message.type !== "complete") return;
    generated = {
      output: new Uint8Array(message.output),
      receipt: message.receipt,
      projection: message.projection
    };
    root.querySelector("[data-output-size]").textContent = `${generated.receipt.outputBytes.toLocaleString()} B`;
    root.querySelector("[data-output-rounds]").textContent = generated.receipt.rounds;
    root.querySelector("[data-output-time]").textContent = `${generated.receipt.durationMs} ms`;
    root.querySelector("[data-output-state]").textContent = generated.receipt.verified ? "verified" : "failed";
    root.querySelector("[data-projection]").textContent = generated.projection;
    root.querySelector("[data-receipt]").textContent = JSON.stringify(generated.receipt, null, 2);
    resultPanel.hidden = false;
    setStatus("Artifact generated and verified without upload.");
    root.dispatchEvent(new CustomEvent("artifact-foundry-complete", {
      detail: { receipt: generated.receipt, projection: generated.projection }
    }));
  });

  root.querySelector("[data-seed-file]").addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (file) {
      seed = new Uint8Array(await file.arrayBuffer());
      seedName = file.name;
      generated = null;
      resultPanel.hidden = true;
      renderSeed();
    }
    event.target.value = "";
  });
  root.querySelector('[data-action="estimate"]').addEventListener("click", renderEstimate);
  generateButton.addEventListener("click", generate);
  root.querySelector('[data-action="export-artifact"]').addEventListener("click", () => {
    if (generated) download("artifact-foundry-stars-shells.gguf", generated.output, "application/octet-stream");
  });
  root.querySelector('[data-action="export-receipt"]').addEventListener("click", () => {
    if (generated) download("artifact-foundry-receipt.json", `${JSON.stringify(generated.receipt, null, 2)}\n`, "application/json");
  });
  root.querySelector('[data-action="export-recipe"]').addEventListener("click", () => {
    const capsule = {
      schema: ARTIFACT_RECIPE_SCHEMA,
      generator: STARS_SHELLS_GENERATOR,
      generatorVersion: "1",
      parameters: currentRecipe().parameters,
      seed: { encoding: "base64", bytes: seed.byteLength, data: base64(seed) }
    };
    download("artifact-foundry-recipe.json", `${JSON.stringify(capsule, null, 2)}\n`, "application/json");
  });

  renderSeed();
  const api = {
    estimate: renderEstimate,
    generate,
    close() {
      root.hidden = true;
      context.onClose?.();
    }
  };
  active = { root, api, worker };
  return api;
}
