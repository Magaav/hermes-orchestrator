$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Src = Join-Path $Root "src"
$Release = Join-Path $Root "release"
New-Item -ItemType Directory -Force -Path $Release | Out-Null
Push-Location $Src
try {
  npm install
  npm run build:win:x64
} finally {
  Pop-Location
}
$Artifact = Join-Path $Release "WASM-Agent-Setup-x64.exe"
if (!(Test-Path $Artifact)) {
  throw "Expected installer artifact was not created: $Artifact"
}
Write-Host "Built $Artifact"
Write-Host "Do not embed account secrets or device tokens in installer artifacts."
