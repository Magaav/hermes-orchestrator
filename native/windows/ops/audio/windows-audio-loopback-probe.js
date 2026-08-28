"use strict";

const { execFile } = require("node:child_process");

const SCHEMA = "hermes.wasm_agent.windows_audio_loopback_probe.v1";
const OPERATION = "inspect_windows_audio_loopback";
const MAX_ENDPOINTS = 32;
const MAX_OUTPUT_BYTES = 64 * 1024;
const LOOPBACK_NAME = /(stereo\s*mix|mixagem\s*est[eé]reo|what\s+u\s+hear|wave\s+out\s+mix|loopback|monitor|cable\s+output|voicemeeter\s+output|virtual\s+audio.*output)/i;

function text(value, maxLength = 240) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, maxLength);
}

function endpointFlow(endpoint = {}) {
  const declared = text(endpoint.flow, 16).toLowerCase();
  if (["capture", "render"].includes(declared)) return declared;
  const instanceId = text(endpoint.instanceId || endpoint.instance_id, 400);
  if (/\{0\.0\.1\./i.test(instanceId)) return "capture";
  if (/\{0\.0\.0\./i.test(instanceId)) return "render";
  return "unknown";
}

function normalizeEndpoint(endpoint = {}) {
  const name = text(endpoint.name || endpoint.friendlyName || endpoint.friendly_name);
  const status = text(endpoint.status, 40) || "Unknown";
  const flow = endpointFlow(endpoint);
  const instanceId = text(endpoint.instanceId || endpoint.instance_id, 400);
  const loopbackCandidate = flow === "capture" && LOOPBACK_NAME.test(name);
  const ready = loopbackCandidate && /^(ok|unknown)$/i.test(status);
  return { name, status, flow, instanceId, loopbackCandidate, ready };
}

function classifyInventory(inventory = {}) {
  const endpoints = (Array.isArray(inventory.endpoints) ? inventory.endpoints : [])
    .slice(0, MAX_ENDPOINTS)
    .map(normalizeEndpoint)
    .filter((endpoint) => endpoint.name || endpoint.instanceId);
  const captureEndpoints = endpoints.filter((endpoint) => endpoint.flow === "capture");
  const renderEndpoints = endpoints.filter((endpoint) => endpoint.flow === "render");
  const loopbackCandidates = captureEndpoints.filter((endpoint) => endpoint.loopbackCandidate);
  const readyLoopbackCandidates = loopbackCandidates.filter((endpoint) => endpoint.ready);
  const defaultRecordingEndpointId = text(inventory.defaultRecordingEndpointId, 500).replace(/^SWD\\MMDEVAPI\\/i, "");
  const defaultRenderEndpointId = text(inventory.defaultRenderEndpointId, 500).replace(/^SWD\\MMDEVAPI\\/i, "");
  const cableRenderEndpoints = renderEndpoints.filter((endpoint) => /cable\s+input|voicemeeter\s+input|virtual\s+audio.*input/i.test(endpoint.name));
  const defaultEndpoint = defaultRecordingEndpointId ? loopbackCandidates.find((endpoint) => endpoint.instanceId.replace(/^SWD\\MMDEVAPI\\/i, "").toLowerCase() === defaultRecordingEndpointId.toLowerCase()) : undefined;
  const defaultRecordingDevice = text(defaultEndpoint?.name || inventory.legacyDefaultRecordingDevice || inventory.defaultRecordingDevice);
  const defaultMatchesLoopback = Boolean(defaultEndpoint || (defaultRecordingDevice && loopbackCandidates.some(
    (endpoint) => endpoint.name.localeCompare(defaultRecordingDevice, undefined, { sensitivity: "accent" }) === 0,
  )));
  let failureClassification = "pass";
  let nextAction = "Use the ready loopback capture endpoint as Chrome's recording input, then rerun the browser_speech proof.";
  if (!loopbackCandidates.length) {
    failureClassification = "audio_loopback_device_missing";
    nextAction = "Install or enable a Windows loopback capture endpoint such as Stereo Mix or VB-CABLE.";
  } else if (!readyLoopbackCandidates.length) {
    failureClassification = "audio_loopback_device_disabled";
    nextAction = `Enable the existing loopback capture endpoint: ${loopbackCandidates[0].name}.`;
  } else if (!defaultMatchesLoopback) {
    failureClassification = "audio_loopback_not_default";
    nextAction = `Set ${readyLoopbackCandidates[0].name} as the default recording input before rerunning Realure transcription.`;
  }
  return {
    schema: SCHEMA,
    operation: OPERATION,
    source: text(inventory.source, 80) || "windows_audio_endpoint_inventory",
    probeOk: true,
    ok: failureClassification === "pass",
    stable: failureClassification === "pass",
    failureClassification,
    nextAction,
    endpointCount: endpoints.length,
    captureEndpointCount: captureEndpoints.length,
    loopbackCandidateCount: loopbackCandidates.length,
    readyLoopbackCount: readyLoopbackCandidates.length,
    defaultRecordingDevice,
    defaultRecordingEndpointId,
    defaultRenderEndpointId,
    defaultRenderMatchesCable: Boolean(defaultRenderEndpointId && cableRenderEndpoints.some((endpoint) => endpoint.instanceId.replace(/^SWD\\MMDEVAPI\\/i, "").toLowerCase() === defaultRenderEndpointId.toLowerCase())),
    defaultMatchesLoopback,
    captureEndpoints,
    renderEndpoints,
    cableRenderEndpoints,
    loopbackCandidates,
    readyLoopbackCandidates,
  };
}

function powershellInventoryScript() {
  return [
    "$ErrorActionPreference = 'Stop';",
    "$source = 'Get-PnpDevice';",
    "try { $raw = @(Get-PnpDevice -Class AudioEndpoint -ErrorAction Stop) } catch {",
    "  $source = 'Get-CimInstance';",
    "  $raw = @(Get-CimInstance Win32_PnPEntity -ErrorAction Stop | Where-Object { $_.PNPClass -eq 'AudioEndpoint' });",
    "}",
    `$endpoints = @($raw | Select-Object -First ${MAX_ENDPOINTS} | ForEach-Object {`,
    "  $instanceId = if ($_.InstanceId) { [string]$_.InstanceId } else { [string]$_.PNPDeviceID };",
    "  $name = if ($_.FriendlyName) { [string]$_.FriendlyName } else { [string]$_.Name };",
    "  $status = if ($_.Status) { [string]$_.Status } else { 'Unknown' };",
    "  $flow = if ($instanceId -match '\\{0\\.0\\.1\\.') { 'capture' } elseif ($instanceId -match '\\{0\\.0\\.0\\.') { 'render' } else { 'unknown' };",
    "  [ordered]@{ name=$name; status=$status; flow=$flow; instanceId=$instanceId };",
    "});",
    "$legacyDefault = '';",
    "try { $legacyDefault = [string](Get-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Multimedia\\Sound Mapper' -Name Record -ErrorAction Stop).Record } catch { }",
    "$coreAudio = @'",
    "using System;",
    "using System.Runtime.InteropServices;",
    "[ComImport, Guid(\"D666063F-1587-4E43-81F1-B948E807363F\"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]",
    "interface IMMDevice { int Activate(ref Guid id, int clsCtx, IntPtr activationParams, out IntPtr instance); int OpenPropertyStore(int access, out IntPtr properties); int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id); int GetState(out int state); }",
    "[ComImport, Guid(\"A95664D2-9614-4F35-A746-DE8DB63617E6\"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]",
    "interface IMMDeviceEnumerator { int EnumAudioEndpoints(int flow, int mask, out IntPtr devices); int GetDefaultAudioEndpoint(int flow, int role, out IMMDevice device); int GetDevice(string id, out IMMDevice device); int RegisterEndpointNotificationCallback(IntPtr client); int UnregisterEndpointNotificationCallback(IntPtr client); }",
    "[ComImport, Guid(\"BCDE0395-E52F-467C-8E3D-C4579291692E\")] class MMDeviceEnumerator { }",
    "public static class AudioDefaultReader { public static string GetId(int flow) { var e=(IMMDeviceEnumerator)new MMDeviceEnumerator(); IMMDevice d; int hr=e.GetDefaultAudioEndpoint(flow,1,out d); if(hr!=0) Marshal.ThrowExceptionForHR(hr); string id; hr=d.GetId(out id); if(hr!=0) Marshal.ThrowExceptionForHR(hr); return id; } }",
    "'@;",
    "if (-not ('AudioDefaultReader' -as [type])) { Add-Type -TypeDefinition $coreAudio -Language CSharp }",
    "$defaultEndpointId = [AudioDefaultReader]::GetId(1); $defaultRenderEndpointId = [AudioDefaultReader]::GetId(0);",
    "[ordered]@{ source=($source + '+CoreAudio'); defaultRecordingEndpointId=$defaultEndpointId; defaultRenderEndpointId=$defaultRenderEndpointId; legacyDefaultRecordingDevice=$legacyDefault; endpoints=$endpoints } | ConvertTo-Json -Compress -Depth 5;",
  ].join("\n");
}

function executeInventory(timeoutMs = 10_000) {
  return new Promise((resolve) => {
    execFile("powershell.exe", [
      "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", powershellInventoryScript(),
    ], { timeout: timeoutMs, maxBuffer: MAX_OUTPUT_BYTES, windowsHide: true, encoding: "utf8" }, (error, stdout, stderr) => {
      resolve({
        ok: !error,
        stdout: String(stdout || ""),
        stderr: text(stderr || error?.message, 1000),
        exitCode: Number.isInteger(error?.code) ? error.code : error ? 1 : 0,
        timedOut: Boolean(error?.killed),
      });
    });
  });
}

async function run(context = {}, dependencies = {}) {
  const platform = dependencies.platform || process.platform;
  if (platform !== "win32") {
    return { schema: SCHEMA, operation: OPERATION, ok: false, stable: false, probeOk: false, failureClassification: "windows_native_shell_required", nextAction: "Run this probe through the installed Windows bridge." };
  }
  context.markPhase?.("audio_endpoint_inventory_started");
  const execute = dependencies.executeInventory || executeInventory;
  const command = await execute(10_000);
  if (!command.ok) {
    return {
      schema: SCHEMA,
      operation: OPERATION,
      ok: false,
      stable: false,
      probeOk: false,
      failureClassification: command.timedOut ? "audio_endpoint_inventory_timeout" : "audio_endpoint_inventory_failed",
      nextAction: "Inspect the bounded Windows AudioEndpoint inventory error before changing any recording device.",
      exitCode: command.exitCode,
      timedOut: command.timedOut,
      error: text(command.stderr, 1000),
    };
  }
  let inventory = {};
  try { inventory = JSON.parse(text(command.stdout, MAX_OUTPUT_BYTES)); }
  catch {
    return { schema: SCHEMA, operation: OPERATION, ok: false, stable: false, probeOk: false, failureClassification: "audio_endpoint_inventory_invalid", nextAction: "Fix the bounded inventory JSON projection before selecting an input device." };
  }
  const result = classifyInventory(inventory);
  context.markPhase?.("audio_endpoint_inventory_complete", {
    endpointCount: result.endpointCount,
    captureEndpointCount: result.captureEndpointCount,
    loopbackCandidateCount: result.loopbackCandidateCount,
    readyLoopbackCount: result.readyLoopbackCount,
    failureClassification: result.failureClassification,
  });
  return result;
}

module.exports = {
  MAX_ENDPOINTS,
  OPERATION,
  SCHEMA,
  classifyInventory,
  endpointFlow,
  normalizeEndpoint,
  powershellInventoryScript,
  run,
};
