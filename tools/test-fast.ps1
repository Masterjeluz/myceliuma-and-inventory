<# test-fast: run alleen de direct geraakte test(s) + directe dependencies.
Gebruik: .\tools\test-fast.ps1 -Project inventory -TestPath tests/test_objects.py
         .\tools\test-fast.ps1 -Project coordinator -TestPath tests/test_missions.py -K some_name
Bestaande pytest, geen nieuwe infra. Output kort (-q, --tb=short). #>
param(
  [ValidateSet("inventory", "coordinator", "agent")]
  [string]$Project = "inventory",
  [string]$TestPath = "",
  [string]$K = "",
  [int]$TimeoutSeconds = 300
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if ($Project -eq "agent") { $projDir = Join-Path $root "Mycelium/agent" }
elseif ($Project -eq "inventory") { $projDir = Join-Path $root "inventory" }
else { $projDir = Join-Path $root "mycelium-ai-main" }

# Tmp-DB discipline: raak nooit echte data aan (zie AGENTS.md).
$tmp = [System.IO.Path]::GetTempPath()
if ($Project -eq "inventory") { $env:INVENTORY_DATABASE_PATH = Join-Path $tmp ("inv_fast_{0}.db" -f $PID) }
else {
  $env:MYCELIUM_DATABASE_PATH = Join-Path $tmp ("myc_fast_{0}.db" -f $PID)
  $env:MYCELIUM_CHAT_DATABASE_PATH = Join-Path $tmp ("myc_chat_fast_{0}.db" -f $PID)
  $env:INVENTORY_DATABASE_PATH = Join-Path $tmp ("inv_fast_{0}.db" -f $PID)
}

$args = @("-q", "--tb=short")
if ($TestPath -ne "") { $args += $TestPath }
if ($K -ne "") { $args += @("-k", $K) }

$sw = [System.Diagnostics.Stopwatch]::StartNew()
Push-Location -LiteralPath $projDir
try {
  & python -m pytest @args
  $code = $LASTEXITCODE
} finally { Pop-Location }
$sw.Stop()
Write-Output ("test-fast [{0}] exit={1} duur={2:N1}s" -f $Project, $code, $sw.Elapsed.TotalSeconds)
exit $code
