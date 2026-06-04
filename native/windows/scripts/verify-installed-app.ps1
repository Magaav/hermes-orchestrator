param(
  [switch]$Pause
)

function Wait-IfRequested {
  if ($Pause) {
    Write-Host ""
    Read-Host "Press Enter to close"
  }
}

try {
  $ErrorActionPreference = "Stop"

  $process = Get-Process "WASM Agent" -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $process) {
    throw "WASM Agent process is not running. Start the installed WASM Agent app, wait for it to load or show diagnostics, then run this verifier again."
  }

  $exePath = $process.Path
  if (-not $exePath) {
    throw "Could not resolve WASM Agent process path."
  }

  $appDir = Split-Path -Parent $exePath
  $resourcesDir = Join-Path $appDir "resources"
  $appAsar = Join-Path $resourcesDir "app.asar"
  $releaseCandidate = Join-Path $PSScriptRoot "..\release"
  $releaseDir = ""
  if (Test-Path $releaseCandidate) {
    $releaseDir = (Resolve-Path $releaseCandidate).Path
  }
  $manifest = if ($releaseDir) { Join-Path $releaseDir "release-manifest.json" } else { "" }
  if ($releaseDir -and !(Test-Path $manifest)) {
    $manifest = Get-ChildItem -Path $releaseDir -Filter "*.release-manifest.json" |
      Sort-Object LastWriteTime |
      Select-Object -Last 1 -ExpandProperty FullName
  }
  $diagnostics = Join-Path $env:LOCALAPPDATA "WASM Agent Native\runtime-diagnostics.json"
  $authDiagnostics = Join-Path $env:LOCALAPPDATA "WASM Agent Native\renderer-auth-diagnostics.log"

  if (!(Test-Path $appAsar)) { throw "Installed app.asar missing: $appAsar" }
  if (!(Test-Path $diagnostics)) { throw "Runtime diagnostics missing: $diagnostics" }

  $diagJson = Get-Content -Raw -Path $diagnostics | ConvertFrom-Json
  $installedHash = (Get-FileHash -Algorithm SHA256 -Path $appAsar).Hash.ToLowerInvariant()

  if ($manifest -and (Test-Path $manifest)) {
    $manifestJson = Get-Content -Raw -Path $manifest | ConvertFrom-Json
    if ($installedHash -ne [string]$manifestJson.appAsarSha256) {
      throw "Installed app.asar hash $installedHash does not match release manifest $($manifestJson.appAsarSha256)."
    }
  }

  $asarBytes = [System.IO.File]::ReadAllBytes($appAsar)
  $asarText = [System.Text.Encoding]::UTF8.GetString($asarBytes)
  foreach ($forbidden in @("http://127.0.0.1:8877", "http://localhost:8877", "http://0.0.0.0:8877", "127.0.0.1:8877", "localhost:8877", "WASM Agent native build loading")) {
    if ($asarText.Contains($forbidden)) {
      throw "Installed app.asar contains forbidden production string: $forbidden"
    }
  }

  if ($diagJson.allowLocalDev -ne $false) { throw "Runtime diagnostics allowLocalDev is not false." }
  if ($diagJson.candidateList.Count -ne 1 -or $diagJson.candidateList[0] -ne "https://wa.colmeio.com") {
    throw "Runtime diagnostics candidate list is not cloud-only: $($diagJson.candidateList -join ', ')"
  }

  Write-Host "Installed WASM Agent verifier ok"
  Write-Host "Process: $exePath"
  if ($manifest -and (Test-Path $manifest)) {
    Write-Host "Manifest: $manifest"
  } else {
    Write-Host "Manifest: not found; skipped installer hash comparison"
  }
  Write-Host "app.asar SHA-256: $installedHash"
  Write-Host "Runtime diagnostics: $diagnostics"
  Write-Host "Renderer auth diagnostics: $authDiagnostics"
  if (Test-Path $authDiagnostics) {
    Write-Host ""
    Write-Host "Last renderer auth diagnostics:"
    Get-Content -Path $authDiagnostics -Tail 30
  }
  Wait-IfRequested
} catch {
  Write-Host "Installed WASM Agent verifier failed" -ForegroundColor Red
  Write-Host $_.Exception.Message -ForegroundColor Red
  Wait-IfRequested
  exit 1
}
