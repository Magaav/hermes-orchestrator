"use strict";

const { execFile } = require("node:child_process");

const SCHEMA = "hermes.wasm_agent.windows_audio_default.v1";
const OPERATION = "set_windows_audio_capture_default";
const MAX_OUTPUT_BYTES = 64 * 1024;

function text(value, maxLength = 400) {
  return String(value || "").replace(/[\r\n\0]+/g, " ").trim().slice(0, maxLength);
}

function powershellSingleQuoted(value) {
  return `'${String(value || "").replace(/'/g, "''")}'`;
}

function normalizeEndpointId(value) {
  return text(value, 500).replace(/^SWD\\MMDEVAPI\\/i, "");
}

function validEndpointId(value, flow = "capture") {
  const code = flow === "render" ? "0" : "1";
  return new RegExp(`^\\{0\\.0\\.${code}\\.00000000\\}\\.\\{[0-9A-F-]{36}\\}$`, "i").test(normalizeEndpointId(value));
}

function powershellSetDefaultScript({ instanceId, expectedName = "", flow = "capture", dryRun = false } = {}) {
  const endpointId = normalizeEndpointId(instanceId);
  const flowValue = flow === "render" ? 0 : 1;
  return [
    "$ErrorActionPreference = 'Stop';",
    `$endpointId = ${powershellSingleQuoted(endpointId)};`,
    `$expectedName = ${powershellSingleQuoted(text(expectedName, 240))};`,
    `$flow = ${flowValue};`,
    `$dryRun = $${dryRun ? "true" : "false"};`,
    "$pnpId = 'SWD\\MMDEVAPI\\' + $endpointId;",
    "$device = Get-PnpDevice -InstanceId $pnpId -ErrorAction Stop;",
    "if ($device.Status -notin @('OK','Unknown')) { throw 'audio_endpoint_not_ready' }",
    "if ($expectedName -and $device.FriendlyName -ne $expectedName) { throw 'audio_endpoint_name_mismatch' }",
    "$source = @'",
    "using System;",
    "using System.Runtime.InteropServices;",
    "public enum ERole { Console = 0, Multimedia = 1, Communications = 2 }",
    "[ComImport, Guid(\"F8679F50-850A-41CF-9C72-430F290290C8\"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]",
    "interface IPolicyConfig {",
    " int GetMixFormat(string deviceId, IntPtr format); int GetDeviceFormat(string deviceId, int defaultFormat, IntPtr format);",
    " int ResetDeviceFormat(string deviceId); int SetDeviceFormat(string deviceId, IntPtr endpointFormat, IntPtr mixFormat);",
    " int GetProcessingPeriod(string deviceId, int defaultPeriod, IntPtr defaultValue, IntPtr minimumValue); int SetProcessingPeriod(string deviceId, IntPtr period);",
    " int GetShareMode(string deviceId, IntPtr mode); int SetShareMode(string deviceId, IntPtr mode);",
    " int GetPropertyValue(string deviceId, IntPtr key, IntPtr value); int SetPropertyValue(string deviceId, IntPtr key, IntPtr value);",
    " int SetDefaultEndpoint([MarshalAs(UnmanagedType.LPWStr)] string deviceId, ERole role); int SetEndpointVisibility(string deviceId, int visible);",
    "}",
    "[ComImport, Guid(\"870AF99C-171D-4F9E-AF0D-E63DF40C2BC9\")] class PolicyConfigClient { }",
    "[ComImport, Guid(\"D666063F-1587-4E43-81F1-B948E807363F\"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] interface IMMDevice { int Activate(ref Guid id, int clsCtx, IntPtr activationParams, out IntPtr instance); int OpenPropertyStore(int access, out IntPtr properties); int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id); int GetState(out int state); }",
    "[ComImport, Guid(\"A95664D2-9614-4F35-A746-DE8DB63617E6\"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] interface IMMDeviceEnumerator { int EnumAudioEndpoints(int flow, int mask, out IntPtr devices); int GetDefaultAudioEndpoint(int flow, int role, out IMMDevice device); int GetDevice(string id, out IMMDevice device); int RegisterEndpointNotificationCallback(IntPtr client); int UnregisterEndpointNotificationCallback(IntPtr client); }",
    "[ComImport, Guid(\"BCDE0395-E52F-467C-8E3D-C4579291692E\")] class MMDeviceEnumerator { }",
    "public static class AudioDefault { public static void Set(string id) { var policy = (IPolicyConfig)new PolicyConfigClient(); foreach (ERole role in Enum.GetValues(typeof(ERole))) { int hr = policy.SetDefaultEndpoint(id, role); if (hr != 0) Marshal.ThrowExceptionForHR(hr); } } public static string GetId(int flow) { var e=(IMMDeviceEnumerator)new MMDeviceEnumerator(); IMMDevice d; int hr=e.GetDefaultAudioEndpoint(flow,1,out d); if(hr!=0) Marshal.ThrowExceptionForHR(hr); string id; hr=d.GetId(out id); if(hr!=0) Marshal.ThrowExceptionForHR(hr); return id; } }",
    "'@;",
    "if (-not ('AudioDefault' -as [type])) { Add-Type -TypeDefinition $source -Language CSharp }",
    "$observedEndpointId = [AudioDefault]::GetId($flow);",
    "if (-not $dryRun) { [AudioDefault]::Set($endpointId); $observedEndpointId = [AudioDefault]::GetId($flow); if ($observedEndpointId -ine $endpointId) { throw 'audio_default_verification_failed' } }",
    "[ordered]@{ endpointId=$endpointId; observedEndpointId=$observedEndpointId; name=[string]$device.FriendlyName; status=[string]$device.Status; changed=(-not $dryRun); roles=@('console','multimedia','communications') } | ConvertTo-Json -Compress -Depth 4;",
  ].join("\n");
}

function executeSetDefault(args, timeoutMs = 15_000) {
  return new Promise((resolve) => {
    execFile("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", powershellSetDefaultScript(args)],
      { timeout: timeoutMs, maxBuffer: MAX_OUTPUT_BYTES, windowsHide: true, encoding: "utf8" },
      (error, stdout, stderr) => resolve({ ok: !error, stdout: String(stdout || ""), stderr: text(stderr || error?.message, 1200), exitCode: Number.isInteger(error?.code) ? error.code : error ? 1 : 0, timedOut: Boolean(error?.killed) }));
  });
}

async function run(context = {}, dependencies = {}) {
  const operation = String(context.operation?.name || OPERATION);
  const flow = operation === "set_windows_audio_render_default" || context.args?.flow === "render" ? "render" : "capture";
  if ((dependencies.platform || process.platform) !== "win32") return { schema: SCHEMA, operation, flow, ok: false, changed: false, failureClassification: "windows_native_shell_required" };
  const instanceId = normalizeEndpointId(context.args?.instanceId || context.args?.instance_id);
  const expectedName = text(context.args?.expectedName || context.args?.expected_name, 240);
  const dryRun = Boolean(context.dryRun || context.args?.dryRun || context.args?.dry_run);
  if (!validEndpointId(instanceId, flow)) return { schema: SCHEMA, operation, flow, ok: false, changed: false, failureClassification: `invalid_${flow}_endpoint_id` };
  context.markPhase?.("audio_default_precondition_started", { dryRun });
  const command = await (dependencies.executeSetDefault || executeSetDefault)({ instanceId, expectedName, flow, dryRun });
  if (!command.ok) return { schema: SCHEMA, operation, flow, ok: false, changed: false, dryRun, failureClassification: command.timedOut ? "audio_default_timeout" : "audio_default_change_failed", error: text(command.stderr, 1200), exitCode: command.exitCode };
  let result = {};
  try { result = JSON.parse(String(command.stdout || "").trim()); } catch { return { schema: SCHEMA, operation, flow, ok: false, changed: false, dryRun, failureClassification: "audio_default_result_invalid" }; }
  context.markPhase?.("audio_default_change_complete", { endpointId: instanceId, changed: result.changed === true });
  const observedEndpointId = normalizeEndpointId(result.observedEndpointId);
  const verified = dryRun || observedEndpointId.toLowerCase() === instanceId.toLowerCase();
  return { schema: SCHEMA, operation, flow, ok: verified, stable: verified, changed: verified && result.changed === true, dryRun, endpointId: instanceId, observedEndpointId, name: text(result.name, 240), status: text(result.status, 40), roles: Array.isArray(result.roles) ? result.roles.slice(0, 3) : [], failureClassification: verified ? "pass" : "audio_default_verification_failed", nextAction: dryRun ? "Run with dryRun false after explicit authorization." : "Rerun the independent Windows audio loopback promise." };
}

module.exports = { OPERATION, SCHEMA, normalizeEndpointId, powershellSetDefaultScript, run, validEndpointId };
