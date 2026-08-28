"use strict";

const { execFile } = require("node:child_process");

const OPERATION = "capture_windows_desktop_screenshot";
const SCHEMA = "hermes.wasm_agent.windows_desktop_screenshot.v1";
const MAX_OUTPUT_BYTES = 16 * 1024;

function clean(value, limit = 1000) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, limit);
}

function powershellScript() {
  return [
    "$ErrorActionPreference = 'Stop';",
    "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing;",
    "$bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen;",
    "$root = Join-Path $env:LOCALAPPDATA 'WASM-Agent\\proof'; [IO.Directory]::CreateDirectory($root) | Out-Null;",
    "$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ'); $path = Join-Path $root ('desktop-' + $stamp + '.png');",
    "$bitmap = New-Object Drawing.Bitmap $bounds.Width,$bounds.Height; $graphics = [Drawing.Graphics]::FromImage($bitmap);",
    "try { $graphics.CopyFromScreen($bounds.Left,$bounds.Top,0,0,$bounds.Size); $bitmap.Save($path,[Drawing.Imaging.ImageFormat]::Png) } finally { $graphics.Dispose(); $bitmap.Dispose() };",
    "$sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant();",
    "[ordered]@{ path=$path; sha256=$sha; width=[int]$bounds.Width; height=[int]$bounds.Height; left=[int]$bounds.Left; top=[int]$bounds.Top; capturedAt=[DateTime]::UtcNow.ToString('o') } | ConvertTo-Json -Compress;",
  ].join("\n");
}

function executeCapture(timeoutMs = 15_000) {
  return new Promise((resolve) => execFile("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", powershellScript()], { timeout: timeoutMs, maxBuffer: MAX_OUTPUT_BYTES, windowsHide: true, encoding: "utf8" }, (error, stdout, stderr) => resolve({ ok: !error, stdout: String(stdout || ""), stderr: clean(stderr || error?.message), exitCode: Number.isInteger(error?.code) ? error.code : error ? 1 : 0, timedOut: Boolean(error?.killed) })));
}

function normalize(value = {}) {
  const width = Number(value.width); const height = Number(value.height);
  const sha256 = clean(value.sha256, 64); const artifactPath = String(value.path || "").slice(0, 32768);
  if (!artifactPath || !/^[a-f0-9]{64}$/.test(sha256) || !Number.isInteger(width) || width < 1 || !Number.isInteger(height) || height < 1) return null;
  return { schema: SCHEMA, operation: OPERATION, ok: true, artifact: { path: artifactPath, sha256, width, height, left: Number(value.left) || 0, top: Number(value.top) || 0, capturedAt: clean(value.capturedAt, 80), scope: "virtual_desktop", containsSensitivePixels: true }, proof: ["windows.desktop.screenshot"] };
}

async function run(context = {}, dependencies = {}) {
  if ((dependencies.platform || process.platform) !== "win32") return { schema: SCHEMA, operation: OPERATION, ok: false, failureClassification: "windows_native_shell_required" };
  context.markPhase?.("desktop_screenshot_started");
  const command = await (dependencies.executeCapture || executeCapture)();
  if (!command.ok) return { schema: SCHEMA, operation: OPERATION, ok: false, failureClassification: command.timedOut ? "windows_desktop_screenshot_timeout" : "windows_desktop_screenshot_failed", error: command.stderr, exitCode: command.exitCode, timedOut: command.timedOut };
  let value; try { value = JSON.parse(command.stdout); } catch { return { schema: SCHEMA, operation: OPERATION, ok: false, failureClassification: "windows_desktop_screenshot_invalid" }; }
  const result = normalize(value);
  if (!result) return { schema: SCHEMA, operation: OPERATION, ok: false, failureClassification: "windows_desktop_screenshot_invalid" };
  context.markPhase?.("desktop_screenshot_complete", { width: result.artifact.width, height: result.artifact.height, sha256: result.artifact.sha256 });
  return result;
}

module.exports = { OPERATION, SCHEMA, normalize, powershellScript, run };
