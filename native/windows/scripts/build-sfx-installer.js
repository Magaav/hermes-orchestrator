#!/usr/bin/env node
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const windowsRoot = path.resolve(__dirname, "..");
const srcRoot = path.join(windowsRoot, "src");
const releaseRoot = path.join(windowsRoot, "release");
const unpackedRoot = path.join(releaseRoot, "win-unpacked");
const stageRoot = path.join(releaseRoot, "sfx-stage");
const appStage = path.join(stageRoot, "app");
const archivePath = path.join(releaseRoot, "WASM-Agent-Setup-x64.7z");
const configPath = path.join(releaseRoot, "WASM-Agent-Setup-x64.sfxconfig");
const outputPath = path.join(releaseRoot, "WASM-Agent-Setup-x64.exe");
const nativeDefaultsPath = path.join(srcRoot, "build", "native-defaults.json");
const verifyWindowsInstaller = path.join(windowsRoot, "scripts", "verify-windows-installer.js");
const sevenZip = path.join(srcRoot, "node_modules", "7zip-bin", "linux", "arm64", "7za");
const sfxStub = path.join(srcRoot, "node_modules", "maker-7z-sfx", "7zsd_extra_162_3888", "7zsd_All_x64.sfx");

function fail(message) {
  console.error(message);
  process.exit(1);
}

function write(file, text) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, text);
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: "inherit", ...options });
  if (result.status !== 0) fail(`Command failed (${result.status}): ${command} ${args.join(" ")}`);
}

function readJson(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return {};
  }
}

function safeFilenamePart(value) {
  return String(value || "").replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^[._-]+|[._-]+$/g, "");
}

function versionedInstallerName(defaults) {
  const version = safeFilenamePart(defaults.wasmAgentVersion || defaults.nativeShellVersion || "0.1.0");
  const buildId = safeFilenamePart(defaults.buildId || "");
  const buildSuffix = buildId.startsWith("win-x64-") ? buildId.slice("win-x64-".length) : buildId.replace(/^win-[^-]+-/, "");
  return `WASM-Agent-Setup-x64-${[version, buildSuffix].filter(Boolean).join("-")}.exe`;
}

if (!fs.existsSync(path.join(unpackedRoot, "WASM Agent.exe"))) {
  fail(`Missing packaged Electron app: ${path.join(unpackedRoot, "WASM Agent.exe")}`);
}
if (!fs.existsSync(sevenZip)) fail(`Missing 7zip binary: ${sevenZip}`);
if (!fs.existsSync(sfxStub)) fail(`Missing Windows x64 SFX stub: ${sfxStub}`);

fs.rmSync(stageRoot, { recursive: true, force: true });
fs.rmSync(archivePath, { force: true });
fs.rmSync(configPath, { force: true });
fs.rmSync(outputPath, { force: true });
fs.mkdirSync(appStage, { recursive: true });
fs.cpSync(unpackedRoot, appStage, { recursive: true, dereference: true });

write(path.join(stageRoot, "install.cmd"), `@echo off\r\nsetlocal\r\npowershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"\r\nif errorlevel 1 (\r\n  echo.\r\n  echo WASM Agent install failed. Keep this window open and share the error above.\r\n  pause\r\n)\r\n`);

write(path.join(stageRoot, "install.ps1"), `$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceApp = Join-Path $ScriptRoot "app"
$InstallDir = Join-Path $env:LOCALAPPDATA "WASM Agent Native"
$AppDir = Join-Path $InstallDir "app"
$ConfigDir = Join-Path $env:APPDATA "WASM Agent"
$ConfigPath = Join-Path $ConfigDir "config.json"
$StartMenu = Join-Path $env:APPDATA "Microsoft\\Windows\\Start Menu\\Programs"
$AppExe = Join-Path $AppDir "WASM Agent.exe"
$IconPath = Join-Path $AppDir "resources\\icon.ico"
$ShortcutReport = Join-Path $InstallDir "shortcut-report.txt"

function Add-ShortcutDirectory {
  param([System.Collections.Generic.List[string]]$Paths, [string]$Value)
  if ([string]::IsNullOrWhiteSpace($Value)) { return }
  $expanded = [Environment]::ExpandEnvironmentVariables($Value)
  if ([string]::IsNullOrWhiteSpace($expanded)) { return }
  foreach ($existingPath in $Paths) {
    if ([string]::Equals($existingPath, $expanded, [StringComparison]::OrdinalIgnoreCase)) { return }
  }
  $Paths.Add($expanded) | Out-Null
}

function New-WasmAgentShortcut {
  param([object]$Shell, [string]$Target)
  $parent = Split-Path -Parent $Target
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
  $shortcut = $Shell.CreateShortcut($Target)
  $shortcut.TargetPath = $AppExe
  $shortcut.WorkingDirectory = $AppDir
  $shortcut.Description = "Open WASM Agent native desktop app"
  $shortcut.IconLocation = if (Test-Path $IconPath) { $IconPath } else { "$AppExe,0" }
  $shortcut.Save()
  return $Target
}

if (!(Test-Path $SourceApp)) { throw "Missing bundled app payload: $SourceApp" }
New-Item -ItemType Directory -Force -Path $InstallDir, $ConfigDir, $StartMenu | Out-Null
if (Test-Path $AppDir) { Remove-Item -Recurse -Force $AppDir }
Copy-Item -Recurse -Force $SourceApp $AppDir

$existing = @{}
if (Test-Path $ConfigPath) {
  try {
    $parsed = Get-Content -Raw -Path $ConfigPath | ConvertFrom-Json
    if ($parsed) {
      foreach ($property in $parsed.PSObject.Properties) {
        $existing[$property.Name] = $property.Value
      }
    }
  } catch { $existing = @{} }
}
$DefaultsPath = Join-Path $AppDir "resources\\native-defaults.json"
$defaults = @{}
if (Test-Path $DefaultsPath) {
  try {
    $parsedDefaults = Get-Content -Raw -Path $DefaultsPath | ConvertFrom-Json
    if ($parsedDefaults) {
      foreach ($property in $parsedDefaults.PSObject.Properties) {
        $defaults[$property.Name] = $property.Value
      }
    }
  } catch { $defaults = @{} }
}
$defaultServerUrl = if ($defaults.serverUrl) { $defaults.serverUrl } else { "https://wa.colmeio.com" }
$serverUrl = if ($env:WASM_AGENT_SERVER_URL) { $env:WASM_AGENT_SERVER_URL } elseif ($existing.userExplicit -eq $true -and $existing.serverUrl) { $existing.serverUrl } else { $defaultServerUrl }
$deviceId = if ($existing.deviceId) { $existing.deviceId } else { "win-$([Environment]::MachineName)-$([Guid]::NewGuid().ToString('N').Substring(0, 12))" }
$config = [ordered]@{
  schema = "hermes.wasm_agent.windows_native_config.v1"
  serverUrl = $serverUrl
  deviceId = $deviceId
  accountId = if ($existing.accountId) { $existing.accountId } else { "" }
  deviceToken = if ($existing.deviceToken) { $existing.deviceToken } else { "" }
  installer = "WASM-Agent-Setup-x64.exe"
  userExplicit = if ($existing.userExplicit -eq $true) { $true } else { $false }
  installedAt = (Get-Date).ToUniversalTime().ToString("o")
  deviceRegistrationReady = $true
  heartbeatReady = $true
}
$config | ConvertTo-Json -Depth 5 | Set-Content -Path $ConfigPath -Encoding UTF8

$UninstallPath = Join-Path $InstallDir "uninstall-wasm-agent.cmd"
$UninstallPs1 = Join-Path $InstallDir "uninstall-wasm-agent.ps1"
Set-Content -Path $UninstallPath -Encoding ASCII -Value @"
@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall-wasm-agent.ps1"
"@
Set-Content -Path $UninstallPs1 -Encoding UTF8 -Value @'
$ErrorActionPreference = "SilentlyContinue"
$InstallDir = Join-Path $env:LOCALAPPDATA "WASM Agent Native"
$targets = New-Object System.Collections.Generic.List[string]
function Add-Target {
  param([string]$Value)
  if ([string]::IsNullOrWhiteSpace($Value)) { return }
  $expanded = [Environment]::ExpandEnvironmentVariables($Value)
  foreach ($existingPath in $targets) {
    if ([string]::Equals($existingPath, $expanded, [StringComparison]::OrdinalIgnoreCase)) { return }
  }
  $targets.Add($expanded) | Out-Null
}
Add-Target (Join-Path $env:APPDATA "Microsoft\\Windows\\Start Menu\\Programs\\WASM Agent.lnk")
Add-Target (Join-Path ([Environment]::GetFolderPath("DesktopDirectory")) "WASM Agent.lnk")
Add-Target (Join-Path ([Environment]::GetFolderPath("Desktop")) "WASM Agent.lnk")
Add-Target (Join-Path $env:USERPROFILE "Desktop\\WASM Agent.lnk")
if ($env:OneDrive) { Add-Target (Join-Path $env:OneDrive "Desktop\\WASM Agent.lnk") }
if ($env:OneDriveConsumer) { Add-Target (Join-Path $env:OneDriveConsumer "Desktop\\WASM Agent.lnk") }
if ($env:OneDriveCommercial) { Add-Target (Join-Path $env:OneDriveCommercial "Desktop\\WASM Agent.lnk") }
Add-Target (Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "WASM Agent.lnk")
foreach ($target in $targets) { Remove-Item -Force -Path $target }
Remove-Item -Recurse -Force -Path $InstallDir
Write-Host "WASM Agent native desktop app removed. Config remains in $env:APPDATA\\WASM Agent."
'@

try {
  $shell = New-Object -ComObject WScript.Shell
  $shortcutLines = New-Object System.Collections.Generic.List[string]
  $desktopDirs = New-Object System.Collections.Generic.List[string]
  Add-ShortcutDirectory $desktopDirs ([Environment]::GetFolderPath("DesktopDirectory"))
  Add-ShortcutDirectory $desktopDirs ([Environment]::GetFolderPath("Desktop"))
  Add-ShortcutDirectory $desktopDirs (Join-Path $env:USERPROFILE "Desktop")
  if ($env:OneDrive) { Add-ShortcutDirectory $desktopDirs (Join-Path $env:OneDrive "Desktop") }
  if ($env:OneDriveConsumer) { Add-ShortcutDirectory $desktopDirs (Join-Path $env:OneDriveConsumer "Desktop") }
  if ($env:OneDriveCommercial) { Add-ShortcutDirectory $desktopDirs (Join-Path $env:OneDriveCommercial "Desktop") }
  Add-ShortcutDirectory $desktopDirs ([Environment]::GetFolderPath("CommonDesktopDirectory"))

  foreach ($target in @((Join-Path $StartMenu "WASM Agent.lnk"))) {
    try {
      $created = New-WasmAgentShortcut $shell $target
      $shortcutLines.Add("ok | $created") | Out-Null
    } catch {
      $shortcutLines.Add("error | $target | $($_.Exception.Message)") | Out-Null
    }
  }
  foreach ($desktopDir in $desktopDirs) {
    $target = Join-Path $desktopDir "WASM Agent.lnk"
    try {
      $created = New-WasmAgentShortcut $shell $target
      $shortcutLines.Add("ok | $created") | Out-Null
    } catch {
      $shortcutLines.Add("error | $target | $($_.Exception.Message)") | Out-Null
    }
  }
  $shortcutLines | Set-Content -Path $ShortcutReport -Encoding UTF8
} catch {
  Write-Warning "Could not create shortcuts: $($_.Exception.Message)"
  "error | shortcut bootstrap | $($_.Exception.Message)" | Set-Content -Path $ShortcutReport -Encoding UTF8
}

Write-Host "WASM Agent installed: $AppExe"
Write-Host "Config: $ConfigPath"
Write-Host "Shortcut report: $ShortcutReport"
Write-Host "Start Menu/Desktop shortcuts created where permitted."
Start-Process -FilePath $AppExe
`);

write(path.join(stageRoot, "README.txt"), `WASM Agent Windows x64 native installer payload.

This installer installs a real Electron desktop app process, creates Start Menu
and Desktop shortcuts with the bundled WASM Agent icon, and persists local
config under %APPDATA%\\WASM Agent. Shortcut creation results are written to
%LOCALAPPDATA%\\WASM Agent Native\\shortcut-report.txt.

It does not use Edge/Chrome app mode and does not include account secrets or
device tokens. Device registration and heartbeat hooks are present in the app
and config contract. If the configured wasm-agent server is not reachable, the
desktop app opens a native setup screen instead of a blank window.
`);

run(sevenZip, ["a", "-t7z", "-mx=7", "-m0=lzma2", "-ms=on", archivePath, "."], { cwd: stageRoot });

write(configPath, `;!@Install@!UTF-8!
Title="WASM Agent Setup"
BeginPrompt="Install WASM Agent native desktop app?"
GUIMode="1"
OverwriteMode="2"
ExtractTitle="Installing WASM Agent"
ExtractDialogText="Installing WASM Agent native desktop app"
RunProgram="install.cmd"
;!@InstallEnd@!
`);

fs.writeFileSync(
  outputPath,
  Buffer.concat([fs.readFileSync(sfxStub), fs.readFileSync(configPath), fs.readFileSync(archivePath)])
);
fs.chmodSync(outputPath, 0o644);
const defaults = readJson(nativeDefaultsPath);
let versionedPath = "";
if (defaults && defaults.buildId) {
  versionedPath = path.join(releaseRoot, versionedInstallerName(defaults));
  fs.copyFileSync(outputPath, versionedPath);
  fs.writeFileSync(path.join(releaseRoot, `${path.basename(versionedPath, ".exe")}.native-defaults.json`), `${JSON.stringify(defaults, null, 2)}\n`);
  console.log(`Built ${versionedPath}`);
}
run(process.execPath, [verifyWindowsInstaller, outputPath]);
if (versionedPath) run(process.execPath, [verifyWindowsInstaller, versionedPath]);
fs.rmSync(stageRoot, { recursive: true, force: true });
fs.rmSync(archivePath, { force: true });
fs.rmSync(configPath, { force: true });
console.log(`Built ${outputPath}`);
