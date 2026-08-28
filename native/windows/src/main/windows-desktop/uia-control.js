"use strict";

const crypto = require("crypto");
const { spawn: spawnProcess } = require("child_process");

const SCHEMA = "hermes.wasm_agent.windows_desktop_automation.v1";
const SNAPSHOT_TTL_MS = 60_000;
const WINDOWS_DESKTOP_OPERATIONS = Object.freeze(["windows_desktop_describe", "windows_desktop_inspect", "windows_desktop_act", "windows_desktop_prove"]);
const ACTIONS = Object.freeze(["focus", "invoke", "click", "set_value", "toggle", "select", "expand", "collapse"]);
const PROPERTIES = Object.freeze(["name", "value", "toggle_state", "enabled", "offscreen", "selected", "expanded"]);

function boundedJson(value, maxBytes = 65_536) {
  const encoded = JSON.stringify(value && typeof value === "object" ? value : {});
  if (Buffer.byteLength(encoded, "utf8") > maxBytes) throw new Error("windows_desktop_payload_too_large");
  return encoded;
}

function normalizedRequest(operation, payload = {}) {
  const value = payload && typeof payload === "object" && !Array.isArray(payload) ? payload : {};
  if (operation === "windows_desktop_describe") {
    if (Object.keys(value).length) throw new Error("windows_desktop_describe_accepts_no_payload");
    return {};
  }
  if (operation === "windows_desktop_inspect") {
    const allowed = new Set(["target", "max_elements", "max_depth", "include_values", "timeout_ms"]);
    if (Object.keys(value).some((key) => !allowed.has(key))) throw new Error("windows_desktop_inspect_fields_invalid");
    return {
      target: value.target && typeof value.target === "object" ? value.target : {},
      max_elements: Math.max(1, Math.min(200, Math.round(Number(value.max_elements) || 80))),
      max_depth: Math.max(1, Math.min(32, Math.round(Number(value.max_depth) || 12))),
      include_values: value.include_values === true,
      timeout_ms: Math.max(3_000, Math.min(30_000, Math.round(Number(value.timeout_ms) || 15_000))),
    };
  }
  if (operation === "windows_desktop_act" || operation === "windows_desktop_prove") {
    const allowed = new Set(["snapshot_id", "ref", "action", "value", "expect", "timeout_ms"]);
    if (Object.keys(value).some((key) => !allowed.has(key))) throw new Error("windows_desktop_action_fields_invalid");
    const snapshotId = String(value.snapshot_id || "");
    const ref = String(value.ref || "");
    if (!/^s-[a-f0-9]{16}$/.test(snapshotId) || !/^e\d{1,3}$/.test(ref)) throw new Error("windows_desktop_snapshot_ref_invalid");
    const action = operation === "windows_desktop_act" ? String(value.action || "") : "prove";
    if (operation === "windows_desktop_act" && !ACTIONS.includes(action)) throw new Error("windows_desktop_action_invalid");
    const expect = value.expect && typeof value.expect === "object" && !Array.isArray(value.expect) ? value.expect : null;
    if (expect && (!PROPERTIES.includes(String(expect.property || "")) || !("equals" in expect))) {
      throw new Error("windows_desktop_expectation_invalid");
    }
    if (typeof expect?.equals === "string" && expect.equals.length > 4_096) throw new Error("windows_desktop_expectation_too_large");
    return {
      snapshot_id: snapshotId,
      ref,
      action,
      value: String(value.value ?? "").slice(0, 4_096),
      expect,
      timeout_ms: Math.max(3_000, Math.min(30_000, Math.round(Number(value.timeout_ms) || 15_000))),
    };
  }
  throw new Error("windows_desktop_operation_unsupported");
}

function encodedPowerShell(script) {
  return Buffer.from(script, "utf16le").toString("base64");
}

function automationScript(request) {
  const input = Buffer.from(boundedJson(request), "utf8").toString("base64");
  return String.raw`
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class WasmAgentUser32 { [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow(); }
"@
$request = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${input}')) | ConvertFrom-Json

function WindowHandle($target) {
  $raw = [string]$target.hwnd
  if ($raw.StartsWith('0x')) { return [IntPtr]([Convert]::ToInt64($raw.Substring(2), 16)) }
  if ($raw) { return [IntPtr]([Int64]$raw) }
  if ([int]$target.process_id -gt 0) {
    $process = Get-Process -Id ([int]$target.process_id) -ErrorAction Stop
    if ($process.MainWindowHandle -ne 0) { return [IntPtr]$process.MainWindowHandle }
    throw 'windows_desktop_target_missing'
  }
  if ([string]$target.title_contains) {
    $needle = [string]$target.title_contains
    $match = Get-Process | Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -like ('*' + $needle + '*') } | Select-Object -First 1
    if ($match) { return [IntPtr]$match.MainWindowHandle }
    throw 'windows_desktop_target_missing'
  }
  return [WasmAgentUser32]::GetForegroundWindow()
}

function PatternNames($element) {
  $patterns = @()
  foreach ($pair in @(
    @('invoke', [Windows.Automation.InvokePattern]::Pattern),
    @('value', [Windows.Automation.ValuePattern]::Pattern),
    @('toggle', [Windows.Automation.TogglePattern]::Pattern),
    @('select', [Windows.Automation.SelectionItemPattern]::Pattern),
    @('expand_collapse', [Windows.Automation.ExpandCollapsePattern]::Pattern)
  )) {
    $candidate = $null
    if ($element.TryGetCurrentPattern($pair[1], [ref]$candidate)) { $patterns += $pair[0] }
  }
  return @($patterns)
}

function Clip([string]$value, [int]$limit) {
  if ($null -eq $value) { return '' }
  if ($value.Length -le $limit) { return $value }
  return $value.Substring(0, $limit)
}

function ElementRecord($element, [bool]$includeValue=$false) {
  $current = $element.Current
  $rect = $current.BoundingRectangle
  $value = $null
  $valueTruncated = $false
  $isPassword = [bool]$current.IsPassword
  $valuePattern = $null
  if ($includeValue -and -not $isPassword -and $element.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern, [ref]$valuePattern)) {
    $rawValue = [string]$valuePattern.Current.Value
    $valueTruncated = $rawValue.Length -gt 4096
    $value = Clip $rawValue 4096
  }
  $toggle = $null
  $togglePattern = $null
  if ($element.TryGetCurrentPattern([Windows.Automation.TogglePattern]::Pattern, [ref]$togglePattern)) { $toggle = [string]$togglePattern.Current.ToggleState }
  $selected = $null
  $selectionPattern = $null
  if ($element.TryGetCurrentPattern([Windows.Automation.SelectionItemPattern]::Pattern, [ref]$selectionPattern)) { $selected = [bool]$selectionPattern.Current.IsSelected }
  $expanded = $null
  $expandPattern = $null
  if ($element.TryGetCurrentPattern([Windows.Automation.ExpandCollapsePattern]::Pattern, [ref]$expandPattern)) { $expanded = [string]$expandPattern.Current.ExpandCollapseState }
  return [ordered]@{
    name=(Clip ([string]$current.Name) 240); automation_id=(Clip ([string]$current.AutomationId) 240)
    control_type=(Clip ([string]$current.ControlType.ProgrammaticName) 120)
    process_id=[int]$current.ProcessId; runtime_id=@($element.GetRuntimeId()); enabled=[bool]$current.IsEnabled; offscreen=[bool]$current.IsOffscreen
    bounds=@([int]$rect.X,[int]$rect.Y,[int]$rect.Width,[int]$rect.Height)
    patterns=@(PatternNames $element); value=$value; value_truncated=$valueTruncated; sensitive=$isPassword; redacted=$isPassword
    toggle_state=$toggle; selected=$selected; expanded=$expanded
  }
}

function Descendants($root, [int]$limit, [int]$maxDepth) {
  $result = New-Object Collections.ArrayList
  [void]$result.Add($root)
  $queue = New-Object Collections.Queue
  $walker = [Windows.Automation.TreeWalker]::ControlViewWalker
  $first = $walker.GetFirstChild($root)
  if ($first) { $queue.Enqueue([pscustomobject]@{ element=$first; depth=1 }) }
  while ($queue.Count -gt 0 -and $result.Count -lt $limit) {
    $entry = $queue.Dequeue(); $element = $entry.element; $depth = [int]$entry.depth
    [void]$result.Add($element)
    if ($depth -lt $maxDepth) {
      $child = $walker.GetFirstChild($element)
      if ($child) { $queue.Enqueue([pscustomobject]@{ element=$child; depth=$depth + 1 }) }
    }
    $sibling = $walker.GetNextSibling($element)
    if ($sibling) { $queue.Enqueue([pscustomobject]@{ element=$sibling; depth=$depth }) }
  }
  return $result.ToArray()
}

function ResolveElement($root, $runtimeId) {
  $wanted = (@($runtimeId) -join '.')
  foreach ($candidate in @(Descendants $root 4096 64)) {
    try { if ((@($candidate.GetRuntimeId()) -join '.') -eq $wanted) { return $candidate } } catch { }
  }
  return $null
}

function PropertyValue($record, [string]$name) {
  if ($name -eq 'name') { return $record.name }
  if ($name -eq 'value') { return $record.value }
  if ($name -eq 'toggle_state') { return $record.toggle_state }
  if ($name -eq 'enabled') { return $record.enabled }
  if ($name -eq 'offscreen') { return $record.offscreen }
  if ($name -eq 'selected') { return $record.selected }
  if ($name -eq 'expanded') { return $record.expanded }
  throw 'windows_desktop_property_unsupported'
}

$hwnd = WindowHandle $request.target
if ($hwnd -eq [IntPtr]::Zero) { throw 'windows_desktop_window_missing' }
$root = [Windows.Automation.AutomationElement]::FromHandle($hwnd)
if (-not $root) { throw 'windows_desktop_root_missing' }
$windowRecord = ElementRecord $root

if ($request.operation -eq 'inspect') {
  $elements = @()
  $enumerationErrors = 0
  foreach ($element in @(Descendants $root ([int]$request.max_elements) ([int]$request.max_depth))) {
    try { $elements += ,(ElementRecord $element ([bool]$request.include_values)) } catch { $enumerationErrors += 1 }
  }
  if ($elements.Count -eq 0) { throw 'windows_desktop_enumeration_empty' }
  [ordered]@{
    schema='${SCHEMA}'; ok=$true; operation='inspect'; hwnd=('0x{0:X}' -f $hwnd.ToInt64())
    window=$windowRecord; elements=$elements; truncated=($elements.Count -ge [int]$request.max_elements)
    element_count=$elements.Count; enumeration_errors=$enumerationErrors; tree_view='control'
    authority='current_user_token'; proof=@('windows.uia.snapshot')
  } | ConvertTo-Json -Compress -Depth 8
  exit 0
}

$element = ResolveElement $root $request.selector.runtime_id
if (-not $element) { throw 'windows_desktop_element_stale' }
$before = ElementRecord $element $true
if ($request.operation -eq 'act') {
  $pattern = $null
  switch ([string]$request.action) {
    'focus' { $element.SetFocus() }
    { $_ -in @('invoke','click') } {
      if (-not $element.TryGetCurrentPattern([Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) { throw 'windows_desktop_invoke_unsupported' }
      $pattern.Invoke()
    }
    'set_value' {
      if (-not $element.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern, [ref]$pattern)) { throw 'windows_desktop_value_unsupported' }
      $pattern.SetValue([string]$request.value)
    }
    'toggle' {
      if (-not $element.TryGetCurrentPattern([Windows.Automation.TogglePattern]::Pattern, [ref]$pattern)) { throw 'windows_desktop_toggle_unsupported' }
      $pattern.Toggle()
    }
    'select' {
      if (-not $element.TryGetCurrentPattern([Windows.Automation.SelectionItemPattern]::Pattern, [ref]$pattern)) { throw 'windows_desktop_select_unsupported' }
      $pattern.Select()
    }
    { $_ -in @('expand','collapse') } {
      if (-not $element.TryGetCurrentPattern([Windows.Automation.ExpandCollapsePattern]::Pattern, [ref]$pattern)) { throw 'windows_desktop_expand_unsupported' }
      if ($request.action -eq 'expand') { $pattern.Expand() } else { $pattern.Collapse() }
    }
    default { throw 'windows_desktop_action_unsupported' }
  }
  Start-Sleep -Milliseconds 120
}
$freshRoot = [Windows.Automation.AutomationElement]::FromHandle($hwnd)
$freshElement = ResolveElement $freshRoot $request.selector.runtime_id
$after = if ($freshElement) { ElementRecord $freshElement $true } else { $null }
$verified = $false
$observed = $null
if ($request.expect -and $after) {
  $observed = PropertyValue $after ([string]$request.expect.property)
  $verified = ($observed -eq $request.expect.equals)
}
[ordered]@{
  schema='${SCHEMA}'; ok=$true; operation=[string]$request.operation; action=[string]$request.action
  hwnd=('0x{0:X}' -f $hwnd.ToInt64()); window=$windowRecord; before=$before; after=$after
  expectation=$request.expect; observed=$observed; independently_verified=$verified
  authority='current_user_token'; proof=@('windows.uia.action_receipt') + $(if ($verified) { 'windows.uia.postcondition' } else { @() })
} | ConvertTo-Json -Compress -Depth 8
`;
}

function createWindowsDesktopAutomation({ spawn = spawnProcess, platform = process.platform, now = Date.now } = {}) {
  const snapshots = new Map();
  const describe = () => ({
    schema: SCHEMA, ok: platform === "win32", operation: "describe",
    authority: "current_user_token", integrity_level: "caller",
    elevation_supported: false, secure_desktop_supported: false,
    elevation_boundary: "separate_signed_broker_required",
    actions: ACTIONS, properties: PROPERTIES,
    limits: { snapshot_ttl_ms: SNAPSHOT_TTL_MS, max_elements: 200, max_depth: 32, payload_bytes: 65_536, output_bytes: 2_097_152, value_chars: 4_096 },
    proof: ["windows.desktop.capability_manifest"],
    ...(platform === "win32" ? {} : { error: "windows_native_shell_required" }),
  });

  const pruneSnapshots = () => {
    const cutoff = now() - SNAPSHOT_TTL_MS;
    for (const [id, snapshot] of snapshots) if (snapshot.created_at_ms < cutoff) snapshots.delete(id);
    while (snapshots.size > 8) snapshots.delete(snapshots.keys().next().value);
  };

  const run = (request, timeoutMs) => new Promise((resolve) => {
    const stdout = []; const stderr = []; let settled = false; let outputBytes = 0;
    const child = spawn("powershell.exe", ["-NoLogo", "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encodedPowerShell(automationScript(request))], { windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
    const timer = setTimeout(() => child.kill("SIGTERM"), timeoutMs); timer.unref?.();
    const finish = (code, spawnError = "") => {
      if (settled) return; settled = true; clearTimeout(timer);
      const output = Buffer.concat(stdout).toString("utf8").trim();
      let receipt = {}; try { receipt = JSON.parse(output.split(/\r?\n/).filter(Boolean).at(-1) || "{}"); } catch { receipt = {}; }
      resolve({ ...receipt, schema: SCHEMA, ok: code === 0 && receipt.ok === true && !spawnError, exit_code: Number.isInteger(code) ? code : null, error: String(spawnError || (code === 0 ? "" : Buffer.concat(stderr).toString("utf8").trim() || "windows_desktop_automation_failed")).slice(0, 2000) });
    };
    const collect = (target, chunk) => {
      outputBytes += chunk.length;
      if (outputBytes > 2_097_152) {
        child.kill("SIGTERM");
        finish(null, "windows_desktop_output_limit_exceeded");
        return;
      }
      target.push(Buffer.from(chunk));
    };
    child.stdout?.on("data", (chunk) => collect(stdout, chunk));
    child.stderr?.on("data", (chunk) => collect(stderr, chunk));
    child.once("error", (error) => finish(null, error?.message || error)); child.once("close", (code) => finish(code));
  });

  const execute = async (operation, payload = {}, commandId = "") => {
    let request;
    try { request = normalizedRequest(operation, payload); } catch (error) { return { schema: SCHEMA, ok: false, command_id: String(commandId || ""), error: String(error?.message || error) }; }
    if (operation === "windows_desktop_describe") return { ...describe(), command_id: String(commandId || "") };
    if (platform !== "win32") return { schema: SCHEMA, ok: false, command_id: String(commandId || ""), error: "windows_native_shell_required" };
    pruneSnapshots();
    if (operation === "windows_desktop_inspect") {
      const receipt = await run({ operation: "inspect", ...request }, request.timeout_ms);
      if (!receipt.ok) return { ...receipt, command_id: String(commandId || "") };
      const snapshotId = `s-${crypto.randomBytes(8).toString("hex")}`;
      const elements = (Array.isArray(receipt.elements) ? receipt.elements : []).slice(0, request.max_elements).map((element, index) => ({ ...element, ref: `e${index}` }));
      snapshots.set(snapshotId, { created_at_ms: now(), hwnd: receipt.hwnd, elements: new Map(elements.map((element) => [element.ref, element])) });
      return { ...receipt, elements, snapshot_id: snapshotId, expires_in_ms: SNAPSHOT_TTL_MS, command_id: String(commandId || "") };
    }
    const snapshot = snapshots.get(request.snapshot_id);
    const element = snapshot?.elements.get(request.ref);
    if (!snapshot || !element) return { schema: SCHEMA, ok: false, command_id: String(commandId || ""), error: "windows_desktop_snapshot_stale" };
    const receipt = await run({ operation: operation === "windows_desktop_act" ? "act" : "prove", target: { hwnd: snapshot.hwnd }, selector: { runtime_id: element.runtime_id }, action: request.action, value: request.value, expect: request.expect }, request.timeout_ms);
    return { ...receipt, snapshot_id: request.snapshot_id, ref: request.ref, command_id: String(commandId || "") };
  };

  return { describe, execute };
}

module.exports = { ACTIONS, PROPERTIES, SCHEMA, SNAPSHOT_TTL_MS, WINDOWS_DESKTOP_OPERATIONS, automationScript, createWindowsDesktopAutomation, normalizedRequest };
