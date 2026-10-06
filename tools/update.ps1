<# Update de lokale stack: fast-forward pull + dependencies.
   Doet nooit force/reset en commit/pusht niets. Na afloop zelf
   herstarten (vensters sluiten + tools/start-local.ps1). #>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Set-Location -LiteralPath $root
git pull --ff-only
if (-not $?) { throw "git pull weigerde (geen fast-forward?) — handmatig oplossen, niets geforceerd." }

foreach ($proj in @("inventory", "mycelium-ai-main")) {
  $venvPython = Join-Path $root "$proj\.venv\Scripts\python.exe"
  if (Test-Path -LiteralPath $venvPython) {
    & $venvPython -m pip install -e (Join-Path $root $proj)
  } else {
    Write-Output "Geen venv in $proj — sla pip over (handmatig: pip install -e ./$proj)"
  }
}
Write-Output "Update klaar. Herstart de twee uvicorn-vensters voor het nieuwe gedrag."
