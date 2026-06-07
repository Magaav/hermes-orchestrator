param(
  [string]$ExePath = "",
  [string]$ReportPath = "",
  [int]$WaitSeconds = 120,
  [switch]$Launch,
  [switch]$InteractiveLogin,
  [switch]$SkipRestart,
  [switch]$Pause
)

$ErrorActionPreference = "Stop"
$script:Steps = @()
$script:FailureClassification = ""
$script:FailureMessage = ""

function Wait-IfRequested {
  if ($Pause) {
    Write-Host ""
    Read-Host "Press Enter to close"
  }
}

function Add-Step {
  param([string]$Name, [bool]$Ok, [object]$Details = $null)
  $script:Steps += [ordered]@{
    name = $Name
    ok = $Ok
    at = (Get-Date).ToUniversalTime().ToString("o")
    details = $Details
  }
}

function Find-WasmAgentExe {
  if ($ExePath -and (Test-Path $ExePath)) { return (Resolve-Path $ExePath).Path }
  $process = Get-Process "WASM Agent" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($process -and $process.Path) { return $process.Path }
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\WASM Agent\WASM Agent.exe"),
    (Join-Path $env:LOCALAPPDATA "WASM Agent Native\WASM Agent.exe"),
    (Join-Path $env:ProgramFiles "WASM Agent\WASM Agent.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "WASM Agent\WASM Agent.exe")
  ) | Where-Object { $_ -and (Test-Path $_) }
  return ($candidates | Select-Object -First 1)
}

function Read-Diagnostics {
  $path = Join-Path $env:LOCALAPPDATA "WASM Agent Native\runtime-diagnostics.json"
  if (!(Test-Path $path)) { return $null }
  try {
    return Get-Content -Raw -Path $path | ConvertFrom-Json
  } catch {
    return $null
  }
}

function Wait-Diagnostics {
  param([scriptblock]$Predicate, [string]$StepName)
  $deadline = (Get-Date).AddSeconds($WaitSeconds)
  do {
    $diag = Read-Diagnostics
    if ($diag -and (& $Predicate $diag)) {
      Add-Step $StepName $true @{ diagnosticsPath = (Join-Path $env:LOCALAPPDATA "WASM Agent Native\runtime-diagnostics.json") }
      return $diag
    }
    Start-Sleep -Milliseconds 750
  } while ((Get-Date) -lt $deadline)
  Add-Step $StepName $false @{ timeoutSeconds = $WaitSeconds }
  return $diag
}

function Get-AuthCookie {
  param($Diagnostics)
  if (-not $Diagnostics -or -not $Diagnostics.authCookie) { return $null }
  return $Diagnostics.authCookie
}

function Get-AuthSession {
  param($Diagnostics)
  if (-not $Diagnostics -or -not $Diagnostics.authSession) { return $null }
  return $Diagnostics.authSession
}

function Classify-Failure {
  param($Diagnostics, [string]$Message)
  $messageText = [string]$Message
  $route = [string]($Diagnostics.currentRoute)
  $lastFailure = [string]($Diagnostics.lastFailureReason)
  $authCookie = Get-AuthCookie $Diagnostics
  $authSession = Get-AuthSession $Diagnostics
  $fatal = $Diagnostics.last_frontend_fatal_error
  if ($fatal -or $messageText -match "bootstrap|fatal|main_bootstrap_error|Cannot assign") { return "frontend bootstrap crash" }
  if ($messageText -match "config\.json|backend|candidate" -or $lastFailure -match "config") { return "backend/config discovery failure" }
  if (-not $authCookie -or $authCookie.hasWaUid -ne $true) { return "cookie missing" }
  $waCookie = @($authCookie.cookieMeta) | Select-Object -First 1
  if ($waCookie -and $waCookie.domain -and $waCookie.domain -notlike "*wa.colmeio.com") { return "cookie wrong domain" }
  if ($authSession -and ([int]$authSession.status -ne 200 -or $authSession.authenticated -ne $true)) { return "cookie wrong partition" }
  if ($route -match "auth_error|auth_code" -or $messageText -match "redeem|redirect|google") { return "Google redirect/code redemption failure" }
  if ($route -match "frontierReload" -or $messageText -match "cache|stale") { return "cloud asset stale/cache issue" }
  if ($route -match "^file:|^wasm-agent:" -or $messageText -match "shell|process|window") { return "native shell issue" }
  if ($messageText -match "asar|manifest|installer|shortcut|forbidden production string") { return "installer packaging issue" }
  return "native shell issue"
}

function Close-WasmAgent {
  $processes = @(Get-Process "WASM Agent" -ErrorAction SilentlyContinue)
  foreach ($process in $processes) {
    try {
      if ($process.MainWindowHandle -ne 0) {
        [void]$process.CloseMainWindow()
      }
    } catch {}
  }
  Start-Sleep -Seconds 3
  $remaining = @(Get-Process "WASM Agent" -ErrorAction SilentlyContinue)
  foreach ($process in $remaining) {
    try { Stop-Process -Id $process.Id -Force } catch {}
  }
  Start-Sleep -Seconds 2
  Add-Step "fully close app" $true @{ closedProcesses = $processes.Count }
}

function Start-WasmAgent {
  param([string]$Path)
  $existing = Get-Process "WASM Agent" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($existing) {
    Add-Step "launch installed app" $true @{ alreadyRunning = $true; path = $existing.Path }
    return $existing
  }
  if (-not $Path -or !(Test-Path $Path)) {
    throw "Installed WASM Agent exe not found. Pass -ExePath or start the installed app once."
  }
  $process = Start-Process -FilePath $Path -PassThru
  Add-Step "launch installed app" $true @{ alreadyRunning = $false; path = $Path; pid = $process.Id }
  return $process
}

function Test-CloudConfig {
  try {
    $response = Invoke-WebRequest -Uri "https://wa.colmeio.com/config.json" -UseBasicParsing -TimeoutSec 15
    Add-Step "confirm /config.json reachable" ($response.StatusCode -eq 200) @{ status = $response.StatusCode }
    return $response.StatusCode -eq 200
  } catch {
    Add-Step "confirm /config.json reachable" $false @{ error = $_.Exception.Message }
    return $false
  }
}

function Assert-InstalledArtifact {
  param([string]$Path)
  $appDir = Split-Path -Parent $Path
  $resourcesDir = Join-Path $appDir "resources"
  $appAsar = Join-Path $resourcesDir "app.asar"
  if (!(Test-Path $appAsar)) { throw "Installed app.asar missing: $appAsar" }
  $installedHash = (Get-FileHash -Algorithm SHA256 -Path $appAsar).Hash.ToLowerInvariant()
  $asarBytes = [System.IO.File]::ReadAllBytes($appAsar)
  $asarText = [System.Text.Encoding]::UTF8.GetString($asarBytes)
  foreach ($forbidden in @("http://127.0.0.1:8877", "http://localhost:8877", "http://0.0.0.0:8877", "127.0.0.1:8877", "localhost:8877", "WASM Agent native build loading")) {
    if ($asarText.Contains($forbidden)) {
      throw "Installed app.asar contains forbidden production string: $forbidden"
    }
  }
  Add-Step "inspect installed app.asar" $true @{ appAsar = $appAsar; sha256 = $installedHash }
  return @{ appAsar = $appAsar; appAsarSha256 = $installedHash }
}

function Assert-Session {
  param($Diagnostics, [string]$Phase)
  if ($Diagnostics.allowLocalDev -ne $false) { throw "$Phase diagnostics allowLocalDev is not false." }
  if ($Diagnostics.candidateList.Count -ne 1 -or $Diagnostics.candidateList[0] -ne "https://wa.colmeio.com") {
    throw "$Phase diagnostics candidate list is not cloud-only: $($Diagnostics.candidateList -join ', ')"
  }
  if ($Diagnostics.currentRoute -ne "https://wa.colmeio.com/home?native=electron") {
    throw "$Phase currentRoute is not the production Electron home route: $($Diagnostics.currentRoute)"
  }
  $authCookie = Get-AuthCookie $Diagnostics
  if (-not $authCookie -or $authCookie.hasWaUid -ne $true) {
    throw "$Phase diagnostics do not show authCookie.hasWaUid true."
  }
  $waCookie = @($authCookie.cookieMeta) | Select-Object -First 1
  if (-not $waCookie) { throw "$Phase diagnostics are missing wa_uid cookie metadata." }
  if ($waCookie.session -eq $true -or [double]$waCookie.expirationDate -le 0) {
    throw "$Phase wa_uid is session-only or missing expirationDate. session=$($waCookie.session) expirationDate=$($waCookie.expirationDate)"
  }
  if ($waCookie.domain -notlike "*wa.colmeio.com") { throw "$Phase wa_uid domain is unexpected: $($waCookie.domain)" }
  if ($waCookie.path -ne "/") { throw "$Phase wa_uid path is unexpected: $($waCookie.path)" }
  $authSession = Get-AuthSession $Diagnostics
  if (-not $authSession -or [int]$authSession.status -ne 200 -or $authSession.authenticated -ne $true) {
    throw "$Phase /auth/session is not authenticated. status=$($authSession.status) authenticated=$($authSession.authenticated)"
  }
  Add-Step "confirm $Phase authenticated session" $true @{
    authCookieHasWaUid = $true
    authSessionStatus = $authSession.status
    currentRoute = $Diagnostics.currentRoute
  }
}

function Write-Report {
  param([bool]$Ok, [object]$Artifact, $Before, $After)
  $releaseCandidate = Join-Path $PSScriptRoot "..\release"
  $releaseDir = if (Test-Path $releaseCandidate) { (Resolve-Path $releaseCandidate).Path } else { $PSScriptRoot }
  if (-not $ReportPath) {
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $script:ReportPath = Join-Path $releaseDir "installed-app-VERIFY-$stamp.json"
  }
  $report = [ordered]@{
    ok = $Ok
    schema = "hermes.wasm_agent.windows_installed_lifecycle_verify.v1"
    generatedAt = (Get-Date).ToUniversalTime().ToString("o")
    verifier = $MyInvocation.MyCommand.Path
    target = "installed-windows-app"
    productionAppUrl = "https://wa.colmeio.com/home?native=electron"
    backend = "https://wa.colmeio.com"
    failureClassification = $script:FailureClassification
    failureMessage = $script:FailureMessage
    steps = $script:Steps
    artifact = $Artifact
    diagnosticsBeforeReopen = $Before
    diagnosticsAfterReopen = $After
  }
  $report | ConvertTo-Json -Depth 24 | Set-Content -Path $ReportPath -Encoding UTF8
  Write-Host "Verifier report: $ReportPath"
}

try {
  $resolvedExe = Find-WasmAgentExe
  if (-not $resolvedExe) {
    throw "Installed WASM Agent exe not found. Install the final NSIS artifact, then rerun this verifier."
  }
  $artifact = Assert-InstalledArtifact $resolvedExe

  if ($Launch) {
    Start-WasmAgent $resolvedExe | Out-Null
  } elseif (-not (Get-Process "WASM Agent" -ErrorAction SilentlyContinue)) {
    Start-WasmAgent $resolvedExe | Out-Null
  } else {
    Add-Step "launch installed app" $true @{ alreadyRunning = $true; path = $resolvedExe }
  }

  $before = Wait-Diagnostics { param($diag) $diag.currentRoute -eq "https://wa.colmeio.com/home?native=electron" } "confirm cloud URL loaded"
  if (-not $before) { throw "Runtime diagnostics did not appear." }
  Test-CloudConfig | Out-Null

  if (-not $before.authCookie -or $before.authCookie.hasWaUid -ne $true) {
    Add-Step "run Google login or detect existing login" $false @{ existingLogin = $false }
    if ($InteractiveLogin) {
      Write-Host "Complete Google login in the WASM Agent window. Waiting up to $WaitSeconds seconds..."
      $before = Wait-Diagnostics { param($diag) $diag.authCookie -and $diag.authCookie.hasWaUid -eq $true } "wait for Google login"
    } else {
      throw "No existing Google login detected. Rerun with -InteractiveLogin after installing the app."
    }
  } else {
    Add-Step "run Google login or detect existing login" $true @{ existingLogin = $true }
  }
  Assert-Session $before "before reopen"

  if (-not $SkipRestart) {
    Close-WasmAgent
    Start-WasmAgent $resolvedExe | Out-Null
    $after = Wait-Diagnostics { param($diag) $diag.currentRoute -eq "https://wa.colmeio.com/home?native=electron" } "reopen from installed exe"
    Assert-Session $after "after reopen"
  } else {
    $after = $before
    Add-Step "reopen from installed exe" $true @{ skipped = $true }
  }

  Write-Report $true $artifact $before $after
  Write-Host "Installed WASM Agent lifecycle verifier ok"
  Wait-IfRequested
} catch {
  $script:FailureMessage = $_.Exception.Message
  $diag = Read-Diagnostics
  $script:FailureClassification = Classify-Failure $diag $script:FailureMessage
  Add-Step "failure classification" $false @{ classification = $script:FailureClassification; message = $script:FailureMessage }
  Write-Report $false $null $diag $null
  Write-Host "Installed WASM Agent verifier failed" -ForegroundColor Red
  Write-Host $script:FailureMessage -ForegroundColor Red
  Write-Host "Classification: $script:FailureClassification" -ForegroundColor Red
  Wait-IfRequested
  exit 1
}
