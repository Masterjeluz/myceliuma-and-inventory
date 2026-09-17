# Mycelium coordinator launcher (Windows, no admin needed).
# Starts uvicorn on loopback only. Pass -Agent to also start the
# desktop agent in safe (observe-only) mode.
param([switch]$Agent)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Project = Split-Path -Parent $Root
Set-Location $Project

if (-not (Test-Path $Project)) {
    throw "Project dir missing: $Project"
}

$coordinator = Start-Process python `
    -ArgumentList "-m", "uvicorn", "coordinator.app.main:app",
        "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory $Project -PassThru
Write-Output "Coordinator PID $($coordinator.Id) on 127.0.0.1:8000"

if ($Agent) {
    $agent = Start-Process python `
        -ArgumentList "-m", "desktop_agent.main", "--read-only" `
        -WorkingDirectory $Project -PassThru
    Write-Output "Desktop agent PID $($agent.Id) (read-only mode)"
}

Write-Output "Health: http://127.0.0.1:8000/api/v1/health"
Write-Output "Stop with Ctrl+C in each window or Stop-Process."
