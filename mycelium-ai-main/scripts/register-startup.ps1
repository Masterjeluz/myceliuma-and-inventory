# Registers a USER-level logon task (no admin). The coordinator
# starts on loopback only; nothing clicks, prints, or moves hardware.
$TaskName = "MyceliumCoordinator"
$Project = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = (Get-Command python).Source

$Action = New-ScheduledTaskAction -Execute $Python `
    -Argument "-m uvicorn coordinator.app.main:app --host 127.0.0.1 --port 8000" `
    -WorkingDirectory $Project
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable -StopIfGoingOnBatteries:$false `
    -ExecutionTimeLimit (New-TimeSpan -Hours 12)
$Principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive

Register-ScheduledTask -TaskName $TaskName -Action $Action `
    -Trigger $Trigger -Settings $Settings -Principal $Principal -Force
Write-Output "Registered '$TaskName'. Disable via Task Scheduler or unregister-startup.ps1."
