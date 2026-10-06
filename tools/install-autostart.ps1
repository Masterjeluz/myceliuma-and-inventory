<# Registreer auto-start bij logon (Windows Task Scheduler).
   DIT SCRIPT ALS ADMIN DRAAIEN (rechtermuisklik PowerShell ->
   Als administrator), anders "Toegang geweigerd".
   Taken: MyceliumLocal (INVENTory :8080 + coordinator :8000) +
   OllamaServe (lokale modellen :11434; valt weg = NPC's vallen
   terug op Hermes, daarna eerlijke noot).
   Verwijderen: Unregister-ScheduledTask -TaskName "Mycelium*","OllamaServe". #>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$action1 = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -File `"$root\tools\start-local.ps1`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "MyceliumLocal" -Action $action1 -Trigger $trigger -Settings $settings -Description "Start INVENTory (:8080) + coordinator (:8000) bij logon" -Force | Out-Null

$ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
if (Test-Path -LiteralPath $ollama) {
  $action2 = New-ScheduledTaskAction -Execute $ollama -Argument "serve"
  Register-ScheduledTask -TaskName "OllamaServe" -Action $action2 -Trigger $trigger -Settings $settings -Description "Ollama :11434 bij logon (lokale modellen voor Mycelium)" -Force | Out-Null
} else {
  Write-Output "Ollama niet gevonden op $ollama — OllamaServe overgeslagen."
}

Write-Output "Geregistreerd: MyceliumLocal + OllamaServe (bij logon). Test met: Start-ScheduledTask -TaskName MyceliumLocal"
