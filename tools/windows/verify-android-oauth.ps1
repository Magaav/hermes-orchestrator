[CmdletBinding()]
param(
  [int]$WaitSeconds = 180
)

$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\.."))

Write-Host "WASM Agent Android OAuth verification fallback"
Write-Host "Preferred path: Open wasm-agent Windows app -> Diagnostics -> Verify Android OAuth."
Write-Host ""

function Resolve-RequiredCommand {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$InstallHint,
    [int]$ExitCode = 2
  )
  $command = Get-Command $Name -ErrorAction SilentlyContinue
  if (-not $command) {
    Write-Host "$Name is missing. $InstallHint"
    exit $ExitCode
  }
  return $command.Source
}

$adb = Resolve-RequiredCommand "adb" "Install Android SDK Platform Tools and add platform-tools to PATH: https://developer.android.com/tools/releases/platform-tools" 2
$horc = Resolve-RequiredCommand "horc" "Run this from a WASM Agent development shell where horc is available." 4

Write-Host "checking adb"
& $adb version
Write-Host ""

$deadline = (Get-Date).AddSeconds($WaitSeconds)
$authorized = $false
while ((Get-Date) -lt $deadline) {
  $raw = & $adb devices -l 2>&1
  $deviceLines = @($raw | Where-Object { $_ -and ($_ -notmatch "^List of devices attached") })
  $states = @()
  foreach ($line in $deviceLines) {
    if ($line -match "^\S+\s+(\S+)") {
      $states += $matches[1]
    }
  }
  if ($states -contains "device") {
    $authorized = $true
    break
  }
  if ($states -contains "unauthorized") {
    Write-Host "unauthorized: Unlock your phone and tap Allow USB debugging."
  } elseif ($states -contains "offline") {
    Write-Host "phone offline: reconnect USB or toggle USB debugging."
  } else {
    Write-Host "waiting for phone: plug Android phone by USB and enable USB debugging."
  }
  Start-Sleep -Seconds 2
}

if (-not $authorized) {
  Write-Warning "PENDING: real-device proof is still pending."
  exit 3
}

Write-Host "device authorized"
Write-Host "running horc simulate android --device --interactive-oauth"
& $horc simulate android --device --interactive-oauth
$horcExit = if ($null -eq $LASTEXITCODE) { 1 } else { [int]$LASTEXITCODE }

$summary = Join-Path (Get-Location) "reports\sim\android\latest\summary.md"
$status = ""
if (Test-Path $summary) {
  Write-Host ""
  Write-Host "Latest report: $summary"
  Write-Host ""
  $summaryText = Get-Content $summary -Raw
  Write-Host $summaryText
  if ($summaryText -match "(?im)^-\s*Status:\s*([A-Z]+)") {
    $status = $matches[1].ToUpperInvariant()
  }
} else {
  Write-Warning "Latest report not found: $summary"
}

if ($horcExit -eq 0 -and $status -eq "PASSED") {
  Write-Host "PASS: Android OAuth real-device proof passed."
  exit 0
}

if ($status -eq "PENDING") {
  Write-Warning "PENDING: real-device proof is still pending."
  exit 5
}

Write-Host "FAIL: Android OAuth real-device proof did not pass."
if ($horcExit -eq 0) {
  exit 5
}
exit $horcExit
