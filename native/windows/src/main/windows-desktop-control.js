"use strict";

const { spawn: spawnProcess } = require("child_process");
const { WINDOWS_DESKTOP_OPERATIONS, createWindowsDesktopAutomation } = require("./windows-desktop/uia-control");

const SCHEMA = "hermes.wasm_agent.windows_notepad_uia_canary.v1";
const DEFAULT_TIMEOUT_MS = 30_000;

function cleanCanary(value) {
  const text = String(value || "").replace(/[\r\n\0]/g, " ").trim().slice(0, 240);
  if (!text) throw new Error("notepad_canary_missing");
  if (!/^[A-Za-z0-9 ._:-]+$/.test(text)) throw new Error("notepad_canary_invalid");
  return text;
}

function encodedPowerShell(script) {
  return Buffer.from(script, "utf16le").toString("base64");
}

function notepadCanaryScript(canary) {
  const literal = Buffer.from(cleanCanary(canary), "utf8").toString("base64");
  return `
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
$canary = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${literal}'))
$proofName = 'wasm-agent-uia-' + [Guid]::NewGuid().ToString('N') + '.txt'
$proofPath = Join-Path ([IO.Path]::GetTempPath()) $proofName
[IO.File]::WriteAllText($proofPath, '')
$launched = Start-Process notepad.exe -ArgumentList @($proofPath) -PassThru
$deadline = (Get-Date).AddSeconds(12)
$process = $null
$root = $null
do {
  Start-Sleep -Milliseconds 150
  foreach ($candidate in @(Get-Process -Name Notepad -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 })) {
    $candidateRoot = [Windows.Automation.AutomationElement]::FromHandle($candidate.MainWindowHandle)
    if ($candidateRoot -and $candidateRoot.Current.Name -like ('*' + $proofName + '*')) {
      $process = $candidate
      $root = $candidateRoot
      break
    }
  }
} while (-not $root -and (Get-Date) -lt $deadline)
if (-not $root) { throw 'notepad_proof_window_missing' }
$hwnd = $process.MainWindowHandle
$editCondition = New-Object Windows.Automation.PropertyCondition(
  [Windows.Automation.AutomationElement]::ControlTypeProperty,
  [Windows.Automation.ControlType]::Edit
)
$edit = $root.FindFirst([Windows.Automation.TreeScope]::Descendants, $editCondition)
$documentCondition = New-Object Windows.Automation.PropertyCondition(
  [Windows.Automation.AutomationElement]::ControlTypeProperty,
  [Windows.Automation.ControlType]::Document
)
if (-not $edit) { $edit = $root.FindFirst([Windows.Automation.TreeScope]::Descendants, $documentCondition) }
if (-not $edit) { throw 'notepad_text_control_missing' }
$edit.SetFocus()
$setMode = 'send_keys'
$valuePattern = $null
if ($edit.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern, [ref]$valuePattern)) {
  $valuePattern.SetValue($canary)
  $setMode = 'value_pattern'
} else {
  [Windows.Forms.SendKeys]::SendWait('^a')
  [Windows.Forms.SendKeys]::SendWait($canary.Replace('{','{{}').Replace('}','{}}'))
}
Start-Sleep -Milliseconds 300
$freshRoot = [Windows.Automation.AutomationElement]::FromHandle($hwnd)
$freshEdit = $freshRoot.FindFirst([Windows.Automation.TreeScope]::Descendants, $editCondition)
if (-not $freshEdit) { $freshEdit = $freshRoot.FindFirst([Windows.Automation.TreeScope]::Descendants, $documentCondition) }
$observed = ''
$freshValue = $null
$freshText = $null
if ($freshEdit.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern, [ref]$freshValue)) {
  $observed = [string]$freshValue.Current.Value
} elseif ($freshEdit.TryGetCurrentPattern([Windows.Automation.TextPattern]::Pattern, [ref]$freshText)) {
  $observed = [string]$freshText.DocumentRange.GetText(4096)
}
$observed = $observed.TrimEnd([char[]]@([char]13,[char]10))
$rect = $freshRoot.Current.BoundingRectangle
[ordered]@{
  schema='${SCHEMA}'
  ok=($observed -eq $canary)
  launched=$true
  process_id=$process.Id
  launched_process_id=$launched.Id
  proof_file=$proofName
  hwnd=('0x{0:X}' -f $hwnd.ToInt64())
  title=$freshRoot.Current.Name
  automation_id=$freshEdit.Current.AutomationId
  control_type=$freshEdit.Current.ControlType.ProgrammaticName
  set_mode=$setMode
  canary=$canary
  observed=$observed
  independently_verified=($observed -eq $canary)
  bounds=@([int]$rect.X,[int]$rect.Y,[int]$rect.Width,[int]$rect.Height)
  inherited_process_token=$true
} | ConvertTo-Json -Compress -Depth 4
`;
}

function createWindowsDesktopControl({ spawn = spawnProcess, platform = process.platform, now = Date.now } = {}) {
  const automation = createWindowsDesktopAutomation({ spawn, platform, now });
  async function runNotepadCanary(payload = {}, commandId = "") {
    if (platform !== "win32") return { schema: SCHEMA, ok: false, command_id: String(commandId || ""), error: "windows_native_shell_required" };
    const canary = cleanCanary(payload.canary || `wasm-agent-${now().toString(36)}`);
    const timeoutMs = Math.max(5_000, Math.min(Number(payload.timeout_ms || DEFAULT_TIMEOUT_MS), 60_000));
    const startedAt = new Date(now()).toISOString();
    return await new Promise((resolve) => {
      const stdout = [];
      const stderr = [];
      let settled = false;
      const child = spawn("powershell.exe", ["-NoLogo", "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encodedPowerShell(notepadCanaryScript(canary))], {
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
      });
      const timer = setTimeout(() => child.kill("SIGTERM"), timeoutMs);
      timer.unref?.();
      const finish = (code, error = "") => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        const output = Buffer.concat(stdout).toString("utf8").trim();
        let receipt = {};
        try { receipt = JSON.parse(output.split(/\r?\n/).filter(Boolean).at(-1) || "{}"); } catch { receipt = {}; }
        resolve({
          schema: SCHEMA,
          ...receipt,
          ok: code === 0 && receipt.ok === true && !error,
          command_id: String(commandId || ""),
          canary,
          started_at: startedAt,
          completed_at: new Date(now()).toISOString(),
          exit_code: Number.isInteger(code) ? code : null,
          error: String(error || (code === 0 ? "" : Buffer.concat(stderr).toString("utf8").trim() || "notepad_canary_failed")).slice(0, 2000),
        });
      };
      child.stdout?.on("data", (chunk) => stdout.push(Buffer.from(chunk)));
      child.stderr?.on("data", (chunk) => stderr.push(Buffer.from(chunk)));
      child.once("error", (error) => finish(null, error?.message || error));
      child.once("close", (code) => finish(code));
    });
  }
  return { describe: automation.describe, execute: automation.execute, runNotepadCanary };
}

module.exports = { SCHEMA, WINDOWS_DESKTOP_OPERATIONS, cleanCanary, createWindowsDesktopControl, encodedPowerShell, notepadCanaryScript };
