<# Start de lokale stack: INVENTory (:8080) + coordinator (:8000).
   Alleen loopback, twee vensters. Stoppen: vensters sluiten.
   Vereist: venvs bestaan al (zie AGENTS.md per projectdir). #>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$inv = Join-Path $root "inventory\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $inv)) { $inv = "python" }
Start-Process -FilePath $inv -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8080" -WorkingDirectory (Join-Path $root "inventory") -WindowStyle Normal

$coord = Join-Path $root "mycelium-ai-main\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $coord)) { $coord = "python" }
Start-Process -FilePath $coord -ArgumentList "-m", "uvicorn", "coordinator.app.main:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory (Join-Path $root "mycelium-ai-main") -WindowStyle Normal

Write-Output "Gestart: INVENTory http://127.0.0.1:8080 + coordinator http://127.0.0.1:8000"
