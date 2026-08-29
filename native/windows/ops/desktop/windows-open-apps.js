"use strict";

const { execFile } = require("node:child_process");

const SCHEMA = "hermes.wasm_agent.windows_open_apps.v1";
const OPERATION = "inspect_windows_open_apps";
const MAX_WINDOWS = 64;
const MAX_OUTPUT_BYTES = 64 * 1024;

function clean(value, limit = 240) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, limit);
}

function normalizeInventory(value = {}) {
  const source = Array.isArray(value.windows) ? value.windows : [];
  const windows = source.slice(0, MAX_WINDOWS).flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const title = clean(item.title);
    const processName = clean(item.processName, 120);
    const processId = Number(item.processId);
    if (!title || !Number.isInteger(processId) || processId < 1) return [];
    return [{
      title,
      processName,
      processId,
      windowHandle: clean(item.windowHandle, 32),
      visible: item.visible === true,
      minimized: item.minimized === true,
    }];
  });
  return {
    schema: SCHEMA,
    operation: OPERATION,
    ok: true,
    windowCount: windows.length,
    windows,
    truncated: value.truncated === true || source.length > MAX_WINDOWS,
    proof: ["windows.desktop.top_level_windows"],
  };
}

function powershellScript() {
  return [
    "$ErrorActionPreference = 'Stop';",
    "$source = @'",
    "using System;",
    "using System.Collections.Generic;",
    "using System.Runtime.InteropServices;",
    "using System.Text;",
    "public static class TopLevelWindowReader {",
    "  public delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lparam);",
    "  [DllImport(\"user32.dll\")] static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lparam);",
    "  [DllImport(\"user32.dll\")] static extern bool IsWindowVisible(IntPtr hwnd);",
    "  [DllImport(\"user32.dll\")] static extern bool IsIconic(IntPtr hwnd);",
    "  [DllImport(\"user32.dll\", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr hwnd, StringBuilder value, int max);",
    "  [DllImport(\"user32.dll\")] static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);",
    "  public sealed class Item { public long windowHandle; public uint processId; public string title; public bool visible; public bool minimized; }",
    "  public static Item[] Read(int max) {",
    "    var values = new List<Item>();",
    "    EnumWindows((hwnd, _) => {",
    "      if (values.Count >= max || !IsWindowVisible(hwnd)) return true;",
    "      var title = new StringBuilder(1024); GetWindowText(hwnd, title, title.Capacity);",
    "      var text = title.ToString().Trim(); if (text.Length == 0) return true;",
    "      uint pid; GetWindowThreadProcessId(hwnd, out pid);",
    "      values.Add(new Item { windowHandle=hwnd.ToInt64(), processId=pid, title=text, visible=true, minimized=IsIconic(hwnd) });",
    "      return true;",
    "    }, IntPtr.Zero);",
    "    return values.ToArray();",
    "  }",
    "}",
    "'@;",
    "if (-not ('TopLevelWindowReader' -as [type])) { Add-Type -TypeDefinition $source -Language CSharp }",
    `$items = @([TopLevelWindowReader]::Read(${MAX_WINDOWS + 1}));`,
    `$windows = @($items | Select-Object -First ${MAX_WINDOWS} | ForEach-Object {`,
    "  $processName = ''; try { $processName = [string](Get-Process -Id ([int]$_.processId) -ErrorAction Stop).ProcessName } catch { }",
    "  [ordered]@{ title=[string]$_.title; processName=$processName; processId=[int]$_.processId; windowHandle=('0x{0:X}' -f [long]$_.windowHandle); visible=[bool]$_.visible; minimized=[bool]$_.minimized }",
    "});",
    `[ordered]@{ windows=$windows; truncated=($items.Count -gt ${MAX_WINDOWS}) } | ConvertTo-Json -Compress -Depth 4;`,
  ].join("\n");
}

function executeInventory(timeoutMs = 10_000) {
  return new Promise((resolve) => execFile("powershell.exe", [
    "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", powershellScript(),
  ], { timeout: timeoutMs, maxBuffer: MAX_OUTPUT_BYTES, windowsHide: true, encoding: "utf8" }, (error, stdout, stderr) => resolve({
    ok: !error, stdout: String(stdout || ""), stderr: clean(stderr || error?.message, 1000),
    exitCode: Number.isInteger(error?.code) ? error.code : error ? 1 : 0,
    timedOut: Boolean(error?.killed),
  })));
}

async function run(context = {}, dependencies = {}) {
  if ((dependencies.platform || process.platform) !== "win32") {
    return { schema: SCHEMA, operation: OPERATION, ok: false, failureClassification: "windows_native_shell_required" };
  }
  context.markPhase?.("top_level_window_inventory_started");
  const command = await (dependencies.executeInventory || executeInventory)(10_000);
  if (!command.ok) return {
    schema: SCHEMA, operation: OPERATION, ok: false,
    failureClassification: command.timedOut ? "windows_window_inventory_timeout" : "windows_window_inventory_failed",
    error: clean(command.stderr, 1000), exitCode: command.exitCode, timedOut: command.timedOut,
  };
  let value;
  try { value = JSON.parse(String(command.stdout || "")); }
  catch { return { schema: SCHEMA, operation: OPERATION, ok: false, failureClassification: "windows_window_inventory_invalid" }; }
  const result = normalizeInventory(value);
  context.markPhase?.("top_level_window_inventory_complete", { windowCount: result.windowCount, truncated: result.truncated });
  return result;
}

module.exports = { MAX_WINDOWS, OPERATION, SCHEMA, normalizeInventory, powershellScript, run };
