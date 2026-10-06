<# test-full: volledige suite, alleen op expliciet verzoek of voor milestone.
Gebruik: .\tools\test-full.ps1 -Project inventory
         .\tools\test-full.ps1 -Project all
Duurt minuten (coordinator ~1860 tests). Niet als standaard-verificatie. #>
param(
  [ValidateSet("inventory", "coordinator", "agent", "all")]
  [string]$Project = "inventory"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$tmp = [System.IO.Path]::GetTempPath()
$targets = if ($Project -eq "all") { @("inventory", "coordinator", "agent") } else { @($Project) }
$globalCode = 0

foreach ($p in $targets) {
  $dir = if ($p -eq "agent") { "Mycelium/agent" } elseif ($p -eq "inventory") { "inventory" } else { "mycelium-ai-main" }
  $env:MYCELIUM_DATABASE_PATH = Join-Path $tmp ("myc_full_{0}_{1}.db" -f $p, $PID)
  $env:MYCELIUM_CHAT_DATABASE_PATH = Join-Path $tmp ("myc_chat_full_{0}_{1}.db" -f $p, $PID)
  $env:INVENTORY_DATABASE_PATH = Join-Path $tmp ("inv_full_{0}_{1}.db" -f $p, $PID)
  Push-Location -LiteralPath (Join-Path $root $dir)
  try {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    & python -m pytest -q --tb=short
    $code = $LASTEXITCODE
    $sw.Stop()
    Write-Output ("test-full [{0}] exit={1} duur={2:N1}s" -f $p, $code, $sw.Elapsed.TotalSeconds)
    if ($code -ne 0) { $globalCode = $code }
  } finally { Pop-Location }
}
exit $globalCode
