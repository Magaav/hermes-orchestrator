"use strict";
const { execFile } = require("node:child_process");
const SCHEMA = "hermes.wasm_agent.windows_cdp_session.v1";
const INCOGNITO_OPERATION = "open_windows_cdp_incognito";
const PERSISTENT_OPERATION = "open_windows_cdp_persistent";
const LEGACY_OPERATION = "open_windows_private_cdp";
const MAX_OUTPUT_BYTES = 32 * 1024;

function clean(value, limit = 500) { return String(value || "").replace(/\s+/g, " ").trim().slice(0, limit); }
function modeForOperation(operation) { return operation === PERSISTENT_OPERATION ? "persistent" : "incognito"; }
function normalize(value = {}, mode = "incognito") {
  const persistent = mode === "persistent";
  const port = Number(value.port), processId = Number(value.processId);
  const endpoint = clean(value.endpoint, 200), webSocketDebuggerUrl = clean(value.webSocketDebuggerUrl, 1000);
  const ready = Number.isInteger(port) && port > 0 && port <= 65535 && Number.isInteger(processId) && processId > 0
    && endpoint === `http://127.0.0.1:${port}` && webSocketDebuggerUrl.startsWith(`ws://127.0.0.1:${port}/`);
  const realm = persistent ? "browser_cdp_persistent" : "browser_cdp_incognito";
  return { schema: SCHEMA, operation: persistent ? PERSISTENT_OPERATION : INCOGNITO_OPERATION, ok: ready,
    failureClassification: ready ? null : "windows_cdp_postcondition_invalid", realm, defaultRealm: persistent,
    sessionId: clean(value.sessionId, 80), processId, port, endpoint, browser: clean(value.browser, 200),
    protocolVersion: clean(value.protocolVersion, 40), webSocketDebuggerUrl,
    profile: persistent ? "wasm_agent_persistent" : "temporary", storage: persistent ? "durable" : "ephemeral",
    isolation: persistent ? "dedicated_profile" : "incognito_isolated_profile",
    cleanup: persistent ? "retain_on_browser_exit" : "automatic_on_browser_exit",
    proof: ready ? [`windows.browser.cdp.${persistent ? "persistent" : "incognito"}.ready`] : [] };
}

function powershellScript(mode = "incognito") {
  const persistent = mode === "persistent";
  const profileLine = persistent
    ? "$profile = Join-Path $env:APPDATA 'WASM-Agent\\browser\\cdp-persistent'; $sessionId = 'browser-cdp-persistent'; New-Item -ItemType Directory -Force -Path $profile | Out-Null;"
    : "$sessionId = 'browser-cdp-incognito-' + [guid]::NewGuid().ToString('N'); $profile = Join-Path $env:TEMP $sessionId; New-Item -ItemType Directory -Force -Path $profile | Out-Null;";
  const incognitoFlag = persistent ? "" : ", '--incognito'";
  const cleanup = persistent ? [] : [
    "$cleanup = \"Wait-Process -Id $($process.Id) -ErrorAction SilentlyContinue; Remove-Item -LiteralPath '$profile' -Recurse -Force -ErrorAction SilentlyContinue\";",
    "Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-Command',$cleanup) | Out-Null;",
  ];
  return ["$ErrorActionPreference = 'Stop';", profileLine,
    "$candidates = @((Join-Path $env:ProgramFiles 'Google\\Chrome\\Application\\chrome.exe'), (Join-Path ${env:ProgramFiles(x86)} 'Google\\Chrome\\Application\\chrome.exe'), (Join-Path $env:LOCALAPPDATA 'Google\\Chrome\\Application\\chrome.exe'));",
    "$chrome = @($candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1); if (-not $chrome) { $chrome = [string](Get-Command chrome.exe -ErrorAction Stop).Source } else { $chrome = [string]$chrome[0] }",
    "$activePort = Join-Path $profile 'DevToolsActivePort';",
    "$existing = @(Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($profile) } | Select-Object -First 1);",
    "$process = $null; if ($existing) { $process = [pscustomobject]@{ Id=[int]$existing[0].ProcessId } } else { Remove-Item $activePort -Force -ErrorAction SilentlyContinue;",
    `  $arguments = @('--user-data-dir=' + $profile, '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0'${incognitoFlag}, '--no-first-run', '--no-default-browser-check', 'about:blank');`,
    "  $process = Start-Process -FilePath $chrome -ArgumentList $arguments -PassThru; }",
    "$deadline = [DateTime]::UtcNow.AddSeconds(12); while (-not (Test-Path $activePort) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 100 }",
    "if (-not (Test-Path $activePort)) { if ($process) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }; " + (persistent ? "" : "Remove-Item $profile -Recurse -Force -ErrorAction SilentlyContinue; ") + "throw 'DevToolsActivePort was not created' }",
    "$lines = @(Get-Content $activePort -ErrorAction Stop); $port = [int]$lines[0]; $version = Invoke-RestMethod -Uri ('http://127.0.0.1:' + $port + '/json/version') -TimeoutSec 5 -ErrorAction Stop;",
    ...cleanup,
    "[ordered]@{ sessionId=$sessionId; processId=[int]$process.Id; port=$port; endpoint=('http://127.0.0.1:' + $port); browser=[string]$version.Browser; protocolVersion=[string]$version.'Protocol-Version'; webSocketDebuggerUrl=[string]$version.webSocketDebuggerUrl } | ConvertTo-Json -Compress;"
  ].join("\n");
}
function executeOpen(mode, timeoutMs = 20_000) { return new Promise((resolve) => execFile("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", powershellScript(mode)], { timeout: timeoutMs, maxBuffer: MAX_OUTPUT_BYTES, windowsHide: true, encoding: "utf8" }, (error, stdout, stderr) => resolve({ ok: !error, stdout: String(stdout || ""), stderr: clean(stderr || error?.message, 1500), exitCode: Number.isInteger(error?.code) ? error.code : error ? 1 : 0, timedOut: Boolean(error?.killed) }))); }
async function run(context = {}, dependencies = {}) {
  const operation = String(context.operation?.name || LEGACY_OPERATION), mode = modeForOperation(operation);
  if ((dependencies.platform || process.platform) !== "win32") return { schema: SCHEMA, operation, ok: false, failureClassification: "windows_native_shell_required" };
  context.markPhase?.(`${mode}_cdp_launch_started`);
  const command = await (dependencies.executeOpen || executeOpen)(mode, 20_000);
  if (!command.ok) return { schema: SCHEMA, operation, ok: false, failureClassification: command.timedOut ? "windows_cdp_timeout" : "windows_cdp_launch_failed", error: clean(command.stderr, 1500), exitCode: command.exitCode, timedOut: command.timedOut };
  let value; try { value = JSON.parse(String(command.stdout || "")); } catch { return { schema: SCHEMA, operation, ok: false, failureClassification: "windows_cdp_output_invalid" }; }
  const result = normalize(value, mode); context.markPhase?.(`${mode}_cdp_ready`, { port: result.port, processId: result.processId, ready: result.ok, realm: result.realm }); return result;
}
module.exports = { INCOGNITO_OPERATION, LEGACY_OPERATION, PERSISTENT_OPERATION, SCHEMA, modeForOperation, normalize, powershellScript, run };
